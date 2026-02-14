"""init full schema

Revision ID: 0001_init
Revises:
Create Date: 2026-02-13 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.db.types import GUID, JSONType

# revision identifiers, used by Alembic.
revision: str = "0001_init"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", GUID(), primary_key=True, nullable=False),
        sa.Column("google_sub", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_users_google_sub", "users", ["google_sub"], unique=True)
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_created_at", "users", ["created_at"], unique=False)

    op.create_table(
        "characters",
        sa.Column("id", GUID(), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("base_personality", JSONType, nullable=False),
        sa.Column("initial_relation_vector", JSONType, nullable=False),
        sa.Column("initial_visible_score", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_characters_name", "characters", ["name"], unique=False)
    op.create_index("ix_characters_created_at", "characters", ["created_at"], unique=False)

    op.create_table(
        "sessions",
        sa.Column("id", GUID(), primary_key=True, nullable=False),
        sa.Column("user_id", GUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("current_node_id", GUID(), nullable=True),
        sa.Column("global_flags", JSONType, nullable=False),
        sa.Column("route_flags", JSONType, nullable=False),
        sa.Column("active_characters", JSONType, nullable=False),
        sa.Column("memory_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("token_budget_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("token_budget_remaining", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"], unique=False)
    op.create_index("ix_sessions_status", "sessions", ["status"], unique=False)
    op.create_index("ix_sessions_current_node_id", "sessions", ["current_node_id"], unique=False)
    op.create_index("ix_sessions_created_at", "sessions", ["created_at"], unique=False)
    op.create_index("ix_sessions_updated_at", "sessions", ["updated_at"], unique=False)

    op.create_table(
        "dialogue_nodes",
        sa.Column("id", GUID(), primary_key=True, nullable=False),
        sa.Column("session_id", GUID(), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("parent_node_id", GUID(), sa.ForeignKey("dialogue_nodes.id"), nullable=True),
        sa.Column("node_type", sa.String(length=32), nullable=False, server_default="ai"),
        sa.Column("player_input", sa.Text(), nullable=True),
        sa.Column("narrative_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("choices", JSONType, nullable=False),
        sa.Column("branch_decision", JSONType, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_dialogue_nodes_session_id", "dialogue_nodes", ["session_id"], unique=False)
    op.create_index("ix_dialogue_nodes_parent_node_id", "dialogue_nodes", ["parent_node_id"], unique=False)
    op.create_index("ix_dialogue_nodes_node_type", "dialogue_nodes", ["node_type"], unique=False)
    op.create_index("ix_dialogue_nodes_created_at", "dialogue_nodes", ["created_at"], unique=False)
    op.create_index("ix_dialogue_nodes_parent_created", "dialogue_nodes", ["parent_node_id", "created_at"], unique=False)

    op.create_table(
        "session_snapshots",
        sa.Column("id", GUID(), primary_key=True, nullable=False),
        sa.Column("session_id", GUID(), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("snapshot_name", sa.String(length=100), nullable=False, server_default="manual"),
        sa.Column("state_blob", JSONType, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_session_snapshots_session_id", "session_snapshots", ["session_id"], unique=False)
    op.create_index("ix_session_snapshots_created_at", "session_snapshots", ["created_at"], unique=False)

    op.create_table(
        "session_character_state",
        sa.Column("id", GUID(), primary_key=True, nullable=False),
        sa.Column("session_id", GUID(), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("character_id", GUID(), sa.ForeignKey("characters.id"), nullable=False),
        sa.Column("score_visible", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("relation_vector", JSONType, nullable=False),
        sa.Column("personality_drift", JSONType, nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("session_id", "character_id", name="uq_session_character_state_session_character"),
    )
    op.create_index("ix_session_character_state_session_id", "session_character_state", ["session_id"], unique=False)
    op.create_index("ix_session_character_state_character_id", "session_character_state", ["character_id"], unique=False)
    op.create_index("ix_session_character_state_updated_at", "session_character_state", ["updated_at"], unique=False)

    op.create_table(
        "branches",
        sa.Column("id", GUID(), primary_key=True, nullable=False),
        sa.Column("from_node_id", GUID(), sa.ForeignKey("dialogue_nodes.id"), nullable=False),
        sa.Column("to_node_id", GUID(), sa.ForeignKey("dialogue_nodes.id"), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_exclusive", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("rule_expr", JSONType, nullable=False),
        sa.Column("route_type", sa.String(length=64), nullable=False, server_default="default"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_branches_from_node_id", "branches", ["from_node_id"], unique=False)
    op.create_index("ix_branches_to_node_id", "branches", ["to_node_id"], unique=False)
    op.create_index("ix_branches_priority", "branches", ["priority"], unique=False)
    op.create_index("ix_branches_route_type", "branches", ["route_type"], unique=False)
    op.create_index("ix_branches_created_at", "branches", ["created_at"], unique=False)

    op.create_table(
        "action_logs",
        sa.Column("id", GUID(), primary_key=True, nullable=False),
        sa.Column("session_id", GUID(), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("node_id", GUID(), sa.ForeignKey("dialogue_nodes.id"), nullable=True),
        sa.Column("player_input", sa.Text(), nullable=False, server_default=""),
        sa.Column("classification", JSONType, nullable=False),
        sa.Column("matched_rules", JSONType, nullable=False),
        sa.Column("affection_delta", JSONType, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_action_logs_session_id", "action_logs", ["session_id"], unique=False)
    op.create_index("ix_action_logs_node_id", "action_logs", ["node_id"], unique=False)
    op.create_index("ix_action_logs_created_at", "action_logs", ["created_at"], unique=False)

    op.create_table(
        "replay_reports",
        sa.Column("id", GUID(), primary_key=True, nullable=False),
        sa.Column("session_id", GUID(), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("report_json", JSONType, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("session_id", name="uq_replay_reports_session_id"),
    )
    op.create_index("ix_replay_reports_session_id", "replay_reports", ["session_id"], unique=True)
    op.create_index("ix_replay_reports_created_at", "replay_reports", ["created_at"], unique=False)

    op.create_table(
        "llm_usage_logs",
        sa.Column("id", GUID(), primary_key=True, nullable=False),
        sa.Column("session_id", GUID(), sa.ForeignKey("sessions.id"), nullable=True),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("cost_estimate", sa.Numeric(10, 4), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_llm_usage_logs_session_id", "llm_usage_logs", ["session_id"], unique=False)
    op.create_index("ix_llm_usage_logs_provider", "llm_usage_logs", ["provider"], unique=False)
    op.create_index("ix_llm_usage_logs_operation", "llm_usage_logs", ["operation"], unique=False)
    op.create_index("ix_llm_usage_logs_status", "llm_usage_logs", ["status"], unique=False)
    op.create_index("ix_llm_usage_logs_created_at", "llm_usage_logs", ["created_at"], unique=False)

    op.create_table(
        "audit_logs",
        sa.Column("id", GUID(), primary_key=True, nullable=False),
        sa.Column("session_id", GUID(), sa.ForeignKey("sessions.id"), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload", JSONType, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_audit_logs_session_id", "audit_logs", ["session_id"], unique=False)
    op.create_index("ix_audit_logs_event_type", "audit_logs", ["event_type"], unique=False)
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")
    op.drop_index("ix_audit_logs_event_type", table_name="audit_logs")
    op.drop_index("ix_audit_logs_session_id", table_name="audit_logs")
    op.drop_table("audit_logs")

    op.drop_index("ix_llm_usage_logs_created_at", table_name="llm_usage_logs")
    op.drop_index("ix_llm_usage_logs_status", table_name="llm_usage_logs")
    op.drop_index("ix_llm_usage_logs_operation", table_name="llm_usage_logs")
    op.drop_index("ix_llm_usage_logs_provider", table_name="llm_usage_logs")
    op.drop_index("ix_llm_usage_logs_session_id", table_name="llm_usage_logs")
    op.drop_table("llm_usage_logs")

    op.drop_index("ix_replay_reports_created_at", table_name="replay_reports")
    op.drop_index("ix_replay_reports_session_id", table_name="replay_reports")
    op.drop_table("replay_reports")

    op.drop_index("ix_action_logs_created_at", table_name="action_logs")
    op.drop_index("ix_action_logs_node_id", table_name="action_logs")
    op.drop_index("ix_action_logs_session_id", table_name="action_logs")
    op.drop_table("action_logs")

    op.drop_index("ix_branches_created_at", table_name="branches")
    op.drop_index("ix_branches_route_type", table_name="branches")
    op.drop_index("ix_branches_priority", table_name="branches")
    op.drop_index("ix_branches_to_node_id", table_name="branches")
    op.drop_index("ix_branches_from_node_id", table_name="branches")
    op.drop_table("branches")

    op.drop_index("ix_session_character_state_updated_at", table_name="session_character_state")
    op.drop_index("ix_session_character_state_character_id", table_name="session_character_state")
    op.drop_index("ix_session_character_state_session_id", table_name="session_character_state")
    op.drop_table("session_character_state")

    op.drop_index("ix_session_snapshots_created_at", table_name="session_snapshots")
    op.drop_index("ix_session_snapshots_session_id", table_name="session_snapshots")
    op.drop_table("session_snapshots")

    op.drop_index("ix_dialogue_nodes_parent_created", table_name="dialogue_nodes")
    op.drop_index("ix_dialogue_nodes_created_at", table_name="dialogue_nodes")
    op.drop_index("ix_dialogue_nodes_node_type", table_name="dialogue_nodes")
    op.drop_index("ix_dialogue_nodes_parent_node_id", table_name="dialogue_nodes")
    op.drop_index("ix_dialogue_nodes_session_id", table_name="dialogue_nodes")
    op.drop_table("dialogue_nodes")

    op.drop_index("ix_sessions_updated_at", table_name="sessions")
    op.drop_index("ix_sessions_created_at", table_name="sessions")
    op.drop_index("ix_sessions_current_node_id", table_name="sessions")
    op.drop_index("ix_sessions_status", table_name="sessions")
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_table("sessions")

    op.drop_index("ix_characters_created_at", table_name="characters")
    op.drop_index("ix_characters_name", table_name="characters")
    op.drop_table("characters")

    op.drop_index("ix_users_created_at", table_name="users")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_index("ix_users_google_sub", table_name="users")
    op.drop_table("users")
