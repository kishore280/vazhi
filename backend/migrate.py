import asyncio
import logging
import sys

sys.path.insert(0, "package")

from vazhi.storage.postgres.manager import BUSINESS_SCHEMA_VERSION, get_postgres_manager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    manager = get_postgres_manager()
    async with manager.schema_migration_lock():
        await manager.create_schema_version_table()
        versions = await manager.get_schema_versions()
        if versions.get("business") == BUSINESS_SCHEMA_VERSION:
            logger.info(f"Business schema already at version {BUSINESS_SCHEMA_VERSION}, nothing to do")
            return

        await manager.create_business_tables()
        await manager.record_schema_version("business", BUSINESS_SCHEMA_VERSION)
        logger.info(f"Business schema migrated to version {BUSINESS_SCHEMA_VERSION}")


if __name__ == "__main__":
    asyncio.run(main())
