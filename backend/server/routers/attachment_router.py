from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from vazhi.repositories.conversation_repository import (
    AttachmentRepository,
    MessageRepository,
)
from vazhi.storage.minio import upload_attachment
from vazhi.storage.postgres.manager import get_postgres_manager

from server.auth import require_uid

router = APIRouter(prefix="/api/agent", tags=["attachments"])

MAX_ATTACHMENT_SIZE = 20 * 1024 * 1024


@router.post("/messages/{message_id}/attachments")
async def upload_message_attachment(message_id: int, file: UploadFile, uid: str = Depends(require_uid)):
    manager = get_postgres_manager()
    async with manager.get_session() as db:
        message = await MessageRepository(db).get(message_id)
        if message is None:
            raise HTTPException(status_code=404, detail="Message not found")

        data = await file.read()
        if len(data) > MAX_ATTACHMENT_SIZE:
            raise HTTPException(status_code=413, detail=f"Attachment exceeds {MAX_ATTACHMENT_SIZE} bytes")

        object_key = f"{uid}/{message_id}/{uuid.uuid4().hex}_{file.filename}"
        upload_attachment(object_key, data, content_type=file.content_type)

        attachment = await AttachmentRepository(db).create(
            message_id=message_id,
            filename=file.filename or "unnamed",
            content_type=file.content_type,
            size_bytes=len(data),
            minio_object_key=object_key,
        )
        await db.commit()

    return attachment.to_dict()
