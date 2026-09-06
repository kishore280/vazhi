from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vazhi.storage.postgres.models import (
    AGENT_RUN_TERMINAL_STATUSES,
    AgentRun,
    AgentRunAttempt,
    utc_now_naive,
)


class AgentRunRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_run(self, run_id: str) -> AgentRun | None:
        return await self.db.get(AgentRun, run_id)

    async def lock_run_for_user(self, run_id: str, uid: str) -> AgentRun | None:
        result = await self.db.execute(
            select(AgentRun).where(AgentRun.id == run_id, AgentRun.uid == str(uid)).with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_subagent_run_for_creator(self, *, run_id: str, uid: str, created_by_run_id: str) -> AgentRun | None:
        result = await self.db.execute(
            select(AgentRun).where(
                AgentRun.id == run_id,
                AgentRun.uid == str(uid),
                AgentRun.parent_run_id == created_by_run_id,
            )
        )
        return result.scalar_one_or_none()

    #oru convo ku edhachu run aagudha
    async def get_active_run_by_thread_for_user(
        self,
        *,
        agent_slug: str,
        conversation_thread_id: str,
        uid: str,
    ) -> AgentRun | None:
        result = await self.db.execute(
            select(AgentRun)
            .where(
                AgentRun.agent_slug == agent_slug,
                AgentRun.uid == str(uid),
                AgentRun.conversation_thread_id == conversation_thread_id,
                AgentRun.status.notin_(AGENT_RUN_TERMINAL_STATUSES),
            )
            .order_by(AgentRun.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    #queue la irukradha edukum ig
    async def create_run(
        self,
        *,
        run_id: str,
        conversation_thread_id: str,
        agent_slug: str,
        uid: str,
        request_id: str,
        conversation_id: int | None,
        input_message_id: int | None = None,
        parent_run_id: str | None = None,
    ) -> AgentRun:
        run = AgentRun(
            id=run_id,
            conversation_thread_id=conversation_thread_id,
            agent_slug=agent_slug,
            uid=str(uid),
            status="pending",
            request_id=request_id,
            conversation_id=conversation_id,
            parent_run_id=parent_run_id,
            input_message_id=input_message_id,
            token_usage={},
        )
        self.db.add(run)
        await self.db.flush()
        return run

    async def mark_running(self, run_id: str, *, worker_id: str, lease_expires_at: datetime) -> bool:
        run = await self.db.get(AgentRun, run_id, with_for_update=True)
        if run is None or run.status not in {"pending", "cancel_requested"}:
            return False
        run.status = "running"
        run.worker_id = worker_id
        run.started_at = run.started_at or utc_now_naive()
        run.heartbeat_at = utc_now_naive()
        run.lease_expires_at = lease_expires_at
        await self.db.flush()
        return True

    async def request_cancel(self, run_id: str) -> bool:
        run = await self.db.get(AgentRun, run_id, with_for_update=True)
        if run is None or run.status not in {"pending", "running"}:
            return False
        run.status = "cancel_requested"
        await self.db.flush()
        return True

    async def renew_lease(self, run_id: str, *, worker_id: str, lease_expires_at: datetime) -> bool:
        run = await self.db.get(AgentRun, run_id, with_for_update=True)
        if run is None or run.worker_id != worker_id or run.status not in {"running", "cancel_requested"}:
            return False
        run.heartbeat_at = utc_now_naive()
        run.lease_expires_at = lease_expires_at
        await self.db.flush()
        return True

    async def mark_terminal(
        self,
        run_id: str,
        *,
        status: str,
        worker_id: str | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
        output_message_id: int | None = None,
        token_usage: dict | None = None,
    ) -> bool:
        run = await self.db.get(AgentRun, run_id, with_for_update=True)
        if run is None:
            return False
        if worker_id is not None and run.worker_id != worker_id:
            return False  # a stale/duplicate attempt cannot finalize a run it no longer owns
        run.status = status
        run.finished_at = utc_now_naive()
        run.error_type = error_type
        run.error_message = error_message
        if output_message_id is not None:
            run.output_message_id = output_message_id
        if token_usage is not None:
            run.token_usage = token_usage
        await self.db.flush()
        return True

    async def release_lease_for_retry(self, run_id: str, *, worker_id: str) -> bool:
        run = await self.db.get(AgentRun, run_id, with_for_update=True)
        now = utc_now_naive()
        if (
            run is None
            or run.status != "running"
            or run.worker_id != worker_id
            or run.lease_expires_at is None
            or run.lease_expires_at <= now
        ):
            return False
        run.status = "pending"
        run.worker_id = None
        run.heartbeat_at = None
        run.lease_expires_at = None
        await self.db.flush()
        return True

    async def find_expired_leases(self) -> list[AgentRun]:
        result = await self.db.execute(
            select(AgentRun).where(
                AgentRun.status.in_(("running", "cancel_requested")), AgentRun.lease_expires_at < utc_now_naive()
            )
        )
        return list(result.scalars().all())

    async def get_children(self, parent_run_id: str) -> list[AgentRun]:
        result = await self.db.execute(select(AgentRun).where(AgentRun.parent_run_id == parent_run_id))
        return list(result.scalars().all())

    async def update_last_event_id(self, run_id: str, event_id: str) -> None:
        run = await self.db.get(AgentRun, run_id)
        if run is not None:
            run.last_event_id = event_id
            await self.db.flush()


class AgentRunAttemptRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def open_attempt(self, run_id: str, *, worker_id: str, lease_expires_at: datetime) -> AgentRunAttempt:
        result = await self.db.execute(
            select(AgentRunAttempt)
            .where(AgentRunAttempt.run_id == run_id)
            .order_by(AgentRunAttempt.attempt_no.desc())
            .limit(1)
        )
        last = result.scalar_one_or_none()
        attempt = AgentRunAttempt(
            run_id=run_id,
            attempt_no=(last.attempt_no + 1) if last else 1,
            worker_id=worker_id,
            started_at=utc_now_naive(),
            heartbeat_at=utc_now_naive(),
            lease_expires_at=lease_expires_at,
        )
        self.db.add(attempt)
        await self.db.flush()
        return attempt

    async def renew(self, run_id: str, *, worker_id: str, lease_expires_at: datetime) -> None:
        result = await self.db.execute(
            select(AgentRunAttempt).where(
                AgentRunAttempt.run_id == run_id,
                AgentRunAttempt.worker_id == worker_id,
                AgentRunAttempt.finished_at.is_(None),
            )
        )
        attempt = result.scalar_one_or_none()
        if attempt is not None:
            attempt.heartbeat_at = utc_now_naive()
            attempt.lease_expires_at = lease_expires_at
            await self.db.flush()

    async def close(self, run_id: str, *, worker_id: str, outcome: str, error_message: str | None = None) -> None:
        result = await self.db.execute(
            select(AgentRunAttempt).where(
                AgentRunAttempt.run_id == run_id,
                AgentRunAttempt.worker_id == worker_id,
                AgentRunAttempt.finished_at.is_(None),
            )
        )
        attempt = result.scalar_one_or_none()
        if attempt is not None:
            attempt.finished_at = utc_now_naive()
            attempt.outcome = outcome
            attempt.error_message = error_message
            await self.db.flush()

    async def close_expired(self, run_id: str) -> None:
        result = await self.db.execute(
            select(AgentRunAttempt).where(AgentRunAttempt.run_id == run_id, AgentRunAttempt.finished_at.is_(None))
        )
        for attempt in result.scalars().all():
            attempt.finished_at = utc_now_naive()
            attempt.outcome = "lease_expired"
        await self.db.flush()
