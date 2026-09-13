import json_repair

from vazhi.knowledge.milvus_store import get_sample_chunks
from vazhi.models.chat import get_chat_model

BENCHMARK_GENERATION_PROMPT = """Based on the following context, generate one question that can be accurately \
answered from it, plus the gold answer.

Context (id={chunk_id}):
{content}

Return ONLY a JSON object with keys "query" and "gold_answer".
"""


async def generate_benchmark_item(chunk_id: str, content: str) -> dict | None:
    model = get_chat_model()
    prompt = BENCHMARK_GENERATION_PROMPT.format(chunk_id=chunk_id, content=content)
    response = await model.ainvoke(prompt)
    text = response.content if isinstance(response.content, str) else str(response.content)
    text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    parsed = json_repair.loads(text)
    if not isinstance(parsed, dict) or not parsed.get("query") or not parsed.get("gold_answer"):
        return None
    return {"query": parsed["query"], "gold_answer": parsed["gold_answer"], "gold_chunk_ids": [chunk_id]}


async def generate_benchmark(kb_id: str, num_questions: int = 5) -> list[dict]:
    chunks = await get_sample_chunks(kb_id, limit=num_questions)
    items = []
    for chunk in chunks:
        item = await generate_benchmark_item(chunk["chunk_id"], chunk["content"])
        if item is not None:
            items.append(item)
    return items
