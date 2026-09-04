import logging
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from vazhi.storage.postgres.models import Base

logger = logging.getLogger(__name__)

SCHEMA_VERSION_TABLE = "vazhi_schema_migrations"
BUSINESS_SCHEMA_VERSION = 4


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
        logger.info("Business tables created/checked")


_manager: PostgresManager | None = None


def get_postgres_manager() -> PostgresManager:
    global _manager
    if _manager is None:
        from vazhi.config import settings

        _manager = PostgresManager(settings.postgres_dsn)
    return _manager
