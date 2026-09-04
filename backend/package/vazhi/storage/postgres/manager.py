from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


class PostgresManager:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.async_engine = create_async_engine(
            dsn,
            pool_pre_ping=True, #before using test pananum
            pool_recycle=1800, #close and replace pananum if more than 30mins connection
        )
        self.async_session = async_sessionmaker(
            bind=self.async_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
_manager: PostgresManager | None = None


@asynccontextmanager
async def get_session(self):
    async with self.async_session() as session:
        yield session


def get_postgres_manager() -> PostgresManager:
    global _manager
    if _manager is None:
        from vazhi.config import settings
        _manager = PostgresManager(settings.postgres_dsn)
    return _manager
