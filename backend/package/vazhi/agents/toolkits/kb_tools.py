from langchain_core.tools import tool
from langgraph.prebuilt.tool_node import ToolRuntime

from vazhi.models.rerank import get_reranker
from vazhi.services.knowledge_service import list_knowledge_bases, query_knowledge_base


@tool
async def list_kbs(runtime: ToolRuntime) -> str:
    """List the knowledge bases available to search. Call this first if you don't already know a kb_id."""
    uid = str(getattr(runtime.context, "uid", "") or "")
    kbs = await list_knowledge_bases(uid=uid)
    if not kbs:
        return "No knowledge bases available."
    return "\n".join(f"kb_id={kb.kb_id} name={kb.name!r}" for kb in kbs)


@tool
async def query_kb(kb_id: str, query_text: str, runtime: ToolRuntime) -> str:
    """Search a knowledge base for information relevant to the query."""
    uid = str(getattr(runtime.context, "uid", "") or "")
    results = await query_knowledge_base(uid=uid, kb_id=kb_id, query_text=query_text)
    if not results:
        return "No relevant documents found."

    reranker = get_reranker()
    scores = await reranker.acompute_score([query_text, [r["content"] for r in results]])
    for result, score in zip(results, scores, strict=True):
        result["rerank_score"] = score
    results.sort(key=lambda r: r["rerank_score"], reverse=True)

    return "\n\n".join(f"[score={r['rerank_score']:.4f}] {r['content']}" for r in results)
