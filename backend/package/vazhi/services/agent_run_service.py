from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from vazhi.repositories.agent_run_repository import AgentRunRepository
from vazhi.repositories.conversation_repository import MessageRepository
from vazhi.storage.postgres.manager import get_postgres_manager
from vazhi.storage.postgres.models import AGENT_RUN_TERMINAL_STATUSES
from vazhi.storage.redis import get_async_redis, run_cancel_key, run_event_stream_key

DEFAULT_AWAIT_TIMEOUT_SECONDS = 120
_POLL_BLOCK_MS = 5000


class AgentRunWaitTimeout(Exception):
    def __init__(self, result: dict[str, Any]):
        self.result = result
        super().__init__("timed out waiting for agent run to finish")


async def get_agent_run_result(run_id: str, *, current_uid: str) -> dict[str, Any] | None:
    manager = get_postgres_manager()
    async with manager.get_session() as db:
        run = await AgentRunRepository(db).get_run(run_id)
        if run is None or run.uid != current_uid:
            return None
        if run.status not in AGENT_RUN_TERMINAL_STATUSES:
            return None
        output = ""
        if run.output_message_id is not None:
            message = await MessageRepository(db).get(run.output_message_id)
            output = message.content if message else ""
        error = {"type": run.error_type, "message": run.error_message} if run.error_message else None
        return {"agent_run_id": run.id, "status": run.status, "output": output, "error": error}


async def get_agent_run_progress(run_id: str, *, limit: int = 3) -> list[str]:
    redis = get_async_redis()
    entries = await redis.xrevrange(run_event_stream_key(run_id), count=limit * 4)
    progress: list[str] = []
    for _message_id, fields in entries:
        payload = json.loads(fields.get("data", "{}"))
        event = payload.get("event")
        if event == "tool-call":
            progress.append(f"called {payload.get('tool')}")
        elif event == "error":
            progress.append(f"error: {payload.get('error_message')}")
        if len(progress) >= limit:
            break
    progress.reverse()
    return progress


async def await_agent_run_result(
    run_id: str, *, current_uid: str, timeout_seconds: int = DEFAULT_AWAIT_TIMEOUT_SECONDS
) -> dict[str, Any]:
    redis = get_async_redis()
    stream_key = run_event_stream_key(run_id)
    deadline = time.monotonic() + timeout_seconds
    last_id = "0-0"

    while time.monotonic() < deadline:
        remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
        block_ms = min(_POLL_BLOCK_MS, remaining_ms)
        entries = await redis.xread({stream_key: last_id}, block=block_ms, count=50)
        if not entries:
            continue
        for _stream_key, messages in entries:
            for message_id, fields in messages:
                last_id = message_id
                payload = json.loads(fields.get("data", "{}"))
                if payload.get("event") == "run-finished":
                    result = await get_agent_run_result(run_id, current_uid=current_uid)
                    if result is not None:
                        return result
                    await asyncio.sleep(0.1)
                    result = await get_agent_run_result(run_id, current_uid=current_uid)
                    if result is not None:
                        return result

    progress = await get_agent_run_progress(run_id)
    raise AgentRunWaitTimeout({"agent_run_id": run_id, "status": "running", "progress": progress})


async def request_cancel_agent_run(run_id: str, *, current_uid: str):
    manager = get_postgres_manager()
    async with manager.get_session() as db:
        repo = AgentRunRepository(db)
        run = await repo.get_run(run_id)
        if run is None or run.uid != current_uid:
            raise ValueError("Run does not exist")
        requested = await repo.request_cancel(run_id)
        await db.commit()
        if requested:
            redis = get_async_redis()
            await redis.set(run_cancel_key(run_id), "1", ex=3600)
        return await repo.get_run(run_id)
