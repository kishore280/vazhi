from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from vazhi.repositories.agent_run_repository import AgentRunRepository
from vazhi.repositories.subagent_thread_repository import SubagentThreadRepository
from vazhi.services import agent_queue_service
from vazhi.storage.postgres.models import Agent, AgentRun, SubagentThread
from vazhi.utils.hash_utils import hash_id, subagent_child_thread_id


@dataclass(frozen=True)
class SubagentStartResult:
    run: AgentRun
    created: bool
    continuing: bool
    relation: SubagentThread


class SubagentRunBusy(Exception):
    def __init__(self, *, thread_id: str, active_run_id: str | None, active_run_status: str | None):
        self.thread_id = thread_id
        self.active_run_id = active_run_id
        self.active_run_status = active_run_status
        super().__init__(f"subagent thread {thread_id} is busy")

    def to_payload(self) -> dict:
        return {
            "status": "busy",
            "thread_id": self.thread_id,
            "active_run_id": self.active_run_id,
            "active_run_status": self.active_run_status,
            "message": "This subagent thread already has a run in progress.",
        }


def subagent_run_urls(run_id: str) -> dict[str, str]:
    return {
        "events_url": f"/api/agent/runs/{run_id}/events",
        "result_url": f"/api/agent/runs/{run_id}",
    }


def serialize_subagent_run_state(run: AgentRun) -> dict:
    return {
        "run_id": run.id,
        "subagent_slug": run.agent_slug,
        "child_thread_id": run.conversation_thread_id,
        "status": run.status,
        "error": run.error_message,
        **subagent_run_urls(run.id),
    }


class SubagentRunService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.run_repo = AgentRunRepository(db)
        self.thread_repo = SubagentThreadRepository(db)

    async def start(
        self,
        *,
        uid: str,
        created_by_run_id: str,
        agent_item: Agent,
        description: str,
        tool_call_id: str,
        requested_thread_id: str | None = None,
    ) -> SubagentStartResult:
        creator_run = await self.run_repo.lock_run_for_user(created_by_run_id, uid)
        if not creator_run:
            raise ValueError("Parent run does not exist")
        if creator_run.status != "running":
            raise ValueError("Parent run has already finished; cannot start a subagent")
        if creator_run.parent_run_id is not None:
            raise ValueError("A subagent cannot itself start a subagent")

        continuing = bool(requested_thread_id and requested_thread_id.strip())
        relation = await self._resolve_thread_relation(
            requested_thread_id=requested_thread_id,
            continuing=continuing,
            uid=uid,
            agent_item=agent_item,
            creator_run=creator_run,
            tool_call_id=tool_call_id,
        )

        active_run = await self.run_repo.get_active_run_by_thread_for_user(
            uid=uid, agent_slug=agent_item.slug, conversation_thread_id=relation.child_thread_id
        )
        if active_run is not None:
            raise SubagentRunBusy(
                thread_id=relation.child_thread_id,
                active_run_id=active_run.id,
                active_run_status=active_run.status,
            )

        request_id = hash_id("req:", f"{creator_run.id}:{relation.child_thread_id}:{tool_call_id}")
        intake = await agent_queue_service.intake_request(
            db=self.db,
            request_id=request_id,
            uid=uid,
            agent_slug=agent_item.slug,
            thread_id=relation.child_thread_id,
            content=description,
            queue_policy="reject",
            parent_run_id=creator_run.id,
        )
        if intake.status != "dispatched" or intake.run_id is None:
            raise SubagentRunBusy(
                thread_id=relation.child_thread_id,
                active_run_id=intake.run_id,
                active_run_status=intake.status,
            )

        await self.db.commit()
        await agent_queue_service.finalize_intake(intake)

        run = await self.run_repo.get_run(intake.run_id)
        if run is None:
            raise ValueError("Subagent run vanished immediately after creation")
        return SubagentStartResult(run=run, created=True, continuing=continuing, relation=relation)

    async def get_run_for_creator(self, *, uid: str, created_by_run_id: str, run_id: str) -> AgentRun:
        run = await self.run_repo.get_subagent_run_for_creator(
            run_id=run_id, uid=uid, created_by_run_id=created_by_run_id
        )
        if run is None:
            raise ValueError("Subagent run does not exist or does not belong to the current parent run")
        return run

    async def _resolve_thread_relation(
        self,
        *,
        requested_thread_id: str | None,
        continuing: bool,
        uid: str,
        agent_item: Agent,
        creator_run: AgentRun,
        tool_call_id: str,
    ) -> SubagentThread:
        if continuing:
            assert requested_thread_id is not None
            relation = await self.thread_repo.get_by_child_thread_for_user(requested_thread_id.strip(), uid)
            if relation is None:
                raise ValueError(f"Cannot continue subagent thread {requested_thread_id}: not found")
            if relation.subagent_slug != agent_item.slug:
                raise ValueError(f"Subagent thread {requested_thread_id} belongs to subagent {relation.subagent_slug}")
            return relation

        child_thread_id = subagent_child_thread_id(creator_run.conversation_thread_id, agent_item.slug, tool_call_id)
        existing = await self.thread_repo.get_by_child_thread_for_user(child_thread_id, uid)
        if existing is not None:
            return existing
        try:
            return await self.thread_repo.create(
                uid=uid,
                parent_run_id=creator_run.id,
                parent_thread_id=creator_run.conversation_thread_id,
                child_thread_id=child_thread_id,
                subagent_slug=agent_item.slug,
            )
        except IntegrityError:
            await self.db.rollback()
            existing = await self.thread_repo.get_by_child_thread_for_user(child_thread_id, uid)
            if existing is None:
                raise
            return existing
