import json_repair

from vazhi.models.chat import get_chat_model

TRIPLE_EXTRACTION_PROMPT = """Extract entities and relationships from the text below. Return strict JSON only, no explanation.

JSON format:
{
  "relations": [
    {
      "source": {"text": "entity text", "label": "entity type"},
      "target": {"text": "entity text", "label": "entity type"},
      "text": "relation description",
      "label": "relation type"
    }
  ]
}

Text:
{text}
"""


async def extract_triples(text: str) -> list[dict]:
    model = get_chat_model()
    prompt = TRIPLE_EXTRACTION_PROMPT.replace("{text}", text)
    response = await model.ainvoke(prompt)
    content = response.content if isinstance(response.content, str) else str(response.content)
    parsed = json_repair.loads(content)
    if not isinstance(parsed, dict):
        return []
    relations = parsed.get("relations")
    return relations if isinstance(relations, list) else []
