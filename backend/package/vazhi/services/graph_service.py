from vazhi.knowledge.graphs import query as graph_query
from vazhi.services.knowledge_service import _get_owned_knowledge_base


async def get_subgraph(*, uid: str, kb_id: str, max_nodes: int = 200) -> dict:
    await _get_owned_knowledge_base(uid=uid, kb_id=kb_id)
    return await graph_query.get_subgraph(kb_id, max_nodes=max_nodes)
