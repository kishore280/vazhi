from fastapi import APIRouter, Response

from vazhi.storage.postgres.manager import get_postgres_manager
from vazhi.storage.redis import get_async_redis

router = APIRouter(prefix="/api/system", tags=["system"])

WORKER_HEALTH_KEY = "vazhi:worker:health"


@router.get("/health")
async def health():
    return {"status": "alive"}


@router.get("/ready")
async def ready(response: Response):
    checks = {}

    try:
        manager = get_postgres_manager()
        await manager.require_current_schema()
        checks["postgres"] = "ok"
    except Exception as e:  # noqa: BLE001
        checks["postgres"] = f"error: {e}"

    try:
        redis = get_async_redis()
        await redis.ping()
        checks["redis"] = "ok"
    except Exception as e:  # noqa: BLE001
        checks["redis"] = f"error: {e}"

    try:
        redis = get_async_redis()
        worker_alive = bool(await redis.get(WORKER_HEALTH_KEY))
        checks["worker"] = "ok" if worker_alive else "no recent worker heartbeat"
    except Exception as e:  # noqa: BLE001
        checks["worker"] = f"error: {e}"

    all_ok = all(v == "ok" for v in checks.values())
    if not all_ok:
        response.status_code = 503
    return {"status": "ready" if all_ok else "not_ready", "checks": checks}
