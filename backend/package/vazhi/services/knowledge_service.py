import uuid

from vazhi.knowledge import milvus_store
from vazhi.repositories.knowledge_base_repository import KnowledgeBaseRepository
from vazhi.storage.postgres.manager import get_postgres_manager
from vazhi.storage.postgres.models import KnowledgeBase


async def create_knowledge_base(*, uid: str, name: str) -> KnowledgeBase:
    manager = get_postgres_manager()
    async with manager.get_session() as db:
        kb = await KnowledgeBaseRepository(db).create(kb_id=uuid.uuid4().hex, name=name, created_by=uid)
        await db.commit()
        return kb


async def list_knowledge_bases(*, uid: str) -> list[KnowledgeBase]:
    manager = get_postgres_manager()
    async with manager.get_session() as db:
        return await KnowledgeBaseRepository(db).list_by_owner(uid)


async def _get_owned_knowledge_base(*, uid: str, kb_id: str) -> KnowledgeBase:
    manager = get_postgres_manager()
    async with manager.get_session() as db:
        kb = await KnowledgeBaseRepository(db).get_by_kb_id(kb_id)
    if kb is None or kb.created_by != uid:
        raise PermissionError(f"Knowledge base {kb_id} not found or not owned by {uid}")
    return kb


async def ingest_document(
    *,
    uid: str,
    kb_id: str,
    doc_id: str,
    content: str,
    filename: str = "document.md",
    preset_id: str = "general",
    parser_config: dict | None = None,
) -> None:
    await _get_owned_knowledge_base(uid=uid, kb_id=kb_id)
    await milvus_store.add_document(
        kb_id, doc_id, content, filename=filename, preset_id=preset_id, parser_config=parser_config
    )


async def query_knowledge_base(*, uid: str, kb_id: str, query_text: str, top_k: int = 3) -> list[dict]:
    await _get_owned_knowledge_base(uid=uid, kb_id=kb_id)
    return await milvus_store.search(kb_id, query_text, top_k=top_k)
