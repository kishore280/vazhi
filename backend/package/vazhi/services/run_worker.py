from __future__ import annotations

import json
import logging
import socket
import uuid
from datetime import timedelta
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.runnables import RunnableConfig

from vazhi.agents.context import VazhiContext
from vazhi.agents.middlewares.steer import SteerMiddleware
from vazhi.agents.state import VazhiAgentState
from vazhi.models.chat import get_chat_model
from vazhi.repositories.agent_run_repository import AgentRunRepository
from vazhi.repositories.conversation_repository import MessageRepository
from vazhi.storage.postgres.manager import get_postgres_manager
from vazhi.storage.postgres.models import utc_now_naive
from vazhi.storage.redis import get_async_redis, run_event_stream_key

logger = logging.getLogger(__name__)

WORKER_ID = f"{socket.gethostname()}:{uuid.uuid4().hex[:8]}"


async def _publish_event(run_id: str, event_type: str, payload: dict) -> None:  
    redis = get_async_redis()
    await redis.xadd(run_event_stream_key(run_id), {"data": json.dumps({"event": event_type, **payload})})


async def execute_agent_run(ctx: dict, run_id: str) -> None:  #arq ku venum ctx dict avlo dhan.. yenu kekaadha
    manager = get_postgres_manager()
    async with manager.get_session() as db:
        run_repo = AgentRunRepository(db)
        message_repo = MessageRepository(db)

        run = await run_repo.get_run(run_id)
        if run is None:
            logger.warning(f"execute_agent_run: run {run_id} not found")
            return

        if run.input_message_id is None:
            logger.warning(f"execute_agent_run: run {run_id} has no input message")
            return

        input_message = await message_repo.get(run.input_message_id)
        if input_message is None:
            logger.warning(f"execute_agent_run: input message {run.input_message_id} not found")
            return

        from vazhi.config import settings

        job_try = int(ctx.get("job_try") or 1)
        owner_token = f"{WORKER_ID}:{job_try}:{uuid.uuid4().hex}"
        lease_expires_at = utc_now_naive() + timedelta(seconds=settings.run_lease_ttl_seconds)
        acquired = await run_repo.mark_running(run_id, worker_id=owner_token, lease_expires_at=lease_expires_at)
        if not acquired:
            logger.info(f"Run {run_id} could not be acquired (already running/terminal) — skipping")
            return

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

        output_text = ""
        async for message_chunk, _metadata in agent.astream(
            {"messages": [{"role": "user", "content": input_message.content}]},
            config=config,
            context=context,
            stream_mode="messages",
        ):
            delta = getattr(message_chunk, "content", "") or ""
            if delta:
                output_text += delta
                await _publish_event(run_id, "message-delta", {"content": delta})

        output_message = await message_repo.create(
            conversation_id=input_message.conversation_id,
            role="assistant",
            content=output_text,
        )
        output_message.run_id = run.id

        run.status = "completed"
        run.output_message_id = output_message.id
        await db.commit()

        await _publish_event(run_id, "run-finished", {"status": "completed", "message_id": output_message.id})
        logger.info(f"Run {run_id} completed with streamed LLM reply")
