"""Пересчёт метрик гостя (visits_count, segment) по подтверждённым бронированиям.

Источник истины: количество броней со статусом confirmed.
При смене статуса брони на «Подтверждено» или с «Подтверждено» на другой
нужно вызывать recalc_guest_metrics_from_bookings — тогда счётчики в таблице
гостей всегда совпадают с фактическим числом подтверждённых броней.
"""
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Booking, Guest, Setting
from app.services.segmentation import calc_segment


async def _get_segment_thresholds(session: AsyncSession) -> tuple[int, int]:
    """Пороги сегментации из settings."""
    result = await session.execute(
        select(Setting).where(
            Setting.key.in_(("segment_regular_threshold", "segment_vip_threshold"))
        )
    )
    by_key = {r.key: r.value for r in result.scalars().all()}
    reg = 5
    vip = 10
    if by_key.get("segment_regular_threshold"):
        try:
            reg = max(0, int((by_key["segment_regular_threshold"] or "").strip()))
        except (ValueError, AttributeError):
            pass
    if by_key.get("segment_vip_threshold"):
        try:
            vip = max(0, int((by_key["segment_vip_threshold"] or "").strip()))
        except (ValueError, AttributeError):
            pass
    if vip <= reg:
        vip = reg + 1
    return reg, vip


async def recalc_guest_metrics_from_bookings(
    session: AsyncSession,
    guest_id: int,
) -> None:
    """Пересчитать у гостя visits_count и segment по числу подтверждённых броней.

    Вызывать после любого изменения статуса брони этого гостя (в т.ч. confirm /
    cancel / no_show). Так «Визиты» и «Подтверждённые брони» в разделе Гости
    всегда равны количеству броней со статусом «Подтверждено».
    """
    # Количество подтверждённых броней гостя
    count_stmt = select(func.count(Booking.id)).where(
        Booking.guest_id == guest_id,
        Booking.status == "confirmed",
    )
    count_result = await session.execute(count_stmt)
    confirmed_count = count_result.scalar() or 0

    # Последняя дата подтверждённой брони (для last_visit_at)
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
    guest.visits_count = confirmed_count
    guest.updated_at = now
    if last_booking_time is not None:
        guest.last_visit_at = (
            last_booking_time.replace(tzinfo=timezone.utc)
            if last_booking_time.tzinfo is None
            else last_booking_time
        )
    else:
        guest.last_visit_at = None

    reg, vip = await _get_segment_thresholds(session)
    guest.segment = calc_segment(confirmed_count, reg, vip)
