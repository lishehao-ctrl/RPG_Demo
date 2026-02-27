from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from app.config import settings
from app.db.bootstrap import init_db
from app.modules.debug.router import router as debug_router
from app.modules.play_ui.router import router as play_ui_router
from app.modules.runtime.router import router as runtime_router
from app.modules.story_domain.router import router as story_router
from app.modules.telemetry.router import router as telemetry_router


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, lifespan=lifespan)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    app.include_router(story_router)
    app.include_router(runtime_router)
    app.include_router(telemetry_router)
    app.include_router(debug_router)
    app.include_router(play_ui_router)
    return app


app = create_app()
