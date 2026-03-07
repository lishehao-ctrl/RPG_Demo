from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class AdminUserView:
    id: str
    email: str
    role: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None = None


@dataclass(frozen=True)
class AdminSessionTimelineEventView:
    event_id: str
    turn_index: int
    event_type: str
    payload: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True)
class AdminSessionTimelineView:
    session_id: str
    events: tuple[AdminSessionTimelineEventView, ...]


@dataclass(frozen=True)
class SessionFeedbackView:
    feedback_id: str
    session_id: str
    story_id: str
    version: int
    verdict: str
    reason_tags: tuple[str, ...]
    note: str | None
    turn_index: int | None
    created_at: datetime


@dataclass(frozen=True)
class SessionFeedbackListView:
    session_id: str
    items: tuple[SessionFeedbackView, ...]
