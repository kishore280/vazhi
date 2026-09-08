from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from collections.abc import Callable
from typing import Any, cast

from langchain_mcp_adapters.client import MultiServerMCPClient

from vazhi.config import settings

logger = logging.getLogger(__name__)

_ALLOWED_TRANSPORTS = ("sse", "streamable_http")

_mcp_lock = asyncio.Lock()
_mcp_tools_cache: dict[str, list[Callable[..., Any]]] = {}
_mcp_tools_stats: dict[str, dict[str, int]] = {}


def _load_configured_mcp_servers() -> dict[str, dict[str, Any]]:
    raw = settings.vazhi_mcp_servers.strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.error("VAZHI_MCP_SERVERS is not valid JSON; ignoring")
        return {}
    if not isinstance(parsed, dict):
        return {}

    servers: dict[str, dict[str, Any]] = {}
    for slug, config in parsed.items():
        if not isinstance(config, dict) or config.get("transport") not in _ALLOWED_TRANSPORTS:
            logger.warning(f"MCP server '{slug}' has an unsupported or missing transport; skipping")
            continue
        servers[str(slug)] = config
    return servers


async def get_mcp_client(server_configs: dict[str, Any] | None = None) -> MultiServerMCPClient | None:
    try:
        client = MultiServerMCPClient(server_configs)  # pyright: ignore[reportArgumentType]
        logger.info(f"Initialized MCP client with servers: {list((server_configs or {}).keys())}")
        return client
    except Exception as e:
        logger.error(f"Failed to initialize MCP client: {e}")
        return None


def to_camel_case(s: str) -> str:
    s = re.sub(r"[-_]+(.)", lambda m: m.group(1).upper(), s)
    if len(s) > 0:
        s = s[0].lower() + s[1:]
    return s


async def get_enabled_mcp_server_config(server_slug: str) -> dict[str, Any] | None:
    return _load_configured_mcp_servers().get(server_slug)


async def get_enabled_mcp_server_slugs() -> list[str]:
    return list(_load_configured_mcp_servers().keys())


async def get_mcp_tools(
    server_slug: str,
    additional_servers: dict[str, dict[str, Any]] | None = None,
    disabled_tools: list[str] | None = None,
    cache: bool = True,
    force_refresh: bool = False,
) -> list[Callable[..., Any]]:
    if additional_servers and server_slug in additional_servers:
        server_config = additional_servers[server_slug]
    else:
        server_config = await get_enabled_mcp_server_config(server_slug)

    if server_config is None:
        logger.warning(f"MCP server '{server_slug}' not configured or disabled")
        return []

    config_payload = json.dumps(server_config, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    config_hash = hashlib.sha256(config_payload.encode("utf-8")).hexdigest()[:16]
    cache_key = f"{server_slug}:{config_hash}"

    all_processed_tools: list[Callable[..., Any]] = []

    async with _mcp_lock:
        if not force_refresh and cache and cache_key in _mcp_tools_cache:
            all_processed_tools = _mcp_tools_cache[cache_key]

    if not all_processed_tools:
        try:
            client_config = {k: v for k, v in server_config.items() if k != "disabled_tools"}
            client = await get_mcp_client({server_slug: client_config})
            if client is None:
                return []

            raw_tools = cast(list[Any], await client.get_tools())

            server_cc = to_camel_case(server_slug)
            for tool in raw_tools:
                original_name = tool.name
                tool_cc = to_camel_case(original_name)
                unique_id = f"mcp__{server_cc}__{tool_cc}"

                if tool.metadata is None:
                    tool.metadata = {}
                tool.metadata["id"] = unique_id
                tool.handle_tool_error = True
                all_processed_tools.append(tool)

            if cache:
                async with _mcp_lock:
                    stale_keys = [
                        key for key in _mcp_tools_cache if key.startswith(f"{server_slug}:") and key != cache_key
                    ]
                    for stale_key in stale_keys:
                        _mcp_tools_cache.pop(stale_key, None)
                    _mcp_tools_cache[cache_key] = all_processed_tools

                global_config_disabled = server_config.get("disabled_tools") or []
                enabled_count = len([t for t in all_processed_tools if t.name not in global_config_disabled])  # pyright: ignore[reportFunctionMemberAccess]
                _mcp_tools_stats[server_slug] = {
                    "total": len(all_processed_tools),
                    "enabled": enabled_count,
                    "disabled": len(all_processed_tools) - enabled_count,
                }
                logger.info(
                    f"Refreshed MCP tools cache for '{server_slug}' with key '{cache_key}': "
                    f"{len(all_processed_tools)} tools loaded."
                )

        except ExceptionGroup as e:
            logger.warning(f"MCP server '{server_slug}' failed with group error: {e}")
            return []
        except Exception as e:
            logger.exception(f"Failed to load tools from MCP server '{server_slug}': {e}")
            return []

    if disabled_tools:
        filtered_tools = [t for t in all_processed_tools if t.name not in disabled_tools]  # pyright: ignore[reportFunctionMemberAccess]
        logger.debug(
            f"Returning {len(filtered_tools)}/{len(all_processed_tools)} tools for '{server_slug}' "
            f"(filtered {len(disabled_tools)} by argument)"
        )
        return filtered_tools

    return all_processed_tools


async def get_tools_from_all_servers() -> list[Callable[..., Any]]:
    server_configs = _load_configured_mcp_servers()
    all_tools: list[Callable[..., Any]] = []
    for server_slug in server_configs:
        tools = await get_mcp_tools(server_slug, additional_servers=server_configs)
        all_tools.extend(tools)
    return all_tools


def clear_mcp_cache() -> None:
    global _mcp_tools_cache, _mcp_tools_stats
    _mcp_tools_cache = {}
    _mcp_tools_stats = {}


def clear_mcp_server_tools_cache(server_slug: str) -> None:
    global _mcp_tools_cache, _mcp_tools_stats
    server_prefix = f"{server_slug}:"
    stale_keys = [key for key in _mcp_tools_cache if key.startswith(server_prefix)]
    for stale_key in stale_keys:
        _mcp_tools_cache.pop(stale_key, None)
    _mcp_tools_stats.pop(server_slug, None)
    logger.info(f"Cleared tools cache for MCP server '{server_slug}'")


def get_mcp_tools_stats(server_slug: str) -> dict[str, int] | None:
    return _mcp_tools_stats.get(server_slug)
