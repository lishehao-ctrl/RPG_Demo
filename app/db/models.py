import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import GUID, JSONType


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    story_node_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    story_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    story_version: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    global_flags: Mapped[dict] = mapped_column(JSONType, default=dict)
    active_characters: Mapped[list] = mapped_column(JSONType, default=list)
    state_json: Mapped[dict] = mapped_column(JSONType, default=dict)
    memory_summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, index=True)


class SessionSnapshot(Base):
    __tablename__ = "session_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("sessions.id"), index=True)
    snapshot_name: Mapped[str] = mapped_column(String(100), default="manual")
    state_blob: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class Character(Base):
    __tablename__ = "characters"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), index=True)
    base_personality: Mapped[dict] = mapped_column(JSONType, default=dict)
    initial_relation_vector: Mapped[dict] = mapped_column(JSONType, default=dict)
    initial_visible_score: Mapped[int] = mapped_column(Integer, default=50)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class SessionCharacterState(Base):
    __tablename__ = "session_character_state"
    __table_args__ = (
        UniqueConstraint("session_id", "character_id", name="uq_session_character_state_session_character"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("sessions.id"), index=True)
    character_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("characters.id"), index=True)
    score_visible: Mapped[int] = mapped_column(Integer, default=50)
    relation_vector: Mapped[dict] = mapped_column(JSONType, default=dict)
    personality_drift: Mapped[dict] = mapped_column(JSONType, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, index=True)


class ActionLog(Base):
    __tablename__ = "action_logs"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("sessions.id"), index=True)
    story_node_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    story_choice_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    player_input: Mapped[str] = mapped_column(Text, default="")
    user_raw_input: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposed_action: Mapped[dict] = mapped_column(JSONType, default=dict)
    final_action: Mapped[dict] = mapped_column(JSONType, default=dict)
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False)
    fallback_reasons: Mapped[list] = mapped_column(JSONType, default=list)
    action_confidence: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)
    key_decision: Mapped[bool] = mapped_column(Boolean, default=False)
    classification: Mapped[dict] = mapped_column(JSONType, default=dict)
    state_before: Mapped[dict] = mapped_column(JSONType, default=dict)
    state_after: Mapped[dict] = mapped_column(JSONType, default=dict)
    state_delta: Mapped[dict] = mapped_column(JSONType, default=dict)
    matched_rules: Mapped[list] = mapped_column(JSONType, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class Story(Base):
    __tablename__ = "stories"
    __table_args__ = (
        UniqueConstraint("story_id", "version", name="uq_stories_story_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    story_id: Mapped[str] = mapped_column(String(128), index=True)
    version: Mapped[int] = mapped_column(Integer, index=True)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    pack_json: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class ReplayReport(Base):
    __tablename__ = "replay_reports"
    __table_args__ = (
        UniqueConstraint("session_id", name="uq_replay_reports_session_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("sessions.id"), index=True)
    report_json: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class SessionStepIdempotency(Base):
    __tablename__ = "session_step_idempotency"
    __table_args__ = (
        UniqueConstraint("session_id", "idempotency_key", name="uq_session_step_idempotency_session_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("sessions.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), index=True)
    request_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    response_json: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
