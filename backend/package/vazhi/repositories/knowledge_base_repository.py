from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vazhi.storage.postgres.models import KnowledgeBase


class KnowledgeBaseRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, *, kb_id: str, name: str, created_by: str) -> KnowledgeBase:
        kb = KnowledgeBase(kb_id=kb_id, name=name, created_by=created_by)
        self.db.add(kb)
        await self.db.flush()
        return kb

    async def get_by_kb_id(self, kb_id: str) -> KnowledgeBase | None:
        result = await self.db.execute(select(KnowledgeBase).where(KnowledgeBase.kb_id == kb_id))
        return result.scalar_one_or_none()

    async def list_by_owner(self, uid: str) -> list[KnowledgeBase]:
        result = await self.db.execute(
            select(KnowledgeBase).where(KnowledgeBase.created_by == uid).order_by(KnowledgeBase.created_at.desc())
        )
        return list(result.scalars().all())
