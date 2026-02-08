"""add guest confirmed_bookings_count

Revision ID: 20260208_confirmed_bc
Revises: 20260208_activity
Create Date: 2026-02-08

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260208_confirmed_bc"
down_revision: str | None = "20260208_activity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "guests",
        sa.Column("confirmed_bookings_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    # Backfill: set confirmed_bookings_count = count of confirmed bookings per guest
    op.execute("""
        UPDATE guests g
        SET confirmed_bookings_count = (
            SELECT COUNT(*) FROM bookings b
            WHERE b.guest_id = g.id AND b.status = 'confirmed'
        )
    """)


def downgrade() -> None:
    op.drop_column("guests", "confirmed_bookings_count")
