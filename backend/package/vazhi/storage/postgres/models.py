from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, Text
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


AGENT_RUN_TERMINAL_STATUSES = ("completed", "failed", "cancelled", "interrupted", "awaiting_approval")


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(primary_key=True)
    conversation_thread_id: Mapped[str] = mapped_column(index=True)
    agent_slug: Mapped[str] = mapped_column(index=True)
    uid: Mapped[str] = mapped_column(index=True)
    status: Mapped[str] = mapped_column(index=True, default="pending")
    request_id: Mapped[str] = mapped_column(unique=True, index=True)
    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id"), default=None, index=True)
    input_message_id: Mapped[int | None] = mapped_column(default=None)
    output_message_id: Mapped[int | None] = mapped_column(default=None)
    last_event_id: Mapped[str | None] = mapped_column(default=None)
    token_usage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error_type: Mapped[str | None] = mapped_column(default=None)
    error_message: Mapped[str | None] = mapped_column(Text, default=None)
    started_at: Mapped[datetime | None] = mapped_column(default=None)
    finished_at: Mapped[datetime | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=utc_now_naive)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now_naive, onupdate=utc_now_naive)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "conversation_thread_id": self.conversation_thread_id,
            "agent_slug": self.agent_slug,
            "uid": self.uid,
            "status": self.status,
            "request_id": self.request_id,
            "conversation_id": self.conversation_id,
            "input_message_id": self.input_message_id,
            "output_message_id": self.output_message_id,
            "last_event_id": self.last_event_id,
            "token_usage": self.token_usage or {},
            "error_type": self.error_type,
            "error_message": self.error_message,
            "started_at": _iso(self.started_at),
            "finished_at": _iso(self.finished_at),
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
        }


Index(
    "uq_agent_runs_one_active_per_thread",
    AgentRun.uid,
    AgentRun.agent_slug,
    AgentRun.conversation_thread_id,
    unique=True,
    postgresql_where=AgentRun.status.notin_(AGENT_RUN_TERMINAL_STATUSES),
)
