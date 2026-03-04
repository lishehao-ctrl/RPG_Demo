from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Story(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    title: str
    draft_pack_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(default_factory=utc_now, nullable=False)


class StoryVersion(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("story_id", "version", name="uq_story_version"),)

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    story_id: str = Field(index=True, foreign_key="story.id")
    version: int = Field(index=True)
    status: str = Field(default="published")
    pack_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(default_factory=utc_now, nullable=False)


class Session(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    story_id: str = Field(index=True, foreign_key="story.id")
    version: int = Field(index=True)
    current_scene_id: str
    beat_index: int = 0
    beat_progress_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    state_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    ended: bool = False
    turn_count: int = 0
    created_at: datetime = Field(default_factory=utc_now, nullable=False)
    updated_at: datetime = Field(default_factory=utc_now, nullable=False)


class SessionAction(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("session_id", "client_action_id", name="uq_session_action"),)

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    session_id: str = Field(index=True, foreign_key="session.id")
    client_action_id: str = Field(index=True)
    request_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    response_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(default_factory=utc_now, nullable=False)


class RuntimeEvent(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    session_id: str = Field(index=True, foreign_key="session.id")
    turn_index: int
    event_type: str
    payload_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(default_factory=utc_now, nullable=False)


class HttpRequestEvent(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    service: str = Field(index=True)
    method: str = Field(index=True)
    path: str = Field(index=True)
    status_code: int = Field(index=True)
    duration_ms: int = Field(ge=0)
    request_id: str | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utc_now, index=True, nullable=False)


class LLMCallEvent(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    session_id: str | None = Field(default=None, index=True, foreign_key="session.id")
    turn_index: int | None = Field(default=None)
    stage: str = Field(index=True)
    gateway_mode: str = Field(index=True)
    model: str = Field(index=True)
    success: bool = Field(index=True)
    error_code: str | None = Field(default=None, index=True)
    duration_ms: int = Field(ge=0)
    request_id: str | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utc_now, index=True, nullable=False)


class ReadinessProbeEvent(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    service: str = Field(index=True)
    ok: bool = Field(index=True)
    error_code: str | None = Field(default=None, index=True)
    latency_ms: int | None = Field(default=None)
    request_id: str | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utc_now, index=True, nullable=False)


class SessionFeedback(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    session_id: str = Field(index=True, foreign_key="session.id")
    story_id: str = Field(index=True, foreign_key="story.id")
    version: int = Field(index=True)
    turn_index: int | None = None
    verdict: str
    reason_tags_json: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    note: str | None = None
    created_at: datetime = Field(default_factory=utc_now, nullable=False)


class RuntimeAlertDispatch(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    bucket_key: str = Field(index=True)
    window_started_at: datetime = Field(index=True, nullable=False)
    window_ended_at: datetime = Field(index=True, nullable=False)
    sent_at: datetime = Field(default_factory=utc_now, index=True, nullable=False)
    status: str
    payload_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
