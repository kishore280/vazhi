from __future__ import annotations

import redis.asyncio as aioredis
from arq.connections import RedisSettings

_async_client: aioredis.Redis | None = None

def get_async_redis() -> aioredis.Redis:
    global _async_client
    if _async_client is None:
        from vazhi.config import settings

        _async_client = aioredis.Redis.from_url(settings.redis_url, decode_responses=True)
    return _async_client

def get_arq_redis_settings() -> RedisSettings: #arq ku own connection format venum soooooo
    from vazhi.config import settings
    return RedisSettings.from_dsn(settings.redis_url)

#indha rendum for cancel and all during streaminggg
def run_event_stream_key(run_id: str) -> str:
    return f"vazhi:run:{run_id}:events"

def run_cancel_key(run_id: str) -> str:
    return f"vazhi:run:{run_id}:cancel"