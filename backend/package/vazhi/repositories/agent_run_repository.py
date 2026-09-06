from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vazhi.storage.postgres.models import (
    AGENT_RUN_TERMINAL_STATUSES,
    AgentRun,
    utc_now_naive,
)


class AgentRunRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_run(self, run_id: str) -> AgentRun | None:
        return await self.db.get(AgentRun, run_id)

    async def lock_run_for_user(self, run_id: str, uid: str) -> AgentRun | None:
        result = await self.db.execute(
            select(AgentRun).where(AgentRun.id == run_id, AgentRun.uid == str(uid)).with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_subagent_run_for_creator(self, *, run_id: str, uid: str, created_by_run_id: str) -> AgentRun | None:
        result = await self.db.execute(
            select(AgentRun).where(
                AgentRun.id == run_id,
                AgentRun.uid == str(uid),
                AgentRun.parent_run_id == created_by_run_id,
            )
        )
        return result.scalar_one_or_none()

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
        parent_run_id: str | None = None,
    ) -> AgentRun:
        run = AgentRun(
            id=run_id,
            conversation_thread_id=conversation_thread_id,
            agent_slug=agent_slug,
            uid=str(uid),
            status="pending",
            request_id=request_id,
            conversation_id=conversation_id,
            parent_run_id=parent_run_id,
            input_message_id=input_message_id,
            token_usage={},
        )
        self.db.add(run)
        await self.db.flush()
        return run

    async def mark_running(self, run_id: str, *, worker_id: str, lease_expires_at: datetime) -> bool:
        run = await self.db.get(AgentRun, run_id, with_for_update=True)
        if run is None or run.status not in {"pending", "cancel_requested"}:
            return False
        run.status = "running"
        run.worker_id = worker_id
        run.started_at = run.started_at or utc_now_naive()
        run.heartbeat_at = utc_now_naive()
        run.lease_expires_at = lease_expires_at
        await self.db.flush()
        return True

    async def request_cancel(self, run_id: str) -> bool:
        run = await self.db.get(AgentRun, run_id, with_for_update=True)
        if run is None or run.status not in {"pending", "running"}:
            return False
        run.status = "cancel_requested"
        await self.db.flush()
        return True
