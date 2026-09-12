from typing import Any

from vazhi.knowledge.chunking.ragflow_like.parsers import general


def chunk_markdown(markdown_content: str, parser_config: dict[str, Any] | None = None) -> list[str]:
    return general.chunk_markdown(markdown_content, parser_config)
