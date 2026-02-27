"""initial schema

Revision ID: 0001_initial
Revises: 
Create Date: 2026-02-25
"""

from alembic import op
import sqlalchemy as sa


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("external_ref", sa.String(length=128), nullable=True, unique=True),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "stories",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("story_id", sa.String(length=128), nullable=False, unique=True),
        sa.Column("owner_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("active_published_version", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "story_versions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("story_id", sa.String(length=128), sa.ForeignKey("stories.story_id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("pack_json", sa.JSON(), nullable=False),
        sa.Column("pack_schema_version", sa.String(length=32), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("story_id", "version", name="uq_story_version"),
    )

    op.create_table(
        "sessions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("story_id", sa.String(length=128), nullable=False),
        sa.Column("story_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("story_node_id", sa.String(length=128), nullable=False),
        sa.Column("state_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "action_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.String(length=36), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("request_payload_json", sa.JSON(), nullable=False),
        sa.Column("selection_result_json", sa.JSON(), nullable=False),
        sa.Column("state_before", sa.JSON(), nullable=False),
        sa.Column("state_delta", sa.JSON(), nullable=False),
        sa.Column("state_after", sa.JSON(), nullable=False),
        sa.Column("llm_trace_json", sa.JSON(), nullable=False),
        sa.Column("classification_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_action_logs_session_id", "action_logs", ["session_id"])

    op.create_table(
        "session_step_idempotency",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.String(length=36), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("response_json", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("session_id", "idempotency_key", name="uq_session_idempotency_key"),
    )
    op.create_index("ix_session_step_idempotency_session_id", "session_step_idempotency", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_session_step_idempotency_session_id", table_name="session_step_idempotency")
    op.drop_table("session_step_idempotency")
    op.drop_index("ix_action_logs_session_id", table_name="action_logs")
    op.drop_table("action_logs")
    op.drop_table("sessions")
    op.drop_table("story_versions")
    op.drop_table("stories")
    op.drop_table("users")
