from __future__ import annotations

import logging

from vazhi.repositories.agent_run_repository import AgentRunRepository
from vazhi.storage.postgres.manager import get_postgres_manager

logger = logging.getLogger(__name__)

async def execute_agent_run(ctx: dict, run_id: str) -> None:  #arq ku venum ctx dict avlo dhan.. yenu kekaadha
    manager = get_postgres_manager()
    async with manager.get_session() as db:
        run_repo = AgentRunRepository(db)
        run = await run_repo.get_run(run_id)
        if run is None:
            logger.warning(f"execute_agent_run: run {run_id} not found")
            return
        run.status = "completed"
        await db.commit()
        logger.info(f"execute_agent_run: run {run_id} marked completed(no LLM call yet)")
