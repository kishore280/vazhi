from __future__ import annotations

from langchain.agents.middleware import AgentMiddleware, hook_config


class SteerMiddleware(AgentMiddleware):
    @hook_config(can_jump_to=["end"])
    async def abefore_model(self, state, runtime):
        return await self._jump_if_steer_requested(runtime)

    @hook_config(can_jump_to=["end"])
    async def aafter_model(self, state, runtime):
        if _last_message_has_tool_calls(state):
            return None
        return await self._jump_if_steer_requested(runtime)

    async def _jump_if_steer_requested(self, runtime):
        from vazhi.services.agent_queue_service import should_end_run_for_steer
        run_id = getattr(runtime.context, "run_id", None)
        if not run_id or not await should_end_run_for_steer(run_id):
            return None
        return {"jump_to": "end"}


def _last_message_has_tool_calls(state) -> bool:
    messages = state.get("messages") if isinstance(state, dict) else None
    if not messages:
        return False
    last_message = messages[-1]
    if isinstance(last_message, dict):
        return bool(last_message.get("tool_calls"))
    return bool(getattr(last_message, "tool_calls", None))