"""hard cut story-only runtime schema

Revision ID: 0003_hard_cut_story_only_runtime
Revises: 0002_step_idempotency
Create Date: 2026-02-21 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.db.types import GUID, JSONType

# revision identifiers, used by Alembic.
revision: str = "0003_hard_cut_story_only_runtime"
down_revision: Union[str, None] = "0002_step_idempotency"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("action_logs") as batch:
        batch.drop_index("ix_action_logs_node_id")
        batch.drop_column("node_id")

    with op.batch_alter_table("sessions") as batch:
        batch.drop_index("ix_sessions_current_node_id")
        batch.drop_column("current_node_id")
        batch.drop_column("route_flags")

    op.drop_index("ix_dialogue_nodes_parent_created", table_name="dialogue_nodes")
    op.drop_index("ix_dialogue_nodes_created_at", table_name="dialogue_nodes")
    op.drop_index("ix_dialogue_nodes_node_type", table_name="dialogue_nodes")
    op.drop_index("ix_dialogue_nodes_parent_node_id", table_name="dialogue_nodes")
    op.drop_index("ix_dialogue_nodes_session_id", table_name="dialogue_nodes")
    op.drop_table("dialogue_nodes")


def downgrade() -> None:
    op.create_table(
        "dialogue_nodes",
        sa.Column("id", GUID(), primary_key=True, nullable=False),
        sa.Column("session_id", GUID(), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("parent_node_id", GUID(), sa.ForeignKey("dialogue_nodes.id"), nullable=True),
        sa.Column("node_type", sa.String(length=32), nullable=False, server_default="ai"),
        sa.Column("player_input", sa.Text(), nullable=True),
        sa.Column("narrative_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("choices", JSONType, nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_dialogue_nodes_session_id", "dialogue_nodes", ["session_id"], unique=False)
    op.create_index("ix_dialogue_nodes_parent_node_id", "dialogue_nodes", ["parent_node_id"], unique=False)
    op.create_index("ix_dialogue_nodes_node_type", "dialogue_nodes", ["node_type"], unique=False)
    op.create_index("ix_dialogue_nodes_created_at", "dialogue_nodes", ["created_at"], unique=False)
    op.create_index("ix_dialogue_nodes_parent_created", "dialogue_nodes", ["parent_node_id", "created_at"], unique=False)

    with op.batch_alter_table("sessions") as batch:
        batch.add_column(sa.Column("current_node_id", GUID(), nullable=True))
        batch.add_column(sa.Column("route_flags", JSONType, nullable=False, server_default="{}"))
        batch.create_index("ix_sessions_current_node_id", ["current_node_id"], unique=False)

    with op.batch_alter_table("action_logs") as batch:
        batch.add_column(sa.Column("node_id", GUID(), sa.ForeignKey("dialogue_nodes.id"), nullable=True))
        batch.create_index("ix_action_logs_node_id", ["node_id"], unique=False)
