"""Пересчёт метрик гостя по подтверждённым бронированиям.

Обновляет только confirmed_bookings_count и last_visit_at от последней подтверждённой брони.
visits_count и segment не трогаются: визиты и сегмент считаются по кнопке «Добавить визит»
и по правилам сегментации в Настройках (пересчитать сегменты всех гостей).
"""
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Booking, Guest


async def recalc_guest_metrics_from_bookings(
    session: AsyncSession,
    guest_id: int,
) -> None:
    """Пересчитать у гостя только confirmed_bookings_count и last_visit_at по броням со статусом «confirmed».

    visits_count и segment не меняются: визиты и сегмент задаются кнопкой «Добавить визит»
    и правилами сегментации в Настройках.
    """
    count_stmt = select(func.count(Booking.id)).where(
        Booking.guest_id == guest_id,
        Booking.status == "confirmed",
    )
    count_result = await session.execute(count_stmt)
    confirmed_count = count_result.scalar() or 0

    max_time_stmt = select(func.max(Booking.booking_time)).where(
        Booking.guest_id == guest_id,
        Booking.status == "confirmed",
    )
    max_result = await session.execute(max_time_stmt)
    last_booking_time = max_result.scalar()

    guest_result = await session.execute(select(Guest).where(Guest.id == guest_id))
    guest = guest_result.scalars().one_or_none()
    if not guest:
        return

    now = datetime.now(timezone.utc)
    guest.confirmed_bookings_count = confirmed_count
    guest.updated_at = now
    if last_booking_time is not None:
        guest.last_visit_at = (
            last_booking_time.replace(tzinfo=timezone.utc)
            if last_booking_time.tzinfo is None
            else last_booking_time
        )
    # при отсутствии подтверждённых броней last_visit_at не трогаем (может быть от «Добавить визит»)
    # Сегмент не меняем — он считается только по visits_count и порогам из Настроек
