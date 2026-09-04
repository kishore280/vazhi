from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vazhi.storage.postgres.models import Conversation, Message


class ConversationRepository:
    def __init__(self, db:AsyncSession):
        self.db = db

    async def lock_by_thread_id(self, thread_id: str) -> Conversation | None:
        result = await self.db.execute(
            select(Conversation).where(Conversation.thread_id == thread_id).with_for_update() #idhu use pannuna otehrs cant touch hence lock
        )
        return result.scalar_one_or_none()

    async def get_by_thread_id(self, thread_id:str) -> Conversation | None:
        result = await self.db.execute(
            select(Conversation).where(Conversation.thread_id == thread_id)
        )
        return result.scalar_one_or_none()

    async def get_or_create(
        self, *, thread_id: str, uid: str, agent_slug: str, title: str | None = None #why therlaa
    ) -> Conversation:
        existing = await self.lock_by_thread_id(thread_id)
        if existing:
            return existing
        conversation = Conversation(thread_id=thread_id, uid=str(uid), agent_slug=agent_slug, title=title)
        self.db.add(conversation)
        await self.db.flush() # id irukaadhu so cant commit nu claude said need to see whaattt
        return conversation

class MessageRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        *,
        conversation_id: int,
        role: str,
        content: str,
        request_id: str | None = None,
        extra_metadata: dict | None = None,
    ) -> Message:
        message = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            request_id=request_id,
            extra_metadata=extra_metadata,
        )
        self.db.add(message)
        await self.db.flush() # eadho irkuu
        return message

    async def list_by_conversation(self, conversation_id: int) -> list[Message]:
        result = await self.db.execute(
            select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at.asc())
        )
        return list(result.scalars().all())

    async def get(self, message_id: int) -> Message | None:
        return await self.db.get(Message, message_id)
        
