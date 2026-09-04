import sys

from fastapi import FastAPI

sys.path.insert(0, "package")

from server.routers import agent_router, system_router

app = FastAPI()

app.include_router(system_router.router)
app.include_router(agent_router.router)

