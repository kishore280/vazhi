from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from vazhi.storage.postgres.models import Base

if TYPE_CHECKING:
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from psycopg_pool import AsyncConnectionPool

logger = logging.getLogger(__name__)

SCHEMA_VERSION_TABLE = "vazhi_schema_migrations"
BUSINESS_SCHEMA_VERSION = 7

LANGGRAPH_CHECKPOINT_SETUP_LOCK_KEY = 94721802


class PostgresManager:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.async_engine = create_async_engine(
            dsn,
            pool_pre_ping=True,  # before using test pananum
            pool_recycle=1800,  # close and replace pananum if more than 30mins connection
        )
        self.async_session = async_sessionmaker(
            bind=self.async_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        self.langgraph_pool: AsyncConnectionPool | None = None
        self.langgraph_checkpointer: AsyncPostgresSaver | None = None
        self._langgraph_checkpointer_setup = False

    @asynccontextmanager
    async def get_session(self):
        async with self.async_session() as session:
            yield session

    @asynccontextmanager
    async def schema_migration_lock(self):
        async with self.async_engine.connect() as conn:
            await conn.execute(text("SELECT pg_advisory_lock(hashtextextended('vazhi:schema-migration', 0))"))
            await conn.commit()
            try:
                yield
            finally:
                unlocked = await conn.scalar(
                    text("SELECT pg_advisory_unlock(hashtextextended('vazhi:schema-migration', 0))")
                )
                await conn.commit()
                if unlocked is not True:
                    await conn.close()
                    raise RuntimeError("Failed to release schema migration advisory lock")

    async def create_schema_version_table(self) -> None:
        async with self.async_engine.begin() as conn:
            await conn.execute(
                text(
                    f"""
                    CREATE TABLE IF NOT EXISTS {SCHEMA_VERSION_TABLE} (
                        domain VARCHAR(32) PRIMARY KEY,
                        version INTEGER NOT NULL CHECK (version > 0),
                        applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )

    async def get_schema_versions(self) -> dict[str, int]:
        async with self.async_engine.connect() as conn:
            exists = await conn.scalar(
                text("SELECT to_regclass(:table_name) IS NOT NULL"), {"table_name": SCHEMA_VERSION_TABLE}
            )
            if not exists:
                return {}
            rows = await conn.execute(text(f"SELECT domain, version FROM {SCHEMA_VERSION_TABLE}"))
            return {str(row.domain): int(row.version) for row in rows}

    async def record_schema_version(self, domain: str, version: int) -> None:
        async with self.async_engine.begin() as conn:
            await conn.execute(
                text(
                    f"""
                    INSERT INTO {SCHEMA_VERSION_TABLE} (domain, version, applied_at)
                    VALUES (:domain, :version, CURRENT_TIMESTAMP)
                    ON CONFLICT (domain) DO UPDATE SET version = EXCLUDED.version, applied_at = EXCLUDED.applied_at
                    """
                ),
                {"domain": domain, "version": version},
            )

    async def require_current_schema(self) -> None:
        versions = await self.get_schema_versions()
        if versions.get("business") != BUSINESS_SCHEMA_VERSION:
            raise RuntimeError(
                f"Database schema is missing or stale (business={versions.get('business', 'missing')}, "
                f"required {BUSINESS_SCHEMA_VERSION}). Run the storage-migrator first."
            )

    async def create_business_tables(self) -> None:
        async with self.async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            # create_all only creates missing TABLES, not missing columns on
            # tables that already exist from a prior schema version — this is
            # the one incremental step needed to add run_id (schema v3).
            await conn.execute(text("ALTER TABLE messages ADD COLUMN IF NOT EXISTS run_id VARCHAR"))
            # Same incremental-column need as run_id above, this time for
            # schema v5's subagent/worker-leasing columns on agent_runs.
            await conn.execute(text("ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS parent_run_id VARCHAR"))
            await conn.execute(text("ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS worker_id VARCHAR"))
            await conn.execute(text("ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMP"))
            await conn.execute(text("ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMP"))
            # create_all also never adds indexes to a table that already
            # existed before the index was added to the model — same class
            # of gap as the columns above, this time for schema v5's
            # parent_run_id (column-level index=True) and the composite
            # status/lease_expires_at index.
            await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_agent_runs_parent_run_id ON agent_runs (parent_run_id)"))
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_agent_runs_status_lease_expires "
                    "ON agent_runs (status, lease_expires_at)"
                )
            )
        logger.info("Business tables created/checked")

    def _ensure_langgraph_pool(self) -> AsyncConnectionPool:
        if self.langgraph_pool is None:
            from psycopg_pool import AsyncConnectionPool

            langgraph_dsn = self.dsn.replace("+asyncpg", "").replace("+psycopg", "")
            self.langgraph_pool = AsyncConnectionPool(
                conninfo=langgraph_dsn,
                max_size=10,
                open=False,
                kwargs={"autocommit": True},
                check=AsyncConnectionPool.check_connection,
            )
        return self.langgraph_pool

    def get_langgraph_checkpointer(self) -> AsyncPostgresSaver:
        if self.langgraph_checkpointer is None:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

            pool = self._ensure_langgraph_pool()
            #psycopg-pool prachna but plain is enough for us
            self.langgraph_checkpointer = AsyncPostgresSaver(pool) # pyright: ignore[reportArgumentType]
        return self.langgraph_checkpointer

    async def setup_langgraph_checkpointer(self) -> AsyncPostgresSaver:
        checkpointer = self.get_langgraph_checkpointer()
        pool = self._ensure_langgraph_pool()
        if not self._langgraph_checkpointer_setup:
            if pool.closed:
                await pool.open()
            async with pool.connection() as connection:
                await connection.execute(
                    f"SELECT pg_advisory_lock({LANGGRAPH_CHECKPOINT_SETUP_LOCK_KEY})"  # pyright: ignore[reportCallIssue, reportArgumentType]
                )
                try:
                    await checkpointer.setup()
                finally:
                    try:
                        cursor = await connection.execute(
                            f"SELECT pg_advisory_unlock({LANGGRAPH_CHECKPOINT_SETUP_LOCK_KEY})"  # pyright: ignore[reportCallIssue, reportArgumentType]
                        )
                        row = await cursor.fetchone()
                        if not row or row[0] is not True:
                            raise RuntimeError("Failed to release LangGraph checkpoint advisory lock")
                    except BaseException:
                        await connection.close()
                        raise
            self._langgraph_checkpointer_setup = True
        return checkpointer


_manager: PostgresManager | None = None


def get_postgres_manager() -> PostgresManager:
    global _manager
    if _manager is None:
        from vazhi.config import settings

        _manager = PostgresManager(settings.postgres_dsn)
    return _manager
