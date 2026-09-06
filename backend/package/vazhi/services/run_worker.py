from __future__ import annotations

import asyncio
import json
import logging
import socket
import uuid
from datetime import timedelta
from typing import Any

from arq.worker import RetryJob
from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.runnables import RunnableConfig
from sqlalchemy.exc import OperationalError

from vazhi.agents.context import VazhiContext
from vazhi.agents.middlewares.steer import SteerMiddleware
from vazhi.agents.middlewares.subagent_task import create_subagent_task_middleware
from vazhi.agents.state import VazhiAgentState
from vazhi.models.chat import get_chat_model
from vazhi.repositories.agent_run_repository import AgentRunAttemptRepository, AgentRunRepository
from vazhi.repositories.conversation_repository import MessageRepository
from vazhi.storage.postgres.manager import get_postgres_manager
from vazhi.storage.postgres.models import utc_now_naive
from vazhi.storage.redis import get_async_redis, run_cancel_key, run_event_stream_key

logger = logging.getLogger(__name__)

WORKER_ID = f"{socket.gethostname()}:{uuid.uuid4().hex[:8]}"


class RetryableRunError(RetryJob):
    """Raising this tells ARQ to requeue the job as a new attempt, instead
    of treating the run as failed."""


def _job_try(ctx: dict) -> int:
    try:
        return int(ctx.get("job_try") or 1)
    except (TypeError, ValueError):
        return 1


def _is_last_try(ctx: dict) -> bool:
    from vazhi.config import settings

    return _job_try(ctx) >= max(1, settings.run_max_retries)


def _is_retryable_exception(exc: Exception) -> bool:
    return isinstance(exc, RetryableRunError | OperationalError | ConnectionError | TimeoutError | asyncio.TimeoutError)


def _owner_token(job_try: int) -> str:
    return f"{WORKER_ID}:{job_try}:{uuid.uuid4().hex}"


async def _publish_event(run_id: str, event_type: str, payload: dict) -> None:
    redis = get_async_redis()
    await redis.xadd(run_event_stream_key(run_id), {"data": json.dumps({"event": event_type, **payload})})


async def _is_cancel_requested(run_id: str) -> bool:
    redis = get_async_redis()
    return bool(await redis.get(run_cancel_key(run_id)))


async def _cancel_active_children(run_id: str) -> None:
    manager = get_postgres_manager()
    cancelled: list[str] = []
    async with manager.get_session() as db:
        repo = AgentRunRepository(db)
        children = await repo.get_children(run_id)
        for child in children:
            if await repo.request_cancel(child.id):
                cancelled.append(child.id)
        await db.commit()
    for child_id in cancelled:
        redis = get_async_redis()
        await redis.set(run_cancel_key(child_id), "1", ex=3600)
        await _cancel_active_children(child_id)  # cascade through the whole execution tree


async def _heartbeat_loop(run_id: str, owner_token: str, ttl_seconds: int, stop: asyncio.Event) -> None:
    manager = get_postgres_manager()
    interval = max(5, ttl_seconds // 3)
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except TimeoutError:
            pass
        if stop.is_set():
            return
        async with manager.get_session() as db:
            lease_expires_at = utc_now_naive() + timedelta(seconds=ttl_seconds)
            renewed = await AgentRunRepository(db).renew_lease(
                run_id, worker_id=owner_token, lease_expires_at=lease_expires_at
            )
            if renewed:
                await AgentRunAttemptRepository(db).renew(
                    run_id, worker_id=owner_token, lease_expires_at=lease_expires_at
                )
            await db.commit()
            if not renewed:
                logger.warning(f"Heartbeat failed to renew lease for run {run_id} — ownership likely lost")
                return


async def execute_agent_run(ctx: dict, run_id: str) -> None:
    from vazhi.config import settings

    job_try = _job_try(ctx)
    owner_token = _owner_token(job_try)
    manager = get_postgres_manager()

    lease_expires_at = utc_now_naive() + timedelta(seconds=settings.run_lease_ttl_seconds)
    async with manager.get_session() as db:
        acquired = await AgentRunRepository(db).mark_running(run_id, worker_id=owner_token, lease_expires_at=lease_expires_at)
        if acquired:
            await AgentRunAttemptRepository(db).open_attempt(run_id, worker_id=owner_token, lease_expires_at=lease_expires_at)
        await db.commit()
    if not acquired:
        logger.info(f"Run {run_id} could not be acquired (already running/terminal) — skipping")
        return

    stop_heartbeat = asyncio.Event()
    heartbeat_task = asyncio.create_task(
        _heartbeat_loop(run_id, owner_token, settings.run_lease_ttl_seconds, stop_heartbeat)
    )

    status = "failed"
    error_message: str | None = None
    output_text = ""
    output_message_id: int | None = None
    try:
        async with manager.get_session() as db:
            run = await AgentRunRepository(db).get_run(run_id)
            input_message = (
                await MessageRepository(db).get(run.input_message_id)
                if run and run.input_message_id is not None
                else None
            )
        if run is None or input_message is None:
            raise RuntimeError(f"Run {run_id} or its input message is missing")

        checkpointer = await manager.setup_langgraph_checkpointer()
        context = VazhiContext(
            run_id=run.id,
            thread_id=run.conversation_thread_id,
            uid=run.uid,
            request_id=run.request_id,
            worker_id=owner_token,
        )
        middleware: list[AgentMiddleware[Any, Any, Any]] = [SteerMiddleware()]
        subagent_middleware = await create_subagent_task_middleware(context)
        if subagent_middleware is not None:
            middleware.append(subagent_middleware)
        agent = create_agent(
            model=get_chat_model(),
            tools=[],
            middleware=middleware,
            context_schema=VazhiContext,
            state_schema=VazhiAgentState,
            checkpointer=checkpointer,
        )
        config: RunnableConfig = {"configurable": {"thread_id": run.conversation_thread_id}}

        async for message_chunk, _metadata in agent.astream(
            {"messages": [{"role": "user", "content": input_message.content}]},
            config=config,
            context=context,
            stream_mode="messages",
        ):
            if await _is_cancel_requested(run_id):
                status = "cancelled"
                break
            delta = getattr(message_chunk, "content", "") or ""
            if delta:
                output_text += delta
                await _publish_event(run_id, "message-delta", {"content": delta})
        else:
            status = "completed"

        if status == "completed" and output_text:
            async with manager.get_session() as db:
                output_message = await MessageRepository(db).create(
                    conversation_id=input_message.conversation_id,
                    role="assistant",
                    content=output_text,
                )
                output_message.run_id = run.id
                output_message_id = output_message.id
                await db.commit()

    except Exception as e:  # noqa: BLE001
        if _is_retryable_exception(e) and not _is_last_try(ctx):
            logger.warning(f"Run {run_id} retryable failure (try={job_try}): {e}")
            async with manager.get_session() as db:
                released = await AgentRunRepository(db).release_lease_for_retry(run_id, worker_id=owner_token)
                if released:
                    await AgentRunAttemptRepository(db).close(
                        run_id, worker_id=owner_token, outcome="retry_released", error_message=str(e)
                    )
                await db.commit()
            stop_heartbeat.set()
            await heartbeat_task
            raise RetryableRunError from e
        status = "failed"
        error_message = str(e)
        logger.exception(f"Run {run_id} failed: {e}")

    stop_heartbeat.set()
    await heartbeat_task

    async with manager.get_session() as db:
        finalized = await AgentRunRepository(db).mark_terminal(
            run_id,
            status=status,
            worker_id=owner_token,
            error_message=error_message,
            output_message_id=output_message_id,
        )
        if finalized:
            await AgentRunAttemptRepository(db).close(
                run_id, worker_id=owner_token, outcome=status, error_message=error_message
            )
        await db.commit()

    if finalized:
        await _publish_event(run_id, "run-finished", {"status": status, "message_id": output_message_id})
        await _cancel_active_children(run_id)
        logger.info(f"Run {run_id} finished with status={status}")


async def reconcile_expired_run_leases() -> list[str]:
    """Periodic sweep: a run whose lease expired without a heartbeat means
    its worker died mid-execution. Fail it — this failure only proves
    ownership was lost, not that side effects didn't happen, so callers
    must treat re-runs as at-least-once, not exactly-once."""
    manager = get_postgres_manager()
    reconciled = []
    async with manager.get_session() as db:
        repo = AgentRunRepository(db)
        for run in await repo.find_expired_leases():
            await repo.mark_terminal(
                run.id,
                status="failed",
                error_type="worker_lease_expired",
                error_message="Worker lease expired without heartbeat",
            )
            await AgentRunAttemptRepository(db).close_expired(run.id)
            reconciled.append(run.id)
        await db.commit()
    return reconciled
