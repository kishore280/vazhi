from langchain_core.tools import tool

from vazhi.knowledge.milvus_store import search as kb_search
from vazhi.models.rerank import get_reranker


@tool
async def query_kb(query_text: str) -> str:
    """Search the knowledge base for information relevant to the query."""
    results = await kb_search(query_text)
    if not results:
        return "No relevant documents found."

    reranker = get_reranker()
    scores = await reranker.acompute_score([query_text, [r["content"] for r in results]])
    for result, score in zip(results, scores, strict=True):
        result["rerank_score"] = score
    results.sort(key=lambda r: r["rerank_score"], reverse=True)

    return "\n\n".join(f"[score={r['rerank_score']:.4f}] {r['content']}" for r in results)
