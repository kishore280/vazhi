from __future__ import annotations

import asyncio
import logging

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from vazhi.services.langfuse_service import submit_user_feedback_score
from vazhi.storage.postgres.models import Message, MessageFeedback

logger = logging.getLogger(__name__)

_VALID_RATINGS = {"like", "dislike"}


async def submit_message_feedback_view(
    *, message_id: int, rating: str, reason: str | None, db: AsyncSession, current_uid: str
) -> dict:
    if rating not in _VALID_RATINGS:
        raise HTTPException(status_code=422, detail=f"rating must be one of {sorted(_VALID_RATINGS)}")

    result = await db.execute(
        select(Message).options(selectinload(Message.conversation)).where(Message.id == message_id)
    )
    message = result.scalar_one_or_none()
    if message is None or message.conversation.uid != str(current_uid):
        raise HTTPException(status_code=404, detail="Message not found")

    existing_result = await db.execute(
        select(MessageFeedback).where(MessageFeedback.message_id == message_id, MessageFeedback.uid == str(current_uid))
    )
    if existing_result.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Feedback already submitted for this message")

    feedback = MessageFeedback(message_id=message_id, uid=str(current_uid), rating=rating, reason=reason)
    db.add(feedback)
    await db.flush()
    await db.commit()
    await db.refresh(feedback)

    trace_id = (message.extra_metadata or {}).get("langfuse_trace_id")
    if trace_id:
        try:
            await asyncio.to_thread(
                submit_user_feedback_score,
                trace_id=trace_id,
                feedback_id=feedback.id,
                message_id=message_id,
                conversation_id=message.conversation_id,
                uid=str(current_uid),
                rating=rating,
                reason=reason,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Langfuse feedback score submission failed, local feedback still saved: {exc}")

    return feedback.to_dict()


async def get_message_feedback_view(*, message_id: int, db: AsyncSession, current_uid: str) -> dict:
    result = await db.execute(
        select(MessageFeedback)
        .join(Message, Message.id == MessageFeedback.message_id)
        .where(MessageFeedback.message_id == message_id, MessageFeedback.uid == str(current_uid))
    )
    feedback = result.scalar_one_or_none()
    return {"has_feedback": feedback is not None, "feedback": feedback.to_dict() if feedback else None}
