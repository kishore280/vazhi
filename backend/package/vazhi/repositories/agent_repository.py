from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vazhi.storage.postgres.models import Agent


class AgentRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_slug(self, slug: str) -> Agent | None:
        return await self.db.get(Agent, slug)

    async def list_subagents(self) -> list[Agent]:
        result = await self.db.execute(select(Agent).where(Agent.kind == "subagent").order_by(Agent.slug))
        return list(result.scalars().all())
