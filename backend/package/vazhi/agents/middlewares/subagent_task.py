from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, Any

from deepagents.middleware._utils import append_to_system_message
from langchain.agents.middleware.types import AgentMiddleware, ContextT, ModelRequest, ModelResponse, ResponseT
from langchain_core.messages import ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.prebuilt.tool_node import ToolRuntime
from langgraph.types import Command

from vazhi.repositories.agent_repository import AgentRepository
from vazhi.storage.postgres.manager import get_postgres_manager
from vazhi.storage.postgres.models import Agent

TASK_SYSTEM_PROMPT = """## `task` (subagent task tool)

You can hand a complex, self-contained subtask to a configured subagent with the `task` tool. The subagent \
only returns its final result — you don't see its intermediate steps. The tool result includes the subagent \
thread ID; pass that back as `thread_id` on a later `task` call to continue the same subtask.

When to use it:
- The task is complex enough to run on its own, or needs an isolated context.
- Independent subtasks can be dispatched in parallel with multiple `task` calls.
- Pass a prior result's `thread_id` to continue an existing subagent task; omit it for a new task.
- Never call the same `thread_id` in parallel — concurrent continuations of one child thread will conflict.
- Don't delegate simple questions or things that take only a few direct tool calls.
- Always pick a `subagent_slug` from the list below, and write the goal, context, and expected output in \
`description`.
- Never invoke a subagent indirectly through shell, curl, an HTTP API, or the command line — always use the \
`task` tool.

Background subagents:
- For long or parallelizable work, prefer `subagent_start` — it returns `run_id` and `thread_id` immediately \
so the parent can keep working.
- Use `subagent_status` to check progress, `subagent_cancel` to cancel, `subagent_await` to block once you \
actually need the result.
- `thread_id` is the subagent's long-lived context ID; once a run on it finishes, a new run can continue the \
same thread_id. A thread with a run already in progress returns busy rather than silently queueing.
- Keep using `task` for short work the parent must have the result of immediately.

Available subagent slugs:

{available_agents}"""

TASK_TOOL_DESCRIPTION = """Launch a configured subagent to handle an isolated task.

Available subagent slugs:
{available_agents}

Use `subagent_slug` to select one available subagent and put the full task brief in `description`.
Omit `thread_id` for a new task. To continue a previous subagent task, pass the child thread ID returned by
that prior task result as `thread_id`.
Do not call subagents through shell, curl, HTTP APIs, or command-line indirection."""

SUBAGENT_START_DESCRIPTION = """Start a configured subagent asynchronously.

Returns a child thread ID for future continuation and a run ID for status/cancel/result checks.
Use this for long-running or parallelizable subagent work. If `thread_id` is provided, it continues that subagent
thread when no active run is currently writing to it."""

SUBAGENT_STATUS_DESCRIPTION = """Check a subagent run status by run_id.

Returns the current run status, a compact progress summary, and the final result when the run has reached a
terminal status."""

SUBAGENT_CANCEL_DESCRIPTION = """Cancel a running subagent run by run_id."""

SUBAGENT_AWAIT_DESCRIPTION = """Wait for a subagent run to finish and return its final result."""

TASK_DESCRIPTION_ARG = (
    "The task for the subagent to complete independently, with necessary context and expected output."
)
SUBAGENT_SLUG_ARG = "The subagent slug to call — must be one of the available slugs listed in the tool description."
TASK_THREAD_ID_ARG = (
    "Optional. An existing subagent thread ID to continue, usually from a prior task result. Omit for a new task."
)
ASYNC_THREAD_ID_ARG = (
    "Optional. An existing background subagent thread ID to continue, from a prior subagent_start result. "
    "Omit for a new task."
)
SUBAGENT_RUN_ID_ARG = "The subagent run ID, returned by subagent_start."


async def create_subagent_task_middleware(parent_context) -> VazhiSubAgentMiddleware | None:
    """Load available subagents for the parent context; return a task middleware only if any exist."""
    uid = str(getattr(parent_context, "uid", "") or "").strip()
    if not uid:
        return None

    manager = get_postgres_manager()
    async with manager.get_session() as db:
        subagents = await AgentRepository(db).list_subagents()

    if not subagents:
        return None
    return VazhiSubAgentMiddleware(parent_context=parent_context, subagents=subagents)


def _async_only_tool(*, name: str, coroutine: Callable[..., Awaitable[Any]], description: str) -> StructuredTool:
    """Background subagent tools only run on the async path; sync callers get a clear LangChain error."""
    return StructuredTool.from_function(name=name, coroutine=coroutine, description=description, infer_schema=True)


class VazhiSubAgentMiddleware(AgentMiddleware[Any, ContextT, ResponseT]):
    def __init__(self, *, parent_context, subagents: list[Agent]) -> None:
        super().__init__()
        self.parent_context = parent_context
        self.subagents = {agent.slug: agent for agent in subagents}
        available_agents = "\n".join(f"- {agent.slug}: {agent.description or agent.name}" for agent in subagents)
        self.system_prompt = TASK_SYSTEM_PROMPT.format(available_agents=available_agents)
        self.tools = [self._build_task_tool(available_agents), *self._build_async_subagent_tools(available_agents)]

    def wrap_model_call(
        self,
        request: ModelRequest[ContextT],
        handler: Callable[[ModelRequest[ContextT]], ModelResponse[ResponseT]],
    ) -> ModelResponse[ResponseT]:
        return handler(
            request.override(system_message=append_to_system_message(request.system_message, self.system_prompt))
        )

    async def awrap_model_call(
        self,
        request: ModelRequest[ContextT],
        handler: Callable[[ModelRequest[ContextT]], Awaitable[ModelResponse[ResponseT]]],
    ) -> ModelResponse[ResponseT]:
        return await handler(
            request.override(system_message=append_to_system_message(request.system_message, self.system_prompt))
        )

    def _build_task_tool(self, available_agents: str) -> StructuredTool:
        """The task tool: start a subagent run and block until its final result."""

        async def atask(
            description: Annotated[str, TASK_DESCRIPTION_ARG],
            subagent_slug: Annotated[str, SUBAGENT_SLUG_ARG],
            runtime: ToolRuntime,
            thread_id: Annotated[str | None, TASK_THREAD_ID_ARG] = None,
        ) -> str | Command:
            assert runtime.tool_call_id
            tool_call_id = runtime.tool_call_id
            started, error = await self._start_subagent(
                description=description,
                subagent_slug=subagent_slug,
                runtime=runtime,
                thread_id=thread_id,
                error_prefix="Could not call subagent",
            )
            if error is not None:
                return error
            assert started is not None

            parent_runtime = started.parent_runtime
            from vazhi.services.agent_run_service import AgentRunWaitTimeout, await_agent_run_result

            try:
                result = await await_agent_run_result(started.result.run.id, current_uid=parent_runtime.uid)
                run = await self._get_verified_subagent_run(
                    run_id=started.result.run.id,
                    uid=parent_runtime.uid,
                    created_by_run_id=parent_runtime.created_by_run_id,
                )
            except AgentRunWaitTimeout as exc:
                try:
                    run = await self._get_verified_subagent_run(
                        run_id=started.result.run.id,
                        uid=parent_runtime.uid,
                        created_by_run_id=parent_runtime.created_by_run_id,
                    )
                except ValueError as verify_exc:
                    return str(verify_exc)
                from vazhi.services.subagent_run_service import serialize_subagent_run_state

                subagent_run = serialize_subagent_run_state(run)
                return _task_wait_timeout_response(exc.result, tool_call_id, subagent_run)
            except ValueError as exc:
                return str(exc)

            from vazhi.services.subagent_run_service import serialize_subagent_run_state

            subagent_run = serialize_subagent_run_state(run)
            return _task_result_response(result, tool_call_id, subagent_run)

        return _async_only_tool(
            name="task",
            coroutine=atask,
            description=TASK_TOOL_DESCRIPTION.format(available_agents=available_agents),
        )

    def _build_async_subagent_tools(self, available_agents: str) -> list[StructuredTool]:
        """Background subagent lifecycle tools: start/status/cancel/await."""

        async def asubagent_start(
            description: Annotated[str, TASK_DESCRIPTION_ARG],
            subagent_slug: Annotated[str, SUBAGENT_SLUG_ARG],
            runtime: ToolRuntime,
            thread_id: Annotated[str | None, ASYNC_THREAD_ID_ARG] = None,
        ) -> str | Command:
            assert runtime.tool_call_id
            tool_call_id = runtime.tool_call_id
            started, error = await self._start_subagent(
                description=description,
                subagent_slug=subagent_slug,
                runtime=runtime,
                thread_id=thread_id,
                error_prefix="Could not start subagent",
            )
            if error is not None:
                return error
            assert started is not None

            result, agent_item = started.result, started.agent_item
            from vazhi.services.subagent_run_service import serialize_subagent_run_state, subagent_run_urls

            payload = {
                "status": "started" if result.created else "existing",
                "run_id": result.run.id,
                "thread_id": result.relation.child_thread_id,
                "subagent_slug": subagent_slug,
                "subagent_name": agent_item.name,
                "run_status": result.run.status,
                "continuing": result.continuing,
                **subagent_run_urls(result.run.id),
            }
            subagent_run = serialize_subagent_run_state(result.run)
            return _json_tool_command(payload, tool_call_id, subagent_run=subagent_run)

        async def asubagent_status(
            run_id: Annotated[str, SUBAGENT_RUN_ID_ARG],
            runtime: ToolRuntime,
        ) -> str | Command:
            assert runtime.tool_call_id
            tool_call_id = runtime.tool_call_id
            from vazhi.services.agent_run_service import get_agent_run_progress, get_agent_run_result

            parent_runtime, runtime_error = self._require_async_parent_runtime("Could not check subagent status")
            if runtime_error:
                return runtime_error
            try:
                run = await self._get_verified_subagent_run(
                    uid=parent_runtime.uid,
                    created_by_run_id=parent_runtime.created_by_run_id,
                    run_id=run_id,
                )
                result = None
                if run.status in ("completed", "failed", "cancelled", "interrupted"):
                    result = await get_agent_run_result(run.id, current_uid=parent_runtime.uid)
            except ValueError as exc:
                return str(exc)

            from vazhi.services.subagent_run_service import serialize_subagent_run_state, subagent_run_urls

            payload = {
                "status": run.status,
                "run_id": run.id,
                "thread_id": run.conversation_thread_id,
                "subagent_slug": run.agent_slug,
                "error": run.error_message,
                "progress": await get_agent_run_progress(run.id),
                **subagent_run_urls(run.id),
            }
            if result:
                payload["result"] = result
            subagent_run = serialize_subagent_run_state(run)
            return _json_tool_command(payload, tool_call_id, subagent_run=subagent_run)

        async def asubagent_cancel(
            run_id: Annotated[str, SUBAGENT_RUN_ID_ARG],
            runtime: ToolRuntime,
        ) -> str | Command:
            assert runtime.tool_call_id
            tool_call_id = runtime.tool_call_id
            from vazhi.services.agent_run_service import request_cancel_agent_run

            parent_runtime, runtime_error = self._require_async_parent_runtime("Could not cancel subagent")
            if runtime_error:
                return runtime_error
            try:
                await self._get_verified_subagent_run(
                    run_id=run_id,
                    uid=parent_runtime.uid,
                    created_by_run_id=parent_runtime.created_by_run_id,
                )
                run = await request_cancel_agent_run(run_id, current_uid=parent_runtime.uid)
            except ValueError as exc:
                return str(exc)
            if run is None:
                return "Subagent run does not exist"

            from vazhi.services.subagent_run_service import serialize_subagent_run_state, subagent_run_urls

            payload = {
                "status": run.status,
                "run_id": run.id,
                "thread_id": run.conversation_thread_id,
                **subagent_run_urls(run.id),
            }
            subagent_run = serialize_subagent_run_state(run)
            return _json_tool_command(payload, tool_call_id, subagent_run=subagent_run)

        async def asubagent_await(
            run_id: Annotated[str, SUBAGENT_RUN_ID_ARG],
            runtime: ToolRuntime,
        ) -> str | Command:
            assert runtime.tool_call_id
            tool_call_id = runtime.tool_call_id
            from vazhi.services.agent_run_service import AgentRunWaitTimeout, await_agent_run_result

            parent_runtime, runtime_error = self._require_async_parent_runtime("Could not wait for subagent")
            if runtime_error:
                return runtime_error
            wait_timed_out = False
            try:
                await self._get_verified_subagent_run(
                    run_id=run_id,
                    uid=parent_runtime.uid,
                    created_by_run_id=parent_runtime.created_by_run_id,
                )
                result = await await_agent_run_result(run_id, current_uid=parent_runtime.uid)
                run = await self._get_verified_subagent_run(
                    run_id=run_id,
                    uid=parent_runtime.uid,
                    created_by_run_id=parent_runtime.created_by_run_id,
                )
            except AgentRunWaitTimeout as exc:
                wait_timed_out = True
                result = exc.result
                try:
                    run = await self._get_verified_subagent_run(
                        run_id=run_id,
                        uid=parent_runtime.uid,
                        created_by_run_id=parent_runtime.created_by_run_id,
                    )
                except ValueError as verify_exc:
                    return str(verify_exc)
            except ValueError as exc:
                return str(exc)

            from vazhi.services.subagent_run_service import serialize_subagent_run_state

            payload = {
                "status": run.status,
                "run_id": run.id,
                "thread_id": run.conversation_thread_id,
                "result": result,
            }
            if wait_timed_out:
                payload["wait_timed_out"] = True
                payload["message"] = (
                    "The subagent is still running; waiting for its final result timed out. "
                    "Check back with subagent_status or subagent_await."
                )
            subagent_run = serialize_subagent_run_state(run)
            return _json_tool_command(payload, tool_call_id, subagent_run=subagent_run)

        return [
            _async_only_tool(
                name="subagent_start",
                coroutine=asubagent_start,
                description=SUBAGENT_START_DESCRIPTION + "\n\nAvailable subagent slugs:\n" + available_agents,
            ),
            _async_only_tool(
                name="subagent_status",
                coroutine=asubagent_status,
                description=SUBAGENT_STATUS_DESCRIPTION,
            ),
            _async_only_tool(
                name="subagent_cancel",
                coroutine=asubagent_cancel,
                description=SUBAGENT_CANCEL_DESCRIPTION,
            ),
            _async_only_tool(
                name="subagent_await",
                coroutine=asubagent_await,
                description=SUBAGENT_AWAIT_DESCRIPTION,
            ),
        ]

    def _parent_runtime(self) -> _ParentRuntime:
        uid = str(getattr(self.parent_context, "uid", "") or "").strip()
        created_by_run_id = str(getattr(self.parent_context, "run_id", "") or "").strip()
        return _ParentRuntime(uid=uid, created_by_run_id=created_by_run_id)

    def _require_async_parent_runtime(self, error_prefix: str) -> tuple[_ParentRuntime, str | None]:
        parent_runtime = self._parent_runtime()
        if not parent_runtime.uid:
            return parent_runtime, f"{error_prefix}: current runtime is missing uid"
        if not parent_runtime.created_by_run_id:
            return parent_runtime, f"{error_prefix}: current runtime is missing a parent run id"
        return parent_runtime, None

    async def _start_subagent(
        self,
        *,
        description: str,
        subagent_slug: str,
        runtime: ToolRuntime,
        thread_id: str | None,
        error_prefix: str,
    ) -> tuple[_StartedSubagent | None, str | Command | None]:
        """Validate and start (or continue) a background subagent run.
        Success returns the start result; failure returns a response that
        can be returned to the model directly."""
        if subagent_slug not in self.subagents:
            allowed = ", ".join(f"`{slug}`" for slug in self.subagents)
            return None, f"Cannot call subagent {subagent_slug}; available subagents are: {allowed}"
        if not runtime.tool_call_id:
            raise ValueError("Tool call ID is required for subagent invocation")

        parent_runtime, runtime_error = self._require_async_parent_runtime(error_prefix)
        if runtime_error:
            return None, runtime_error

        agent_item = self.subagents[subagent_slug]
        from vazhi.services.subagent_run_service import SubagentRunBusy
        from vazhi.storage.postgres.manager import get_postgres_manager

        manager = get_postgres_manager()
        try:
            async with manager.get_session() as db:
                from vazhi.services.subagent_run_service import SubagentRunService

                result = await SubagentRunService(db).start(
                    uid=parent_runtime.uid,
                    created_by_run_id=parent_runtime.created_by_run_id,
                    agent_item=agent_item,
                    description=description,
                    tool_call_id=runtime.tool_call_id,
                    requested_thread_id=thread_id,
                )
        except SubagentRunBusy as exc:
            return None, _json_tool_command(exc.to_payload(), runtime.tool_call_id)
        except ValueError as exc:
            return None, str(exc)
        return _StartedSubagent(result=result, parent_runtime=parent_runtime, agent_item=agent_item), None

    async def _get_verified_subagent_run(self, *, run_id: str, uid: str, created_by_run_id: str):
        from vazhi.services.subagent_run_service import SubagentRunService

        manager = get_postgres_manager()
        async with manager.get_session() as db:
            return await SubagentRunService(db).get_run_for_creator(
                uid=uid, created_by_run_id=created_by_run_id, run_id=run_id
            )


@dataclass(frozen=True)
class _ParentRuntime:
    uid: str
    created_by_run_id: str


@dataclass(frozen=True)
class _StartedSubagent:
    result: Any  # SubagentStartResult
    parent_runtime: _ParentRuntime
    agent_item: Agent


def _task_result_response(result: dict[str, Any], tool_call_id: str, subagent_run: dict[str, Any]) -> Command:
    output = str(result.get("output") or "").strip()
    error = result.get("error") if isinstance(result.get("error"), dict) else None
    if not output and error:
        output = str(error.get("message") or "The subagent run failed.")
    if not output:
        output = "The subagent finished but returned no text result."

    tool_result = _tool_result_with_thread_id(subagent_run["child_thread_id"], output)
    return Command(
        update={"messages": [ToolMessage(tool_result, tool_call_id=tool_call_id)], "subagent_runs": [subagent_run]}
    )


def _task_wait_timeout_response(result: dict[str, Any], tool_call_id: str, subagent_run: dict[str, Any]) -> Command:
    status = str(result.get("status") or subagent_run.get("status") or "running")
    run_id = str(result.get("agent_run_id") or subagent_run["run_id"])
    output = (
        f"The subagent is still running (status: {status}) and hasn't returned a final text result yet.\n"
        f"run_id: {run_id}\n"
        "Check back with subagent_status or subagent_await later; do not treat this as task completion."
    )
    tool_result = _tool_result_with_thread_id(subagent_run["child_thread_id"], output)
    return Command(
        update={"messages": [ToolMessage(tool_result, tool_call_id=tool_call_id)], "subagent_runs": [subagent_run]}
    )


def _json_tool_command(
    payload: dict[str, Any],
    tool_call_id: str,
    *,
    subagent_run: dict[str, Any] | None = None,
) -> Command:
    content = json.dumps(payload, ensure_ascii=False, indent=2)
    update: dict[str, Any] = {"messages": [ToolMessage(content, tool_call_id=tool_call_id)]}
    if subagent_run is not None:
        update["subagent_runs"] = [subagent_run]
    return Command(update=update)


def _tool_result_with_thread_id(child_thread_id: str, content: str) -> str:
    return f"> Subagent thread ID: {child_thread_id}\n\n---\n\n{content}"
