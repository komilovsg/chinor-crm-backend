"""Align Railway DB schema with app models.

Revision ID: align_schema
Revises: fix_booking_time
Create Date: 2026-02-07

Добавляет недостающие колонки: campaigns.message_text, guests.deleted_at,
guests.segment, guests.visits_count, guests.is_in_stop_list и др.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "align_schema"
down_revision: Union[str, None] = "fix_booking_time"
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

    # campaigns.message_text — ошибка: column campaigns.message_text does not exist
    if _table_exists(conn, "campaigns") and not _column_exists(conn, "campaigns", "message_text"):
        op.execute("""
            ALTER TABLE campaigns
            ADD COLUMN message_text TEXT NOT NULL DEFAULT ''
        """)

    # guests — нужны для GET /guests (deleted_at.is_(None)), broadcasts (is_in_stop_list)
    if _table_exists(conn, "guests"):
        if not _column_exists(conn, "guests", "deleted_at"):
            op.execute("ALTER TABLE guests ADD COLUMN deleted_at TIMESTAMP WITH TIME ZONE")
        if not _column_exists(conn, "guests", "segment"):
            op.execute("ALTER TABLE guests ADD COLUMN segment VARCHAR(50) DEFAULT 'Новичок'")
        if not _column_exists(conn, "guests", "visits_count"):
            op.execute("ALTER TABLE guests ADD COLUMN visits_count INTEGER DEFAULT 0")
        if not _column_exists(conn, "guests", "is_in_stop_list"):
            op.execute("ALTER TABLE guests ADD COLUMN is_in_stop_list BOOLEAN DEFAULT FALSE")
        if not _column_exists(conn, "guests", "consent_marketing"):
            op.execute("ALTER TABLE guests ADD COLUMN consent_marketing BOOLEAN DEFAULT FALSE")
        if not _column_exists(conn, "guests", "total_revenue"):
            op.execute("ALTER TABLE guests ADD COLUMN total_revenue NUMERIC(10,2) DEFAULT 0")
        if not _column_exists(conn, "guests", "last_interaction_at"):
            op.execute("ALTER TABLE guests ADD COLUMN last_interaction_at TIMESTAMP WITH TIME ZONE")
        if not _column_exists(conn, "guests", "wa_id"):
            op.execute("ALTER TABLE guests ADD COLUMN wa_id VARCHAR(50) UNIQUE")
        if not _column_exists(conn, "guests", "updated_at"):
            op.execute("ALTER TABLE guests ADD COLUMN updated_at TIMESTAMP WITH TIME ZONE")

    # campaign_sends.created_at — если используется
    if _table_exists(conn, "campaign_sends") and not _column_exists(conn, "campaign_sends", "created_at"):
        op.execute("ALTER TABLE campaign_sends ADD COLUMN created_at TIMESTAMP WITH TIME ZONE")


def downgrade() -> None:
    # Не откатываем — может сломать данные; при необходимости откат вручную
    pass
