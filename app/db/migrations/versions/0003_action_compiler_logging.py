"""add action compiler logging fields

Revision ID: 0003_action_compiler_logging
Revises: 0002_step_id_accounting
Create Date: 2026-02-16 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003_action_compiler_logging"
down_revision: Union[str, None] = "0002_step_id_accounting"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("action_logs", sa.Column("user_raw_input", sa.Text(), nullable=True))
    op.add_column("action_logs", sa.Column("proposed_action", sa.JSON(), nullable=False, server_default="{}"))
    op.add_column("action_logs", sa.Column("final_action", sa.JSON(), nullable=False, server_default="{}"))
    op.add_column("action_logs", sa.Column("fallback_used", sa.Boolean(), nullable=False, server_default=sa.text("0")))
    op.add_column("action_logs", sa.Column("fallback_reasons", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("action_logs", sa.Column("action_confidence", sa.Numeric(4, 3), nullable=True))
    op.add_column("action_logs", sa.Column("key_decision", sa.Boolean(), nullable=False, server_default=sa.text("0")))


def downgrade() -> None:
    op.drop_column("action_logs", "key_decision")
    op.drop_column("action_logs", "action_confidence")
    op.drop_column("action_logs", "fallback_reasons")
    op.drop_column("action_logs", "fallback_used")
    op.drop_column("action_logs", "final_action")
    op.drop_column("action_logs", "proposed_action")
    op.drop_column("action_logs", "user_raw_input")
