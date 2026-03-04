"""add admin user auth table

Revision ID: 0002_admin_user_auth
Revises: 0001_initial_schema
Create Date: 2026-03-04 00:00:01.000000

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0002_admin_user_auth"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "adminuser",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_admin_user_email"),
    )
    op.create_index("ix_adminuser_email", "adminuser", ["email"], unique=False)
    op.create_index("ix_adminuser_created_at", "adminuser", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_adminuser_created_at", table_name="adminuser")
    op.drop_index("ix_adminuser_email", table_name="adminuser")
    op.drop_table("adminuser")
