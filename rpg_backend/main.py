from contextlib import asynccontextmanager

from fastapi import FastAPI

from rpg_backend.api.errors import register_error_handlers
from rpg_backend.api.router_registry import register_routers
from rpg_backend.observability.logging import configure_logging
from rpg_backend.observability.middleware import RequestIdMiddleware
from rpg_backend.storage.engine import init_db


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    init_db()
    yield


app = FastAPI(title="RPG Backend API", lifespan=lifespan)
app.add_middleware(RequestIdMiddleware, service_name="backend")
register_error_handlers(app)
register_routers(app)
