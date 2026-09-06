from __future__ import annotations

import operator
from typing import Annotated, Any

from langchain.agents.middleware.types import AgentState


class VazhiAgentState(AgentState):
    subagent_runs: Annotated[list[dict[str, Any]], operator.add]
