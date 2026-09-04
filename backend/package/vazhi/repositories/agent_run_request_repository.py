from __future__ import annotations

from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from vazhi.storage.postgres.models import AgentRunRequest, utc_now_naive


class AgentRunRequestRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _queued_for_thread_query(self, *, uid: str, agent_slug: str, conversation_thread_id: str):
        return (
            select(AgentRunRequest)
            .where(
                AgentRunRequest.uid == str(uid),
                AgentRunRequest.agent_slug == agent_slug,
                AgentRunRequest.conversation_thread_id == conversation_thread_id,
                AgentRunRequest.status == "queued",
            )
            .order_by(
                (AgentRunRequest.queue_policy != "steer").asc(), #FIFO
                AgentRunRequest.created_at.asc(),
                AgentRunRequest.id.asc(),
            )
        )

    async def get_by_request_id(self, request_id: str) -> AgentRunRequest | None:
        result = await self.db.execute(select(AgentRunRequest).where(AgentRunRequest.request_id == request_id))
        return result.scalar_one_or_none()

    async def lock_by_request_id(self, request_id: str) -> AgentRunRequest | None:
        result = await self.db.execute(
            select(AgentRunRequest).where(AgentRunRequest.request_id == request_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        request_id: str,
        uid: str,
        agent_slug: str,
        conversation_thread_id: str,
        queue_policy: str,
        input_message_id: int,
        status: str,
    ) -> AgentRunRequest:
        request = AgentRunRequest(
            request_id=request_id,
            uid=str(uid),
            agent_slug=agent_slug,
            conversation_thread_id=conversation_thread_id,
            queue_policy=queue_policy,
            input_message_id=input_message_id,
            status=status,
        )
        self.db.add(request)
        await self.db.flush()
        return request

    async def get_queue_head(self, *, uid: str, agent_slug: str, conversation_thread_id: str) -> AgentRunRequest | None:
        result = await self.db.execute(
            self._queued_for_thread_query(uid=uid, agent_slug=agent_slug, conversation_thread_id=conversation_thread_id)
            .limit(1)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def list_queued(self, *, uid: str, agent_slug: str, conversation_thread_id: str) -> list[AgentRunRequest]:
        result = await self.db.execute(
            self._queued_for_thread_query(uid=uid, agent_slug=agent_slug, conversation_thread_id=conversation_thread_id)
        )
        return list(result.scalars().all())

    async def get_pending_steer(
        self, *, uid: str, agent_slug: str, conversation_thread_id: str
    ) -> AgentRunRequest | None:
        result = await self.db.execute(
            select(AgentRunRequest).where(
                AgentRunRequest.uid == str(uid),
                AgentRunRequest.agent_slug == agent_slug,
                AgentRunRequest.conversation_thread_id == conversation_thread_id,
                AgentRunRequest.queue_policy == "steer",
                AgentRunRequest.status == "queued",
            )
        )
        return result.scalar_one_or_none()

    async def get_queue_position(self, request_id: str) -> int:
        request = await self.get_by_request_id(request_id)
        if request is None or request.status != "queued":
            return 0
        if request.queue_policy == "steer":
            return 1
        result = await self.db.execute(
            select(func.count())
            .select_from(AgentRunRequest)
            .where(
                AgentRunRequest.uid == request.uid,
                AgentRunRequest.agent_slug == request.agent_slug,
                AgentRunRequest.conversation_thread_id == request.conversation_thread_id,
                AgentRunRequest.status == "queued",
                tuple_(AgentRunRequest.created_at, AgentRunRequest.id) <= (request.created_at, request.id),
            )
        )
        return int(result.scalar_one())

    async def mark_dispatched(self, request_id: str, *, run_id: str) -> AgentRunRequest | None:
        request = await self.lock_by_request_id(request_id)
        if request is None or request.status != "queued":
            return None
        now = utc_now_naive()
        request.status = "dispatched"
        request.dispatched_run_id = run_id
        request.dispatched_at = now
        request.updated_at = now
        await self.db.flush()
        return request

    async def mark_cancelled(self, request_id: str) -> AgentRunRequest | None:
        request = await self.lock_by_request_id(request_id)
        if request is None or request.status != "queued":
            return None
        request.status = "cancelled"
        request.updated_at = utc_now_naive()
        await self.db.flush()
        return request
