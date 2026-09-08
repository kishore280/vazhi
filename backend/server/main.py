import logging
import sys
from contextlib import asynccontextmanager

sys.path.insert(0, "package")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from vazhi.storage.postgres.manager import get_postgres_manager

from server.routers import agent_router, attachment_router, system_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    manager = get_postgres_manager()
    await manager.require_current_schema()
    await manager.setup_langgraph_checkpointer()
    logger.info("Schema verified, API ready")
    yield
    if manager.langgraph_pool is not None:
        await manager.langgraph_pool.close()


app = FastAPI(title="Vazhi", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(system_router.router)
app.include_router(agent_router.router)
app.include_router(attachment_router.router)
