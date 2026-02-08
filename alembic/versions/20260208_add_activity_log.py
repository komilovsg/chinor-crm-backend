"""add activity_log table

Revision ID: 20260208_activity
Revises: 20260208_exclude_bc
Create Date: 2026-02-08

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260208_activity"
down_revision: str | None = "20260208_exclude_bc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "activity_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("action_type", sa.String(50), nullable=False),
        sa.Column("entity_type", sa.String(20), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_activity_log_created_at", "activity_log", ["created_at"])
    op.create_index("ix_activity_log_user_id", "activity_log", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_activity_log_user_id", table_name="activity_log")
    op.drop_index("ix_activity_log_created_at", table_name="activity_log")
    op.drop_table("activity_log")
