from __future__ import annotations

from arq import create_pool

from vazhi.storage.redis import get_arq_redis_settings


async def enqueue_agent_run(run_id: str) -> None:
    pool = await create_pool(get_arq_redis_settings())
    try:
        await pool.enqueue_job("execute_agent_run", run_id)
    finally:
        await pool.aclose()
