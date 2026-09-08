from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse

from vazhi.agents.mcp.service import get_mcp_tools

logger = logging.getLogger(__name__)


class DynamicToolMiddleware(AgentMiddleware):
    def __init__(self, base_tools: list[Any], mcp_servers: list[str] | None = None):
        super().__init__()
        self.tools: list[Any] = base_tools  # pyright: ignore[reportIncompatibleVariableOverride]
        self._all_mcp_tools: dict[str, list[Any]] = {}
        self._mcp_servers = mcp_servers or []

    async def initialize_mcp_tools(self) -> None:
        for mcp_name in self._mcp_servers:
            if mcp_name not in self._all_mcp_tools:
                logger.info(f"Pre-loading MCP tools from: {mcp_name}")
                mcp_tools = await get_mcp_tools(mcp_name)
                self._all_mcp_tools[mcp_name] = mcp_tools
                self.tools.extend(mcp_tools)
                logger.info(f"Registered {len(mcp_tools)} tools from {mcp_name}")

    async def awrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[ModelResponse]]
    ) -> ModelResponse:
        selected_tools = getattr(request.runtime.context, "tools", None)
        selected_mcps = getattr(request.runtime.context, "mcps", None)

        enabled_tools = []

        if selected_tools and isinstance(selected_tools, list) and len(selected_tools) > 0:
            enabled_tools = [tool for tool in self.tools if tool.name in selected_tools]

        if selected_mcps and isinstance(selected_mcps, list) and len(selected_mcps) > 0:
            for mcp in selected_mcps:
                if mcp in self._all_mcp_tools:
                    enabled_tools.extend(self._all_mcp_tools[mcp])
                else:
                    logger.warning(f"MCP server '{mcp}' not pre-loaded. Add it to mcp_servers.")

        logger.info(
            f"Dynamic tool selection: {len(enabled_tools)} tools enabled: {[tool.name for tool in enabled_tools]}, "
            f"selected_tools: {selected_tools}, selected_mcps: {selected_mcps}"
        )

        request = request.override(tools=enabled_tools)
        return await handler(request)
