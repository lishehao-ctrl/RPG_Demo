from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import ensure_dev_database_schema, settings
from app.db import session as db_session
from app.modules.demo.router import STATIC_DIR as DEMO_STATIC_DIR
from app.modules.demo.router import router as demo_router
from app.modules.session.router import router as session_router
from app.modules.story.router import router as story_router

app = FastAPI(title="RPG Demo Backend")
app.mount("/demo/static", StaticFiles(directory=str(DEMO_STATIC_DIR)), name="demo_static")


@app.on_event("startup")
def validate_security_settings() -> None:
    if settings.env == "dev":
        ensure_dev_database_schema(str(db_session.engine.url))


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(session_router)
app.include_router(story_router)
app.include_router(demo_router)
