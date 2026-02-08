"""add campaign image_url

Revision ID: 20260208_image_url
Revises: 20260207_fix_booking_time
Create Date: 2026-02-08

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260208_image_url"
down_revision: str | None = "visits_columns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "campaigns",
        sa.Column("image_url", sa.String(500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("campaigns", "image_url")
