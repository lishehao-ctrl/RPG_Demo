from __future__ import annotations

from fastapi import APIRouter, Depends

from app.modules.auth.deps import require_author_token
from app.modules.telemetry.service import get_runtime_telemetry_summary

router = APIRouter(prefix="/api/v1/telemetry", tags=["telemetry"])


@router.get("/runtime")
def runtime_telemetry(_: str | None = Depends(require_author_token)) -> dict:
    return get_runtime_telemetry_summary()
