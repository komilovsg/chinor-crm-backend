"""Add missing columns to visits table (left_at, revenue, admin_notes, created_at).

Revision ID: visits_columns
Revises: align_schema
Create Date: 2026-02-07

Ошибка: column "left_at" of relation "visits" does not exist.
Railway БД visits может иметь другую схему — добавляем недостающие колонки.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "visits_columns"
down_revision: Union[str, None] = "align_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(connection, table: str, column: str) -> bool:
    r = connection.execute(
        text("""
            SELECT 1 FROM information_schema.columns
            WHERE table_name = :t AND column_name = :c
        """),
        {"t": table, "c": column},
    )
    return r.fetchone() is not None


def _table_exists(connection, table: str) -> bool:
    r = connection.execute(
        text("SELECT 1 FROM information_schema.tables WHERE table_name = :t"),
        {"t": table},
    )
    return r.fetchone() is not None


def upgrade() -> None:
    conn = op.get_bind()
    if not _table_exists(conn, "visits"):
        return

    if not _column_exists(conn, "visits", "left_at"):
        op.execute("ALTER TABLE visits ADD COLUMN left_at TIMESTAMP WITH TIME ZONE")
    if not _column_exists(conn, "visits", "revenue"):
        op.execute("ALTER TABLE visits ADD COLUMN revenue NUMERIC(10, 2)")
    if not _column_exists(conn, "visits", "admin_notes"):
        op.execute("ALTER TABLE visits ADD COLUMN admin_notes TEXT")
    if not _column_exists(conn, "visits", "created_at"):
        op.execute("ALTER TABLE visits ADD COLUMN created_at TIMESTAMP WITH TIME ZONE")
    if not _column_exists(conn, "visits", "booking_id"):
        op.execute("ALTER TABLE visits ADD COLUMN booking_id INTEGER REFERENCES bookings(id)")


def downgrade() -> None:
    pass
