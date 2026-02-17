from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

STATIC_DIR = Path(__file__).resolve().parent / "static"
INDEX_PATH = STATIC_DIR / "index.html"

router = APIRouter(tags=["demo"])


@router.get("/demo")
def demo_page():
    return FileResponse(INDEX_PATH, media_type="text/html")
