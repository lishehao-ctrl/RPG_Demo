from __future__ import annotations

from fastapi import FastAPI

from rpg_backend.api.admin_auth import router as admin_auth_router
from rpg_backend.api.admin_observability import router as admin_observability_router
from rpg_backend.api.admin_sessions import router as admin_sessions_router
from rpg_backend.api.admin_users import router as admin_users_router
from rpg_backend.api.health import router as health_router
from rpg_backend.api.sessions import router as sessions_router
from rpg_backend.api.stories import router as stories_router


def register_routers(app: FastAPI) -> None:
    app.include_router(health_router)
    app.include_router(admin_auth_router)
    app.include_router(stories_router)
    app.include_router(sessions_router)
    app.include_router(admin_sessions_router)
    app.include_router(admin_observability_router)
    app.include_router(admin_users_router)
