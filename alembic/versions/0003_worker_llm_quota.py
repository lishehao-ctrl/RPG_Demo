"""add worker llm quota window table

Revision ID: 0003_worker_llm_quota
Revises: 0002_admin_user_auth
Create Date: 2026-03-04 00:00:02.000000

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0003_worker_llm_quota"
down_revision: str | None = "0002_admin_user_auth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llmquotawindow",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("window_epoch_minute", sa.Integer(), nullable=False),
        sa.Column("rpm_used", sa.Integer(), nullable=False),
        sa.Column("tpm_used", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("model", "window_epoch_minute", name="uq_llm_quota_window_model_minute"),
    )
    op.create_index("ix_llmquotawindow_model", "llmquotawindow", ["model"], unique=False)
    op.create_index("ix_llmquotawindow_window_epoch_minute", "llmquotawindow", ["window_epoch_minute"], unique=False)
    op.create_index("ix_llmquotawindow_updated_at", "llmquotawindow", ["updated_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_llmquotawindow_updated_at", table_name="llmquotawindow")
    op.drop_index("ix_llmquotawindow_window_epoch_minute", table_name="llmquotawindow")
    op.drop_index("ix_llmquotawindow_model", table_name="llmquotawindow")
    op.drop_table("llmquotawindow")
