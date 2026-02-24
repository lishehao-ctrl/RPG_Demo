"""drop llm usage logs table

Revision ID: 0004_drop_llm_usage_logs
Revises: 0003_hard_cut_story_only_runtime
Create Date: 2026-02-24 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.db.types import GUID

# revision identifiers, used by Alembic.
revision: str = "0004_drop_llm_usage_logs"
down_revision: Union[str, None] = "0003_hard_cut_story_only_runtime"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "llm_usage_logs" not in inspector.get_table_names():
        return

    for index_name in (
        "ix_llm_usage_logs_created_at",
        "ix_llm_usage_logs_status",
        "ix_llm_usage_logs_step_id",
        "ix_llm_usage_logs_operation",
        "ix_llm_usage_logs_model",
        "ix_llm_usage_logs_provider",
        "ix_llm_usage_logs_session_id",
    ):
        op.drop_index(index_name, table_name="llm_usage_logs")
    op.drop_table("llm_usage_logs")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "llm_usage_logs" in inspector.get_table_names():
        return

    op.create_table(
        "llm_usage_logs",
        sa.Column("id", GUID(), primary_key=True, nullable=False),
        sa.Column("session_id", GUID(), sa.ForeignKey("sessions.id"), nullable=True),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column("step_id", GUID(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_llm_usage_logs_session_id", "llm_usage_logs", ["session_id"], unique=False)
    op.create_index("ix_llm_usage_logs_provider", "llm_usage_logs", ["provider"], unique=False)
    op.create_index("ix_llm_usage_logs_model", "llm_usage_logs", ["model"], unique=False)
    op.create_index("ix_llm_usage_logs_operation", "llm_usage_logs", ["operation"], unique=False)
    op.create_index("ix_llm_usage_logs_step_id", "llm_usage_logs", ["step_id"], unique=False)
    op.create_index("ix_llm_usage_logs_status", "llm_usage_logs", ["status"], unique=False)
    op.create_index("ix_llm_usage_logs_created_at", "llm_usage_logs", ["created_at"], unique=False)
