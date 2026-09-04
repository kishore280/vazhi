from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vazhi.storage.postgres.models import AGENT_RUN_TERMINAL_STATUSES, AgentRun


class AgentRunRepository:
    def __init__(self, db: AsyncSession):
        self.db = db
    async def get_run(self, run_id: str) -> AgentRun | None:
        return await self.db.get(AgentRun, run_id)
    #oru convo ku edhachu run aagudha
    async def get_active_run_by_thread_for_user(
        self,
        *,
        agent_slug: str,
        conversation_thread_id: str,
        uid: str,
    ) -> AgentRun | None:
        result = await self.db.execute(
            select(AgentRun)
            .where(
                AgentRun.agent_slug == agent_slug,
                AgentRun.uid == str(uid),
                AgentRun.conversation_thread_id == conversation_thread_id,
                AgentRun.status.notin_(AGENT_RUN_TERMINAL_STATUSES),
            )
            .order_by(AgentRun.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    #queue la irukradha edukum ig
    async def create_run(
        self,
        *,
        run_id: str,
        conversation_thread_id: str,
        agent_slug: str,
        uid: str,
        request_id: str,
        conversation_id: int | None,
        input_message_id: int | None = None,
    ) -> AgentRun:
        run = AgentRun(
            id=run_id,
            conversation_thread_id=conversation_thread_id,
            agent_slug=agent_slug,
            uid=str(uid),
            status="pending",
            request_id=request_id,
            conversation_id=conversation_id,
            input_message_id=input_message_id,
            token_usage={},
        )
        self.db.add(run)
        await self.db.flush()
        return run