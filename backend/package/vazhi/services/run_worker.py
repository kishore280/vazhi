from __future__ import annotations

import json
import logging
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.runnables import RunnableConfig

from vazhi.agents.context import VazhiContext
from vazhi.agents.middlewares.steer import SteerMiddleware
from vazhi.models.chat import get_chat_model
from vazhi.repositories.agent_run_repository import AgentRunRepository
from vazhi.repositories.conversation_repository import MessageRepository
from vazhi.storage.postgres.manager import get_postgres_manager
from vazhi.storage.redis import get_async_redis, run_event_stream_key

logger = logging.getLogger(__name__)


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

        checkpointer = await manager.setup_langgraph_checkpointer()
        context = VazhiContext(
            run_id=run.id,
            thread_id=run.conversation_thread_id,
            uid=run.uid,
            request_id=run.request_id,
        )
        middleware: list[AgentMiddleware[Any, Any, Any]] = [SteerMiddleware()]
        agent = create_agent(
            model=get_chat_model(),
            tools=[],
            middleware=middleware,
            context_schema=VazhiContext,
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
