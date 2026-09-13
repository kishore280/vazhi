from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vazhi.storage.postgres.models import KnowledgeDocument


class KnowledgeDocumentRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, *, kb_id: str, doc_id: str, filename: str) -> KnowledgeDocument:
        doc = KnowledgeDocument(kb_id=kb_id, doc_id=doc_id, filename=filename)
        self.db.add(doc)
        await self.db.flush()
        return doc

    async def list_by_kb(self, kb_id: str) -> list[KnowledgeDocument]:
        result = await self.db.execute(
            select(KnowledgeDocument)
            .where(KnowledgeDocument.kb_id == kb_id)
            .order_by(KnowledgeDocument.created_at.desc())
        )
        return list(result.scalars().all())
