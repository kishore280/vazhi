from __future__ import annotations

import hashlib
import time
import uuid


def hashstr(input_string: object, length: int | None = None, with_salt: bool = False, salt: str | None = None) -> str:
    try:
        encoded_string = str(input_string).encode("utf-8")
    except UnicodeEncodeError:
        encoded_string = str(input_string).encode("utf-8", errors="replace")

    if with_salt:
        if not salt:
            salt = f"{time.time()}_{uuid.uuid4().hex[:8]}"
        encoded_string = (encoded_string.decode("utf-8") + salt).encode("utf-8")

    digest = hashlib.sha256(encoded_string).hexdigest()
    if length:
        return digest[:length]
    return digest


def hash_id(prefix: str, value: object, length: int = 48) -> str:
    digest_length = max(0, length - len(prefix))
    digest = hashstr(value, length=digest_length) if digest_length else ""
    return f"{prefix}{digest}"


def subagent_child_thread_id(parent_thread_id: str, agent_slug: str, tool_call_id: str) -> str:
    return hash_id("subagent_", f"{parent_thread_id}:{agent_slug}:{tool_call_id}", length=64)
