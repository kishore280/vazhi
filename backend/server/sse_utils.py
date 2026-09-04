from __future__ import annotations

import json

SSE_HEARTBEAT_SECONDS = 15
SSE_POLL_INTERVAL_SECONDS = 1.0
SSE_MAX_CONNECTION_MINUTES = 30

def format_sse(data:dict, event:str, event_id:str | None = None) -> str:
    lines = [f"event: {event}", f"data: {json.dumps(data, ensure_ascii=False)}"] #json convert panrom
    if event_id is not None:
        lines.append(f"id: {event_id}") #id oruvela vandhuchuna adhayum sethuko if none vitru
    lines.append("") #SSE format, a blank line marks the end of one message.
    return "\n".join(lines) + "\n" #complicated. revisit

def format_heartbeat() -> str:
    return ":heartbeat:\n\n" #anyting after : is comment in sse
    