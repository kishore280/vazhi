from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vazhi.storage.postgres.models import AgentRun, Conversation, Message

_ROLE_TO_TYPE = {"user": "human", "assistant": "ai", "system": "system"}


async def get_thread_history_view(*, thread_id: str, current_uid: str, db: AsyncSession) -> dict:
    result = await db.execute(select(Conversation).where(Conversation.thread_id == thread_id))
    conversation = result.scalar_one_or_none()
    if conversation is None or conversation.uid != str(current_uid):
        raise HTTPException(status_code=404, detail="Conversation thread not found")

    messages_result = await db.execute(
        select(Message).where(Message.conversation_id == conversation.id).order_by(Message.created_at.asc())
    )
    messages = list(messages_result.scalars().all())

    run_ids = {m.run_id for m in messages if m.run_id is not None}
    run_timing: dict[str, AgentRun] = {}
    if run_ids:
        runs_result = await db.execute(select(AgentRun).where(AgentRun.id.in_(run_ids)))
        run_timing = {run.id: run for run in runs_result.scalars().all()}

    history = []
    for message in messages:
        item = message.to_dict()
        item["type"] = _ROLE_TO_TYPE.get(message.role, message.role)
        run = run_timing.get(message.run_id) if message.run_id else None
        item["run_started_at"] = run.to_dict()["started_at"] if run else None
        item["run_finished_at"] = run.to_dict()["finished_at"] if run else None
        history.append(item)

    return {"history": history}
