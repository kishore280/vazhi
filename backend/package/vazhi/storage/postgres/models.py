from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def utc_now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None) #timezone vendammm


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None #therlaa


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    thread_id: Mapped[str] = mapped_column(unique=True, index=True)
    uid: Mapped[str] = mapped_column(index=True)
    agent_slug: Mapped[str] = mapped_column(index=True)
    title: Mapped[str | None] = mapped_column(default=None)
    status: Mapped[str] = mapped_column(default="active")
    created_at: Mapped[datetime] = mapped_column(default=utc_now_naive)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now_naive, onupdate=utc_now_naive)

    messages: Mapped[list[Message]] = relationship(back_populates="conversation", cascade="all, delete-orphan")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "thread_id": self.thread_id,
            "uid": self.uid,
            "agent_slug": self.agent_slug,
            "title": self.title,
            "status": self.status,
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
        }


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    role: Mapped[str] = mapped_column()
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utc_now_naive)
    request_id: Mapped[str | None] = mapped_column(default=None, index=True)
    extra_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "role": self.role,
            "content": self.content,
            "created_at": _iso(self.created_at),
            "request_id": self.request_id,
            "metadata": self.extra_metadata or {},
        }
