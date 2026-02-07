"""GET /api/dashboard/stats: totalBookings, todayArrivals, guestCount, noShowRate."""
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import Booking, Guest, User
from app.db.session import get_session

router = APIRouter(prefix="/api", tags=["dashboard"])


class DashboardStatsResponse(BaseModel):
    totalBookings: int
    todayArrivals: int
    guestCount: int
    noShowRate: float


@router.get("/dashboard/stats", response_model=DashboardStatsResponse)
async def get_dashboard_stats(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DashboardStatsResponse:
    """Статистика для карточек дашборда: брони, приезды сегодня, гости, % no-show."""
    # totalBookings
    total_result = await session.execute(select(func.count(Booking.id)))
    total_bookings = (total_result.scalar() or 0)

    # todayArrivals: брони с booking_time в сегодняшней дате (UTC)
    today_start = datetime.combine(date.today(), datetime.min.time()).replace(tzinfo=timezone.utc)
    today_end = today_start.replace(hour=23, minute=59, second=59, microsecond=999999)
    today_result = await session.execute(
        select(func.count(Booking.id)).where(
            Booking.booking_time >= today_start,
            Booking.booking_time <= today_end,
        )
    )
    today_arrivals = (today_result.scalar() or 0)

    # guestCount: гости без deleted_at
    guests_result = await session.execute(
        select(func.count(Guest.id)).where(Guest.deleted_at.is_(None))
    )
    guest_count = (guests_result.scalar() or 0)

    # noShowRate: доля no_show среди завершённых (confirmed, no_show, canceled)
    resolved_statuses = ("confirmed", "no_show", "canceled")
    resolved_result = await session.execute(
        select(func.count(Booking.id)).where(Booking.status.in_(resolved_statuses))
    )
    resolved_total = (resolved_result.scalar() or 0)
    no_show_result = await session.execute(
        select(func.count(Booking.id)).where(Booking.status == "no_show")
    )
    no_show_count = (no_show_result.scalar() or 0)
    no_show_rate = round((no_show_count / resolved_total * 100.0), 1) if resolved_total else 0.0

    return DashboardStatsResponse(
        totalBookings=total_bookings,
        todayArrivals=today_arrivals,
        guestCount=guest_count,
        noShowRate=no_show_rate,
    )
