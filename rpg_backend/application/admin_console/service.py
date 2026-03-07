from __future__ import annotations

from typing import Literal

from rpg_backend.application.admin_console.models import (
    AdminSessionTimelineEventView,
    AdminSessionTimelineView,
    AdminUserView,
    SessionFeedbackListView,
    SessionFeedbackView,
)
from rpg_backend.application.admin_console.errors import AdminUserNotFoundError
from rpg_backend.application.play_sessions.errors import SessionNotFoundError
from rpg_backend.infrastructure.db.transaction import transactional
from rpg_backend.infrastructure.repositories.admin_users_async import get_admin_user_by_id, list_admin_users
from rpg_backend.infrastructure.repositories.runtime_events_async import list_runtime_events
from rpg_backend.infrastructure.repositories.session_feedback_async import create_session_feedback, list_session_feedback
from rpg_backend.infrastructure.repositories.sessions_async import get_session as get_session_record
from rpg_backend.observability.context import get_request_id
from rpg_backend.observability.logging import log_event


async def _require_session(db, session_id: str):
    session = await get_session_record(db, session_id)
    if session is None:
        raise SessionNotFoundError(session_id=session_id)
    return session


async def list_admin_user_views(*, db, limit: int) -> list[AdminUserView]:
    users = await list_admin_users(db, limit=limit)
    return [
        AdminUserView(
            id=user.id,
            email=user.email,
            role=user.role,
            is_active=bool(user.is_active),
            created_at=user.created_at,
            updated_at=user.updated_at,
            last_login_at=user.last_login_at,
        )
        for user in users
    ]


async def get_admin_user_view(*, db, user_id: str) -> AdminUserView:
    user = await get_admin_user_by_id(db, user_id)
    if user is None:
        raise AdminUserNotFoundError(user_id=user_id)
    return AdminUserView(
        id=user.id,
        email=user.email,
        role=user.role,
        is_active=bool(user.is_active),
        created_at=user.created_at,
        updated_at=user.updated_at,
        last_login_at=user.last_login_at,
    )


async def get_session_timeline_view(
    *,
    db,
    session_id: str,
    limit: int,
    order: Literal["asc", "desc"],
    event_type: str | None,
) -> AdminSessionTimelineView:
    await _require_session(db, session_id)
    events = await list_runtime_events(
        db,
        session_id=session_id,
        limit=limit,
        order=order,
        event_type=event_type,
    )
    return AdminSessionTimelineView(
        session_id=session_id,
        events=tuple(
            AdminSessionTimelineEventView(
                event_id=event.id,
                turn_index=event.turn_index,
                event_type=event.event_type,
                payload=event.payload_json,
                created_at=event.created_at,
            )
            for event in events
        ),
    )


async def create_session_feedback_view(
    *,
    db,
    session_id: str,
    verdict: str,
    reason_tags: list[str],
    note: str | None,
    turn_index: int | None,
    request_id: str | None = None,
) -> SessionFeedbackView:
    session = await _require_session(db, session_id)
    current_request_id = request_id or get_request_id()
    async with transactional(db):
        feedback = await create_session_feedback(
            db,
            session_id=session.id,
            story_id=session.story_id,
            version=session.version,
            verdict=verdict,
            reason_tags=list(reason_tags),
            note=note,
            turn_index=turn_index,
        )
    log_event(
        "admin_feedback_created",
        level="INFO",
        request_id=current_request_id,
        session_id=session.id,
        story_id=session.story_id,
        version=session.version,
        verdict=verdict,
        reason_tags_count=len(reason_tags),
        turn_index=turn_index,
    )
    return SessionFeedbackView(
        feedback_id=feedback.id,
        session_id=feedback.session_id,
        story_id=feedback.story_id,
        version=feedback.version,
        verdict=feedback.verdict,
        reason_tags=tuple(feedback.reason_tags_json),
        note=feedback.note,
        turn_index=feedback.turn_index,
        created_at=feedback.created_at,
    )


async def list_session_feedback_views(*, db, session_id: str, limit: int) -> SessionFeedbackListView:
    await _require_session(db, session_id)
    items = await list_session_feedback(db, session_id=session_id, limit=limit)
    return SessionFeedbackListView(
        session_id=session_id,
        items=tuple(
            SessionFeedbackView(
                feedback_id=item.id,
                session_id=item.session_id,
                story_id=item.story_id,
                version=item.version,
                verdict=item.verdict,
                reason_tags=tuple(item.reason_tags_json),
                note=item.note,
                turn_index=item.turn_index,
                created_at=item.created_at,
            )
            for item in items
        ),
    )
