import sys

sys.path.insert(0, "package")

from typing import ClassVar

from arq import cron

from vazhi.config import settings
from vazhi.services.run_worker import execute_agent_run, reconcile_expired_run_leases
from vazhi.storage.redis import get_arq_redis_settings, get_async_redis

WORKER_HEALTH_KEY = "vazhi:worker:health"
WORKER_HEALTH_TTL_SECONDS = 30


async def _reconcile_cron(ctx: dict) -> None:
    reconciled = await reconcile_expired_run_leases()
    if reconciled:
        import logging

        logging.getLogger(__name__).warning(f"Reconciled {len(reconciled)} expired-lease runs: {reconciled}")


async def _health_heartbeat_cron(ctx: dict) -> None:
    redis = get_async_redis()
    await redis.set(WORKER_HEALTH_KEY, "1", ex=WORKER_HEALTH_TTL_SECONDS)


class WorkerSettings:
    functions: ClassVar[list] = [execute_agent_run]
    cron_jobs: ClassVar[list] = [
        cron(_reconcile_cron, second={0, 15, 30, 45}),
        cron(_health_heartbeat_cron, second={0, 10, 20, 30, 40, 50}),
    ]
    redis_settings = get_arq_redis_settings()
    max_tries = settings.run_max_retries
