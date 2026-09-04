from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from vazhi.services import agent_queue_service
from vazhi.storage.postgres.manager import get_postgres_manager

from server.auth import require_uid

router = APIRouter(prefix="/api/agent", tags=["agent"])

DEFAULT_AGENT_SLUG = "vazhi_demo"

class CreateRunRequest(BaseModel):
    thread_id:str
    content : str
    queue_policy: str = "enqueue"  #specify panlana queue deefault ah irkatummm

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
    return {
        "request_id": request_id,
        "status": intake.status,
        "run_id": intake.run_id,
        "queue_position": intake.queue_position,
    }


