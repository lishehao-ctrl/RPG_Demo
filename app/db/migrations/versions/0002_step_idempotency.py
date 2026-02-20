"""add session step idempotency table

Revision ID: 0002_step_idempotency
Revises: 0001_init
Create Date: 2026-02-19 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.db.types import GUID, JSONType

# revision identifiers, used by Alembic.
revision: str = "0002_step_idempotency"
down_revision: Union[str, None] = "0001_init"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "session_step_idempotency",
        sa.Column("id", GUID(), primary_key=True, nullable=False),
        sa.Column("session_id", GUID(), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("response_json", JSONType, nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "session_id",
            "idempotency_key",
            name="uq_session_step_idempotency_session_key",
        ),
    )
    op.create_index(
        "ix_session_step_idempotency_session_id",
        "session_step_idempotency",
        ["session_id"],
        unique=False,
    )
    op.create_index(
        "ix_session_step_idempotency_idempotency_key",
        "session_step_idempotency",
        ["idempotency_key"],
        unique=False,
    )
    op.create_index(
        "ix_session_step_idempotency_request_hash",
        "session_step_idempotency",
        ["request_hash"],
        unique=False,
    )
    op.create_index(
        "ix_session_step_idempotency_status",
        "session_step_idempotency",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_session_step_idempotency_created_at",
        "session_step_idempotency",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_session_step_idempotency_updated_at",
        "session_step_idempotency",
        ["updated_at"],
        unique=False,
    )
    op.create_index(
        "ix_session_step_idempotency_expires_at",
        "session_step_idempotency",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_session_step_idempotency_expires_at", table_name="session_step_idempotency")
    op.drop_index("ix_session_step_idempotency_updated_at", table_name="session_step_idempotency")
    op.drop_index("ix_session_step_idempotency_created_at", table_name="session_step_idempotency")
    op.drop_index("ix_session_step_idempotency_status", table_name="session_step_idempotency")
    op.drop_index("ix_session_step_idempotency_request_hash", table_name="session_step_idempotency")
    op.drop_index("ix_session_step_idempotency_idempotency_key", table_name="session_step_idempotency")
    op.drop_index("ix_session_step_idempotency_session_id", table_name="session_step_idempotency")
    op.drop_table("session_step_idempotency")
