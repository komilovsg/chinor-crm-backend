"""add guest exclude_from_broadcasts

Revision ID: 20260208_exclude_bc
Revises: 20260208_image_url
Create Date: 2026-02-08

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260208_exclude_bc"
down_revision: str | None = "20260208_image_url"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "guests",
        sa.Column("exclude_from_broadcasts", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("guests", "exclude_from_broadcasts")
