from contextlib import asynccontextmanager

from fastapi import FastAPI

from rpg_backend.api.admin_sessions import observability_router as admin_observability_router
from rpg_backend.api.admin_sessions import router as admin_sessions_router
from rpg_backend.api.health import router as health_router
from rpg_backend.api.sessions import router as sessions_router
from rpg_backend.api.stories import router as stories_router
from rpg_backend.observability.logging import configure_logging
from rpg_backend.observability.middleware import RequestIdMiddleware
from rpg_backend.storage.engine import init_db


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    init_db()
    yield


app = FastAPI(title="RPG Backend API", lifespan=lifespan)
app.add_middleware(RequestIdMiddleware)
app.include_router(health_router)
app.include_router(stories_router)
app.include_router(sessions_router)
app.include_router(admin_sessions_router)
app.include_router(admin_observability_router)
