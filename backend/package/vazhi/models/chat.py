from __future__ import annotations

from langchain_openai import ChatOpenAI
from pydantic import SecretStr


class _ToolCallChunkFixChatOpenAI(ChatOpenAI):
    async def _astream(self, *args, **kwargs):
        async for chunk in super()._astream(*args, **kwargs):
            _normalize_tool_call_chunks(chunk.message)
            yield chunk

    def _stream(self, *args, **kwargs):
        for chunk in super()._stream(*args, **kwargs):
            _normalize_tool_call_chunks(chunk.message)
            yield chunk


def _normalize_tool_call_chunks(message) -> None:
    for chunk in message.tool_call_chunks:
        if chunk.get("name") == "":
            chunk["name"] = None
        if chunk.get("id") == "":
            chunk["id"] = None


def get_chat_model(temperature: float = 0.0):
    from vazhi.config import settings

    return _ToolCallChunkFixChatOpenAI(
        api_key=SecretStr(settings.groq_api_key),
        base_url="https://api.groq.com/openai/v1",
        model=settings.groq_model,
        temperature=temperature,
        stream_usage=True,
    )
