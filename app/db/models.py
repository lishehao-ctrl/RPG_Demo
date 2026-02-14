import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import GUID, JSONType


def utcnow() -> datetime:
    return datetime.utcnow()


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    google_sub: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    current_node_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    global_flags: Mapped[dict] = mapped_column(JSONType, default=dict)
    route_flags: Mapped[dict] = mapped_column(JSONType, default=dict)
    active_characters: Mapped[list] = mapped_column(JSONType, default=list)
    memory_summary: Mapped[str] = mapped_column(Text, default="")
    token_budget_used: Mapped[int] = mapped_column(Integer, default=0)
    token_budget_remaining: Mapped[int] = mapped_column(Integer, default=0)
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


class DialogueNode(Base):
    __tablename__ = "dialogue_nodes"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("sessions.id"), index=True)
    parent_node_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("dialogue_nodes.id"), nullable=True, index=True)
    node_type: Mapped[str] = mapped_column(String(32), default="ai", index=True)
    player_input: Mapped[str | None] = mapped_column(Text, nullable=True)
    narrative_text: Mapped[str] = mapped_column(Text, default="")
    choices: Mapped[list] = mapped_column(JSONType, default=list)
    branch_decision: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class Branch(Base):
    __tablename__ = "branches"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    from_node_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("dialogue_nodes.id"), index=True)
    to_node_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("dialogue_nodes.id"), nullable=True, index=True)
    priority: Mapped[int] = mapped_column(Integer, default=0, index=True)
    is_exclusive: Mapped[bool] = mapped_column(Boolean, default=False)
    rule_expr: Mapped[dict] = mapped_column(JSONType, default=dict)
    route_type: Mapped[str] = mapped_column(String(64), default="default", index=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class ActionLog(Base):
    __tablename__ = "action_logs"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("sessions.id"), index=True)
    node_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("dialogue_nodes.id"), nullable=True, index=True)
    player_input: Mapped[str] = mapped_column(Text, default="")
    classification: Mapped[dict] = mapped_column(JSONType, default=dict)
    matched_rules: Mapped[list] = mapped_column(JSONType, default=list)
    affection_delta: Mapped[list] = mapped_column(JSONType, default=list)
    branch_evaluation: Mapped[list] = mapped_column(JSONType, default=list)
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


class LLMUsageLog(Base):
    __tablename__ = "llm_usage_logs"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("sessions.id"), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(64), index=True)
    operation: Mapped[str] = mapped_column(String(64), index=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), index=True)
    cost_estimate: Mapped[float] = mapped_column(Numeric(10, 4), default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("sessions.id"), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


Index("ix_dialogue_nodes_parent_created", DialogueNode.parent_node_id, DialogueNode.created_at)
