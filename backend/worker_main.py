
import sys

sys.path.insert(0, "package") #innum figureout pannala

from typing import ClassVar

from vazhi.services.run_worker import execute_agent_run
from vazhi.storage.redis import get_arq_redis_settings


class WorkerSettings:
    functions: ClassVar[list] = [execute_agent_run]
    redis_settings = get_arq_redis_settings()

