"""add session version and action log unique step index

Revision ID: 0002_session_version_and_actionlog_unique
Revises: 0001_initial
Create Date: 2026-02-26
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_session_version_and_actionlog_unique"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("sessions") as batch_op:
        batch_op.add_column(sa.Column("version", sa.Integer(), nullable=False, server_default="0"))

    with op.batch_alter_table("action_logs") as batch_op:
        batch_op.create_unique_constraint("uq_action_log_session_step", ["session_id", "step_index"])


def downgrade() -> None:
    with op.batch_alter_table("action_logs") as batch_op:
        batch_op.drop_constraint("uq_action_log_session_step", type_="unique")

    with op.batch_alter_table("sessions") as batch_op:
        batch_op.drop_column("version")
