from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, RedirectResponse

from app.config import settings

STATIC_DIR = Path(__file__).resolve().parent / "static"
DEV_INDEX_PATH = STATIC_DIR / "index.dev.html"
PLAY_INDEX_PATH = STATIC_DIR / "index.play.html"

router = APIRouter(tags=["demo"])


@router.get("/demo")
def demo_page():
    return RedirectResponse(url="/demo/play", status_code=307)


@router.get("/demo/dev")
def demo_page_dev():
    return FileResponse(DEV_INDEX_PATH, media_type="text/html")


@router.get("/demo/play")
def demo_page_play():
    return FileResponse(PLAY_INDEX_PATH, media_type="text/html")


@router.get("/demo/bootstrap")
def demo_bootstrap():
    return {
        "default_story_id": settings.demo_default_story_id,
        "default_story_version": settings.demo_default_story_version,
        "step_retry_max_attempts": max(1, int(settings.demo_step_retry_max_attempts)),
        "step_retry_backoff_ms": max(1, int(settings.demo_step_retry_backoff_ms)),
    }
