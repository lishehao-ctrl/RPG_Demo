from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlmodel.ext.asyncio.session import AsyncSession

from rpg_backend.api.contracts.admin import AdminSessionTimelineEvent, AdminSessionTimelineResponse
from rpg_backend.api.contracts.sessions import SessionFeedbackCreateRequest, SessionFeedbackItem, SessionFeedbackListResponse
from rpg_backend.api.error_mapping import api_error_from_application_error
from rpg_backend.api.route_paths import API_ADMIN_SESSIONS_PREFIX
from rpg_backend.application.admin_console.service import (
    create_session_feedback_view,
    get_session_timeline_view,
    list_session_feedback_views,
)
from rpg_backend.application.errors import ApplicationError
from rpg_backend.infrastructure.db.async_session import get_async_session
from rpg_backend.observability.context import get_request_id
from rpg_backend.security.deps import require_admin

router = APIRouter(
    prefix=API_ADMIN_SESSIONS_PREFIX,
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


@router.get("/{session_id}/timeline", response_model=AdminSessionTimelineResponse)
async def get_session_timeline_endpoint(
    session_id: str,
    limit: int = Query(default=200, ge=1, le=1000),
    order: Literal["asc", "desc"] = Query(default="asc"),
    event_type: str | None = Query(default=None),
    db: AsyncSession = Depends(get_async_session),
) -> AdminSessionTimelineResponse:
    try:
        view = await get_session_timeline_view(
            db=db,
            session_id=session_id,
            limit=limit,
            order=order,
            event_type=event_type,
        )
    except ApplicationError as exc:
        raise api_error_from_application_error(exc) from exc
    return AdminSessionTimelineResponse(
        session_id=view.session_id,
        events=[
            AdminSessionTimelineEvent(
                event_id=item.event_id,
                turn_index=item.turn_index,
                event_type=item.event_type,
                payload=item.payload,
                created_at=item.created_at,
            )
            for item in view.events
        ],
    )


@router.post("/{session_id}/feedback", response_model=SessionFeedbackItem)
async def create_session_feedback_endpoint(
    session_id: str,
    payload: SessionFeedbackCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
) -> SessionFeedbackItem:
    request_id = getattr(request.state, "request_id", None) or get_request_id()
    try:
        item = await create_session_feedback_view(
            db=db,
            session_id=session_id,
            verdict=payload.verdict,
            reason_tags=list(payload.reason_tags),
            note=payload.note,
            turn_index=payload.turn_index,
            request_id=request_id,
        )
    except ApplicationError as exc:
        raise api_error_from_application_error(exc) from exc
    return SessionFeedbackItem(
        feedback_id=item.feedback_id,
        session_id=item.session_id,
        story_id=item.story_id,
        version=item.version,
        verdict=item.verdict,
        reason_tags=list(item.reason_tags),
        note=item.note,
        turn_index=item.turn_index,
        created_at=item.created_at,
    )


@router.get("/{session_id}/feedback", response_model=SessionFeedbackListResponse)
async def list_session_feedback_endpoint(
    session_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_async_session),
) -> SessionFeedbackListResponse:
    try:
        view = await list_session_feedback_views(db=db, session_id=session_id, limit=limit)
    except ApplicationError as exc:
        raise api_error_from_application_error(exc) from exc
    return SessionFeedbackListResponse(
        session_id=view.session_id,
        items=[
            SessionFeedbackItem(
                feedback_id=item.feedback_id,
                session_id=item.session_id,
                story_id=item.story_id,
                version=item.version,
                verdict=item.verdict,
                reason_tags=list(item.reason_tags),
                note=item.note,
                turn_index=item.turn_index,
                created_at=item.created_at,
            )
            for item in view.items
        ],
    )
