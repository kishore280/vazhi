from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, Text, UniqueConstraint
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
    run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.id"), default=None, index=True)
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
            "run_id": self.run_id,
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
    parent_run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.id"), default=None, index=True)
    input_message_id: Mapped[int | None] = mapped_column(default=None)
    output_message_id: Mapped[int | None] = mapped_column(default=None)
    last_event_id: Mapped[str | None] = mapped_column(default=None)
    token_usage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error_type: Mapped[str | None] = mapped_column(default=None)
    error_message: Mapped[str | None] = mapped_column(Text, default=None)
    worker_id: Mapped[str | None] = mapped_column(default=None)
    heartbeat_at: Mapped[datetime | None] = mapped_column(default=None)
    lease_expires_at: Mapped[datetime | None] = mapped_column(default=None)
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
            "parent_run_id": self.parent_run_id,
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
Index("ix_agent_runs_status_lease_expires", AgentRun.status, AgentRun.lease_expires_at)


class AgentRunAttempt(Base):
    """Immutable fact record: one row per lease a worker takes on a run."""

    __tablename__ = "agent_run_attempts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"))
    attempt_no: Mapped[int] = mapped_column()
    worker_id: Mapped[str] = mapped_column()
    started_at: Mapped[datetime] = mapped_column()
    heartbeat_at: Mapped[datetime | None] = mapped_column(default=None)
    lease_expires_at: Mapped[datetime | None] = mapped_column(default=None)
    finished_at: Mapped[datetime | None] = mapped_column(default=None)
    outcome: Mapped[str | None] = mapped_column(default=None)
    error_message: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(default=utc_now_naive)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now_naive, onupdate=utc_now_naive)

    __table_args__ = (
        UniqueConstraint("run_id", "attempt_no", name="uq_agent_run_attempts_run_attempt_no"),
        Index("ix_agent_run_attempts_open", "run_id", "finished_at"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "run_id": self.run_id,
            "attempt_no": self.attempt_no,
            "worker_id": self.worker_id,
            "started_at": _iso(self.started_at),
            "heartbeat_at": _iso(self.heartbeat_at),
            "lease_expires_at": _iso(self.lease_expires_at),
            "finished_at": _iso(self.finished_at),
            "outcome": self.outcome,
            "error_message": self.error_message,
        }


AGENT_RUN_REQUEST_STATUS_QUEUED = "queued"
AGENT_RUN_REQUEST_STATUS_DISPATCHED = "dispatched"
AGENT_RUN_REQUEST_STATUS_CANCELLED = "cancelled"
AGENT_RUN_REQUEST_STATUS_REJECTED = "rejected"


class AgentRunRequest(Base):
    __tablename__ = "agent_run_requests"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(unique=True, index=True)
    uid: Mapped[str] = mapped_column()
    agent_slug: Mapped[str] = mapped_column()
    conversation_thread_id: Mapped[str] = mapped_column()
    queue_policy: Mapped[str] = mapped_column(default="enqueue")
    status: Mapped[str] = mapped_column(default=AGENT_RUN_REQUEST_STATUS_QUEUED)
    input_message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"))
    dispatched_run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.id"), default=None)
    error_message: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(default=utc_now_naive)
    dispatched_at: Mapped[datetime | None] = mapped_column(default=None)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now_naive, onupdate=utc_now_naive)

    input_message: Mapped[Message] = relationship(foreign_keys=[input_message_id])
    dispatched_run: Mapped[AgentRun | None] = relationship(foreign_keys=[dispatched_run_id])

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "uid": self.uid,
            "agent_slug": self.agent_slug,
            "thread_id": self.conversation_thread_id,
            "queue_policy": self.queue_policy,
            "status": self.status,
            "input_message_id": self.input_message_id,
            "dispatched_run_id": self.dispatched_run_id,
            "error_message": self.error_message,
            "created_at": _iso(self.created_at),
            "dispatched_at": _iso(self.dispatched_at),
        }


Index(
    "ix_agent_run_requests_queue",
    AgentRunRequest.uid,
    AgentRunRequest.agent_slug,
    AgentRunRequest.conversation_thread_id,
    AgentRunRequest.status,
    AgentRunRequest.created_at,
    AgentRunRequest.id,
)


class Agent(Base):
    __tablename__ = "agents"

    slug: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column()
    description: Mapped[str | None] = mapped_column(Text, default=None)
    kind: Mapped[str] = mapped_column(default="subagent")  # main/subagent
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utc_now_naive)

    def to_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "name": self.name,
            "description": self.description,
            "kind": self.kind,
            "config_json": self.config_json or {},
            "created_at": _iso(self.created_at),
        }


class SubagentThread(Base):
    __tablename__ = "subagent_threads"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    uid: Mapped[str] = mapped_column(index=True)
    parent_run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    parent_thread_id: Mapped[str] = mapped_column()
    child_thread_id: Mapped[str] = mapped_column(unique=True, index=True)
    subagent_slug: Mapped[str] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(default=utc_now_naive)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "uid": self.uid,
            "parent_run_id": self.parent_run_id,
            "parent_thread_id": self.parent_thread_id,
            "child_thread_id": self.child_thread_id,
            "subagent_slug": self.subagent_slug,
            "created_at": _iso(self.created_at),
        }
