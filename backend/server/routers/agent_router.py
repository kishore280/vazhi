from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from vazhi.services import agent_queue_service
from vazhi.storage.postgres.manager import get_postgres_manager
from vazhi.storage.redis import get_async_redis, run_event_stream_key

from server.auth import require_uid
from server.sse_utils import (
    SSE_HEARTBEAT_SECONDS,
    SSE_MAX_CONNECTION_MINUTES,
    SSE_POLL_INTERVAL_SECONDS,
    format_heartbeat,
    format_sse,
)

router = APIRouter(prefix="/api/agent", tags=["agent"])

DEFAULT_AGENT_SLUG = "vazhi_demo"

class CreateRunRequest(BaseModel):
    thread_id:str
    content : str
    queue_policy: str = "enqueue"  #specify panlana queue deefault ah irkatummm
    tool_approval_mode: str | None = None

@router.post("/runs")
async def create_run(request: CreateRunRequest, uid:str = Depends(require_uid)):
    request_id = uuid.uuid4().hex
    manager = get_postgres_manager()
    async with manager.get_session() as db:
        try:
            intake = await agent_queue_service.intake_request(
                db=db,
                request_id=request_id,
                uid=uid,
                agent_slug=DEFAULT_AGENT_SLUG,
                thread_id=request.thread_id,
                content=request.content,
                queue_policy=request.queue_policy,
            )
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        await db.commit()

    await agent_queue_service.finalize_intake(intake)
    return {
        "request_id": request_id,
        "status": intake.status,
        "run_id": intake.run_id,
        "queue_position": intake.queue_position,
    }


@router.get("/runs/{run_id}/events")
async def stream_run_events(
    run_id: str,
    after_seq: str = "0-0",
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    uid: str = Depends(require_uid),
):
    cursor = last_event_id or after_seq

    async def event_source():
        redis = get_async_redis()
        last_id = cursor
        elapsed = 0.0

        while elapsed < SSE_MAX_CONNECTION_MINUTES * 60:
            entries = await redis.xread(
                {run_event_stream_key(run_id): last_id}, block=int(SSE_POLL_INTERVAL_SECONDS * 1000), count=50
            )
            if not entries:
                elapsed += SSE_POLL_INTERVAL_SECONDS
                if elapsed % SSE_HEARTBEAT_SECONDS < SSE_POLL_INTERVAL_SECONDS:
                    yield format_heartbeat()
                continue

            for _stream_key, messages in entries:
                for message_id, fields in messages:
                    last_id = message_id
                    payload = json.loads(fields.get("data", "{}"))
                    event_type = payload.pop("event", "message")
                    yield format_sse(payload, event=event_type, event_id=message_id)
                    if event_type == "run-finished":
                        return
            elapsed = 0.0

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.post("/requests/{request_id}/cancel")
async def cancel_request(request_id: str, uid: str = Depends(require_uid)):
    cancelled = await agent_queue_service.cancel_queued_request(request_id=request_id, uid=uid)
    if not cancelled:
        raise HTTPException(status_code=404, detail="Request not found or not cancellable")
    return {"cancelled": True}


@router.get("/thread/{thread_id}/history")
async def get_thread_history(thread_id: str, uid: str = Depends(require_uid)):
    from vazhi.services.chat_history_service import get_thread_history_view

    manager = get_postgres_manager()
    async with manager.get_session() as db:
        return await get_thread_history_view(thread_id=thread_id, current_uid=uid, db=db)
