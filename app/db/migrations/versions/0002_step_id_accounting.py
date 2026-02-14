"""add step_id to llm usage logs

Revision ID: 0002_step_id_accounting
Revises: 0001_init
Create Date: 2026-02-14 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.db.types import GUID


revision: str = "0002_step_id_accounting"
down_revision: Union[str, None] = "0001_init"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("llm_usage_logs", sa.Column("step_id", GUID(), nullable=True))
    op.create_index("ix_llm_usage_logs_step_id", "llm_usage_logs", ["step_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_llm_usage_logs_step_id", table_name="llm_usage_logs")
    op.drop_column("llm_usage_logs", "step_id")
