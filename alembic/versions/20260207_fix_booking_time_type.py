"""fix booking_time: TIME -> TIMESTAMP WITH TIME ZONE.

Revision ID: fix_booking_time
Revises: b3_users_settings
Create Date: 2026-02-07

Исправляет тип колонки bookings.booking_time: в БД Railway она была создана
как TIME WITHOUT TIME ZONE, а приложение ожидает TIMESTAMP WITH TIME ZONE.
Ошибка: operator does not exist: time without time zone >= timestamp with time zone
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "fix_booking_time"
down_revision: Union[str, None] = "b3_users_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _booking_time_is_time_type(connection) -> bool:
    """Проверить, что booking_time — TIME (не TIMESTAMPTZ)."""
    r = connection.execute(
        text("""
            SELECT data_type FROM information_schema.columns
            WHERE table_name = 'bookings' AND column_name = 'booking_time'
        """)
    )
    row = r.fetchone()
    return row is not None and row[0] == "time without time zone"


def upgrade() -> None:
    conn = op.get_bind()
    if _booking_time_is_time_type(conn):
        # TIME -> TIMESTAMPTZ: комбинируем с epoch-датой (старые записи потеряют дату)
        op.execute("""
            ALTER TABLE bookings
            ALTER COLUMN booking_time TYPE TIMESTAMP WITH TIME ZONE
            USING ((date '1970-01-01' + booking_time) AT TIME ZONE 'UTC')
        """)


def downgrade() -> None:
    # TIMESTAMPTZ -> TIME: извлекаем только время (в UTC)
    op.execute("""
        ALTER TABLE bookings
        ALTER COLUMN booking_time TYPE TIME
        USING ((booking_time AT TIME ZONE 'UTC')::time)
    """)
