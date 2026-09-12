from langchain_core.tools import tool

from vazhi.knowledge.milvus_store import search as kb_search


@tool
def query_kb(query_text: str) -> str:
    """Search the knowledge base for information relevant to the query."""
    results = kb_search(query_text)
    if not results:
        return "No relevant documents found."
    return "\n\n".join(f"[score={r['score']:.4f}] {r['content']}" for r in results)
