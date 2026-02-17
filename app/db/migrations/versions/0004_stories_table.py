"""add stories table

Revision ID: 0004_stories_table
Revises: 0003_action_compiler_logging
Create Date: 2026-02-16 00:10:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.db.types import GUID


revision: str = "0004_stories_table"
down_revision: Union[str, None] = "0003_action_compiler_logging"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "stories",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("story_id", sa.String(length=128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("is_published", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("pack_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("story_id", "version", name="uq_stories_story_version"),
    )
    op.create_index("ix_stories_story_id", "stories", ["story_id"], unique=False)
    op.create_index("ix_stories_version", "stories", ["version"], unique=False)
    op.create_index("ix_stories_is_published", "stories", ["is_published"], unique=False)
    op.create_index("ix_stories_created_at", "stories", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_stories_created_at", table_name="stories")
    op.drop_index("ix_stories_is_published", table_name="stories")
    op.drop_index("ix_stories_version", table_name="stories")
    op.drop_index("ix_stories_story_id", table_name="stories")
    op.drop_table("stories")
