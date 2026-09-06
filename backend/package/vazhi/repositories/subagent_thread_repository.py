from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vazhi.storage.postgres.models import SubagentThread


class SubagentThreadRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_child_thread_for_user(self, child_thread_id: str, uid: str) -> SubagentThread | None:
        result = await self.db.execute(
            select(SubagentThread).where(
                SubagentThread.child_thread_id == child_thread_id, SubagentThread.uid == str(uid)
            )
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        uid: str,
        parent_run_id: str,
        parent_thread_id: str,
        child_thread_id: str,
        subagent_slug: str,
    ) -> SubagentThread:
        relation = SubagentThread(
            uid=str(uid),
            parent_run_id=parent_run_id,
            parent_thread_id=parent_thread_id,
            child_thread_id=child_thread_id,
            subagent_slug=subagent_slug,
        )
        self.db.add(relation)
        await self.db.flush()
        return relation
