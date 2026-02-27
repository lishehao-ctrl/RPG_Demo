from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.db.session import get_db
from app.modules.auth.deps import require_author_token
from app.modules.auth.identity import resolve_token_user_id
from app.modules.debug.schemas import (
    DebugBundleIncludeFlagsOut,
    DebugSessionListResponse,
    DebugSessionBundleOut,
    DebugSessionOverviewOut,
    DebugStepDetailOut,
    DebugTimelineResponse,
)
from app.modules.debug.service import (
    get_debug_session_bundle,
    get_debug_session_overview,
    get_debug_step_detail,
    get_debug_timeline,
    list_debug_sessions,
)
from app.modules.runtime.service import RuntimeNotFoundError

router = APIRouter(prefix="/api/v1/debug", tags=["debug"])


def _actor_user_id(*, author_token: str | None) -> str | None:
    cleaned = str(author_token or "").strip()
    if not cleaned:
        return None

    with SessionLocal() as identity_db:
        user_id = resolve_token_user_id(identity_db, token=cleaned, role="author")
        identity_db.commit()
        return user_id


def _parse_include_flags(include: str | None) -> DebugBundleIncludeFlagsOut:
    if not include or not include.strip():
        return DebugBundleIncludeFlagsOut(telemetry=True, versions=True, latest_step_detail=True)

    parts = {item.strip() for item in include.split(",") if item.strip()}
    allowed = {"telemetry", "versions", "latest_step_detail"}
    unknown = parts - allowed
    if unknown:
        bad = ", ".join(sorted(unknown))
        raise ValueError(f"unsupported include values: {bad}")

    return DebugBundleIncludeFlagsOut(
        telemetry="telemetry" in parts,
        versions="versions" in parts,
        latest_step_detail="latest_step_detail" in parts,
    )


@router.get("/sessions", response_model=DebugSessionListResponse)
def list_sessions(
    story_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: str | None = Depends(require_author_token),
) -> DebugSessionListResponse:
    return list_debug_sessions(db, story_id=story_id, status=status, limit=limit, offset=offset)


@router.get("/sessions/{session_id}/bundle", response_model=DebugSessionBundleOut)
def session_bundle(
    session_id: str,
    timeline_limit: int = Query(default=50, ge=1, le=200),
    timeline_offset: int = Query(default=0, ge=0),
    include: str | None = Query(default=None),
    db: Session = Depends(get_db),
    author_token: str | None = Depends(require_author_token),
) -> DebugSessionBundleOut:
    try:
        include_flags = _parse_include_flags(include)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "BAD_REQUEST", "message": str(exc)}) from exc

    actor_user_id = _actor_user_id(author_token=author_token)
    try:
        return get_debug_session_bundle(
            db,
            session_id=session_id,
            timeline_limit=timeline_limit,
            timeline_offset=timeline_offset,
            include_flags=include_flags,
            actor_user_id=actor_user_id,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": str(exc)}) from exc
    except (RuntimeNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}) from exc


@router.get("/sessions/{session_id}/overview", response_model=DebugSessionOverviewOut)
def session_overview(
    session_id: str,
    db: Session = Depends(get_db),
    _: str | None = Depends(require_author_token),
) -> DebugSessionOverviewOut:
    try:
        return get_debug_session_overview(db, session_id=session_id)
    except RuntimeNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}) from exc


@router.get("/sessions/{session_id}/timeline", response_model=DebugTimelineResponse)
def session_timeline(
    session_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: str | None = Depends(require_author_token),
) -> DebugTimelineResponse:
    try:
        return get_debug_timeline(db, session_id=session_id, limit=limit, offset=offset)
    except RuntimeNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}) from exc


@router.get("/sessions/{session_id}/steps/{step_index}", response_model=DebugStepDetailOut)
def step_detail(
    session_id: str,
    step_index: int,
    db: Session = Depends(get_db),
    _: str | None = Depends(require_author_token),
) -> DebugStepDetailOut:
    try:
        return get_debug_step_detail(db, session_id=session_id, step_index=step_index)
    except RuntimeNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}) from exc
