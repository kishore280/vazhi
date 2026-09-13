import asyncio

from langchain_core.tools import tool

from vazhi.knowledge.graphs.ppr import query_graph as ppr_query_graph
from vazhi.storage.neo4j.manager import get_shared_neo4j_connection, neo4j_read


@tool
async def query_graph(kb_id: str, query_text: str) -> str:
    """Search a knowledge base's entity graph for information relevant to the query."""
    results = await ppr_query_graph(kb_id, query_text)
    if not results:
        return "No relevant graph context found."

    conn = get_shared_neo4j_connection()
    chunk_ids = [r["chunk_id"] for r in results]
    rows = await asyncio.to_thread(
        neo4j_read,
        conn.driver,
        "MATCH (c:Chunk {kb_id: $kb_id}) WHERE c.chunk_id IN $chunk_ids RETURN c.chunk_id AS chunk_id, c.content_preview AS content",
        kb_id=kb_id,
        chunk_ids=chunk_ids,
    )
    content_by_id = {row["chunk_id"]: row["content"] for row in rows}

    return "\n\n".join(
        f"[score={r['score']:.4f}] {content_by_id.get(r['chunk_id'], '')}" for r in results
    )
