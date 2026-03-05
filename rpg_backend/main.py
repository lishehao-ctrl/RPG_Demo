from contextlib import asynccontextmanager

from fastapi import FastAPI

from rpg_backend.api.errors import register_error_handlers
from rpg_backend.api.router_registry import register_routers
from rpg_backend.llm.worker_client import close_worker_client_cache
from rpg_backend.observability.logging import configure_logging
from rpg_backend.security.bootstrap import (
    assert_production_secret_requirements,
    ensure_bootstrap_admin,
)
from rpg_backend.observability.middleware import RequestIdMiddleware
from rpg_backend.storage.migrations import assert_schema_current


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    assert_schema_current()
    assert_production_secret_requirements()
    await ensure_bootstrap_admin()
    try:
        yield
    finally:
        await close_worker_client_cache()


app = FastAPI(title="RPG Backend API", lifespan=lifespan)
app.add_middleware(RequestIdMiddleware, service_name="backend")
register_error_handlers(app)
register_routers(app)
