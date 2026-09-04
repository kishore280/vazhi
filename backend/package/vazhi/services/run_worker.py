from __future__ import annotations

import logging

from langchain.agents import create_agent

from vazhi.models.chat import get_chat_model
from vazhi.repositories.agent_run_repository import AgentRunRepository
from vazhi.repositories.conversation_repository import MessageRepository
from vazhi.storage.postgres.manager import get_postgres_manager

logger = logging.getLogger(__name__)


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

        agent = create_agent(model=get_chat_model(), tools=[])
        result = await agent.ainvoke({"messages": [{"role": "user", "content": input_message.content}]})
        reply_content = result["messages"][-1].content #last item of list ahm

        output_message = await message_repo.create(
            conversation_id=input_message.conversation_id,
            role="assistant",
            content=reply_content,
        )
        output_message.run_id = run.id

        run.status = "completed"
        run.output_message_id = output_message.id
        await db.commit()
        logger.info(f"Run {run_id} completed with a real LLM reply")
