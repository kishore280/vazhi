from __future__ import annotations

from dataclasses import dataclass

DEFAULT_SUMMARY_THRESHOLD_K = 100
DEFAULT_SUMMARY_KEEP_MESSAGES = 10
DEFAULT_SUMMARY_TOOL_RESULT_TOKEN_LIMIT = 300
DEFAULT_SUMMARY_L2_TRIGGER_RATIO = 0.4
DEFAULT_VAZHI_SUMMARY_PROMPT = """You are a conversation context compression assistant.
Your task is to compress the conversation history below into the high-value context a
continuing agent needs to keep working.

Preserve and clearly record, in particular:

## SESSION INTENT
The user's current main goal, task scope, and final deliverable.

## USER REQUIREMENTS AND PREFERENCES
Requirements, preferences, things to avoid, output format, language style, technical
constraints, and acceptance criteria the user explicitly stated, plus any tradeoffs they
expressed about implementation approach. Only record what could still affect later
answers or execution.

## PROGRESS AND DECISIONS
Steps already completed, key conclusions, confirmed approaches, and rejected approaches
with their reasons.

## ARTIFACTS AND REFERENCES
Files, paths, tool output paths, thread or run identifiers already created, modified,
read, or still worth tracking. Keep concrete paths and key identifiers.

## NEXT STEPS
The concrete next steps most worth taking to reach the user's goal. Write None if there
is nothing pending.

Requirements:
- Don't recite lengthy tool output verbatim; keep conclusions, paths, and necessary evidence.
- Don't invent facts that didn't appear in the conversation.
- If there are unresolved questions or risks, record them explicitly.
- Use the same language as the user's main conversation.

<messages>
{messages}
</messages>

Output only the compressed context, with no extra commentary."""


@dataclass
class VazhiContext:
    run_id: str | None = None
    thread_id: str | None = None
    uid: str | None = None
    request_id: str | None = None
    worker_id: str | None = None
    tools: list[str] | None = None
    mcps: list[str] | None = None
    summary_threshold: int = DEFAULT_SUMMARY_THRESHOLD_K
    summary_keep_messages: int = DEFAULT_SUMMARY_KEEP_MESSAGES
    summary_prompt: str | None = None
    summary_tool_result_token_limit: int = DEFAULT_SUMMARY_TOOL_RESULT_TOKEN_LIMIT
    summary_l2_trigger_ratio: float = DEFAULT_SUMMARY_L2_TRIGGER_RATIO
    tool_approval_mode: str | None = None
