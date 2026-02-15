from fastapi import FastAPI

from app.config import settings
from app.modules.auth.router import router as auth_router
from app.modules.session.router import router as session_router
from app.modules.webdemo.router import router as webdemo_router

app = FastAPI(title="RPG Demo Backend")


@app.on_event("startup")
def validate_security_settings() -> None:
    if settings.env != "dev" and settings.jwt_secret == "change-me-in-prod":
        raise RuntimeError("JWT_SECRET must be set to a non-default value when env != dev")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(auth_router)
app.include_router(session_router)
app.include_router(webdemo_router)
