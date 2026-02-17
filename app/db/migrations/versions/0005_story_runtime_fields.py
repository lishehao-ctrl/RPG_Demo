"""add story runtime fields to sessions and action logs

Revision ID: 0005_story_runtime_fields
Revises: 0004_stories_table
Create Date: 2026-02-16 00:20:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0005_story_runtime_fields"
down_revision: Union[str, None] = "0004_stories_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("story_id", sa.String(length=128), nullable=True))
    op.add_column("sessions", sa.Column("story_version", sa.Integer(), nullable=True))
    op.create_index("ix_sessions_story_id", "sessions", ["story_id"], unique=False)
    op.create_index("ix_sessions_story_version", "sessions", ["story_version"], unique=False)

    op.add_column("action_logs", sa.Column("story_node_id", sa.String(length=128), nullable=True))
    op.add_column("action_logs", sa.Column("story_choice_id", sa.String(length=128), nullable=True))
    op.create_index("ix_action_logs_story_node_id", "action_logs", ["story_node_id"], unique=False)
    op.create_index("ix_action_logs_story_choice_id", "action_logs", ["story_choice_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_action_logs_story_choice_id", table_name="action_logs")
    op.drop_index("ix_action_logs_story_node_id", table_name="action_logs")
    op.drop_column("action_logs", "story_choice_id")
    op.drop_column("action_logs", "story_node_id")

    op.drop_index("ix_sessions_story_version", table_name="sessions")
    op.drop_index("ix_sessions_story_id", table_name="sessions")
    op.drop_column("sessions", "story_version")
    op.drop_column("sessions", "story_id")
