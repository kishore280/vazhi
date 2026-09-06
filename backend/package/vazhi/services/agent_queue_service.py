from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from vazhi.repositories.agent_run_repository import AgentRunRepository
from vazhi.repositories.agent_run_request_repository import AgentRunRequestRepository
from vazhi.repositories.conversation_repository import (
    ConversationRepository,
    MessageRepository,
)
from vazhi.storage.postgres.manager import get_postgres_manager

logger = logging.getLogger(__name__)

SUPPORTED_QUEUE_POLICIES = ("enqueue", "reject", "steer")


@dataclass(frozen=True)
class IntakeResult:
    request_id: str
    status: str  # queued / dispatched / rejected
    queue_policy: str
    message_id: int
    thread_id: str
    run_id: str | None = None
    queue_position: int | None = None


def validate_queue_policy(queue_policy: str) -> str:
    if queue_policy not in SUPPORTED_QUEUE_POLICIES:
        raise ValueError(f"Unsupported queue_policy: {queue_policy}")
    return queue_policy


async def intake_request(
    *,
    db: AsyncSession,
    request_id: str,
    uid: str,
    agent_slug: str,
    thread_id: str,
    content: str,
    queue_policy: str = "enqueue",
    parent_run_id: str | None = None,
) -> IntakeResult:
    policy = validate_queue_policy(queue_policy)
    uid_str = str(uid)
    request_repo = AgentRunRequestRepository(db)
    run_repo = AgentRunRepository(db)
    conversation_repo = ConversationRepository(db)
    message_repo = MessageRepository(db)

    existing = await request_repo.get_by_request_id(request_id)
    if existing is not None:
        return await _existing_intake_result(request_repo, existing)

    conversation = await conversation_repo.get_or_create(thread_id=thread_id, uid=uid_str, agent_slug=agent_slug)

    existing = await request_repo.get_by_request_id(request_id)
    if existing is not None:
        return await _existing_intake_result(request_repo, existing)

    active_run = await run_repo.get_active_run_by_thread_for_user(
        uid=uid_str, agent_slug=agent_slug, conversation_thread_id=thread_id
    )
    existing_head = await request_repo.list_queued(uid=uid_str, agent_slug=agent_slug, conversation_thread_id=thread_id)
    existing_head = existing_head[0] if existing_head else None

    if policy == "steer":
        if active_run is None:
            raise ValueError("Nothing running to steer")
        pending_steer = await request_repo.get_pending_steer(
            uid=uid_str, agent_slug=agent_slug, conversation_thread_id=thread_id
        )
        if pending_steer is not None:
            raise ValueError("Thread already has a pending steer request")

    reject_without_dispatch = policy == "reject" and (active_run is not None or existing_head is not None)

    try:
        message = await message_repo.create(
            conversation_id=conversation.id,
            role="user",
            content=content,
            request_id=request_id,
        )
        request_status = "rejected" if reject_without_dispatch else "queued"
        request = await request_repo.create(
            request_id=request_id,
            uid=uid_str,
            agent_slug=agent_slug,
            conversation_thread_id=thread_id,
            queue_policy=policy,
            input_message_id=message.id,
            status=request_status,
        )
    except IntegrityError:
        existing = await request_repo.get_by_request_id(request_id)
        if existing is not None:
            return await _existing_intake_result(request_repo, existing)
        raise

    if reject_without_dispatch:
        return IntakeResult(
            request_id=request_id, status="rejected", queue_policy=policy, message_id=message.id, thread_id=thread_id
        )

    if policy != "reject" or active_run is None:
        dispatched = await _dispatch_ready_head(
            db=db,
            uid=uid_str,
            agent_slug=agent_slug,
            thread_id=thread_id,
            conversation_id=conversation.id,
            parent_run_id=parent_run_id,
            expected_request_id=request_id if policy == "reject" else None,
        )
        if dispatched is not None and dispatched[0] == request_id:
            return IntakeResult(
                request_id=request_id,
                status="dispatched",
                queue_policy=policy,
                message_id=message.id,
                thread_id=thread_id,
                run_id=dispatched[1],
            )

    if policy == "reject":
        request.status = "rejected"
        await db.flush()
        return IntakeResult(
            request_id=request_id, status="rejected", queue_policy=policy, message_id=message.id, thread_id=thread_id
        )

    return IntakeResult(
        request_id=request_id,
        status="queued",
        queue_policy=policy,
        message_id=message.id,
        thread_id=thread_id,
        queue_position=await request_repo.get_queue_position(request_id),
    )


async def finalize_intake(intake: IntakeResult) -> None:
    # Never enqueue before commit.
    if intake.status == "dispatched" and intake.run_id:
        from vazhi.services.run_dispatch import enqueue_agent_run
        await enqueue_agent_run(intake.run_id)


async def _existing_intake_result(request_repo: AgentRunRequestRepository, request) -> IntakeResult:
    return IntakeResult(
        request_id=request.request_id,
        status=request.status,
        queue_policy=request.queue_policy,
        message_id=request.input_message_id,
        thread_id=request.conversation_thread_id,
        run_id=request.dispatched_run_id,
        queue_position=await request_repo.get_queue_position(request.request_id)
        if request.status == "queued"
        else None,
    )


async def _dispatch_ready_head(
    *,
    db: AsyncSession,
    uid: str,
    agent_slug: str,
    thread_id: str,
    conversation_id: int,
    parent_run_id: str | None = None,
    expected_request_id: str | None = None,
) -> tuple[str, str] | None:
    request_repo = AgentRunRequestRepository(db)
    run_repo = AgentRunRepository(db)

    head = await request_repo.get_queue_head(uid=uid, agent_slug=agent_slug, conversation_thread_id=thread_id)
    if head is None:
        return None
    if expected_request_id is not None and head.request_id != expected_request_id:
        return None

    active_run = await run_repo.get_active_run_by_thread_for_user(
        uid=uid, agent_slug=agent_slug, conversation_thread_id=thread_id
    )
    if active_run is not None:
        return None

    run_id = str(uuid.uuid4())
    try:
        run = await run_repo.create_run(
            run_id=run_id,
            conversation_thread_id=thread_id,
            agent_slug=agent_slug,
            uid=uid,
            request_id=head.request_id,
            conversation_id=conversation_id,
            input_message_id=head.input_message_id,
            parent_run_id=parent_run_id,
        )
        message = await MessageRepository(db).get(head.input_message_id)
        if message is not None:
            message.run_id = run.id
        await request_repo.mark_dispatched(head.request_id, run_id=run.id)
    except IntegrityError as exc:
        constraint_name = getattr(getattr(exc.orig, "__cause__", None), "constraint_name", None)
        if constraint_name != "uq_agent_runs_one_active_per_thread":
            raise
        logger.info(f"Dispatch conflict for {head.request_id}, keeping queued")
        return None

    return head.request_id, run_id

async def should_end_run_for_steer(run_id:str) -> bool:
    manager = get_postgres_manager()
    async with manager.get_session() as db:
        run = await AgentRunRepository(db).get_run(run_id)
        if run is None:
            return False
        pending = await AgentRunRequestRepository(db).get_pending_steer(
            uid=run.uid,
            agent_slug=run.agent_slug,
            conversation_thread_id=run.conversation_thread_id,
        )
        return pending is not None
