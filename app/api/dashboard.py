"""GET /api/dashboard/stats, recent-activity, user-stats, visits-by-date, activity export (admin)."""
import csv
import io
import json
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_role
from app.db.models import ActivityLog, Booking, Guest, User, Visit
from app.db.session import get_session

router = APIRouter(prefix="/api", tags=["dashboard"])


class DashboardStatsResponse(BaseModel):
    totalBookings: int
    todayArrivals: int
    guestCount: int
    noShowRate: float


class RecentActivityItem(BaseModel):
    id: int
    created_at: str
    action_type: str
    entity_type: str
    entity_id: int
    details: Optional[str] = None
    user_display_name: str
    user_email: str
    summary: str  # краткое описание для таблицы


class UserActivityStats(BaseModel):
    user_id: int
    display_name: str
    email: str
    role: str
    bookings_created: int
    guests_created: int
    status_changes: int


class VisitsByDateItem(BaseModel):
    date: str  # YYYY-MM-DD
    count: int


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


def _action_label(action_type: str, details: Optional[str]) -> str:
    if action_type == "booking_created":
        return "Создана бронь"
    if action_type == "guest_created":
        return "Добавлен гость"
    if action_type == "booking_status_changed" and details:
        try:
            d = json.loads(details)
            old_s = d.get("old_status", "")
            new_s = d.get("new_status", "")
            return f"Статус брони: {old_s} → {new_s}"
        except (json.JSONDecodeError, TypeError):
            pass
        return "Смена статуса брони"
    return action_type


@router.get("/dashboard/recent-activity", response_model=List[RecentActivityItem])
async def get_recent_activity(
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(require_role(["admin"])),
    session: AsyncSession = Depends(get_session),
) -> List[RecentActivityItem]:
    """Последние действия по броням и гостям (только админ)."""
    stmt = (
        select(ActivityLog, User)
        .join(User, ActivityLog.user_id == User.id)
        .order_by(ActivityLog.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    rows = result.all()
    out = []
    for log, user in rows:
        summary = _action_label(log.action_type, log.details)
        if log.entity_type == "booking" and log.entity_id:
            summary += f" (бронь #{log.entity_id})"
        elif log.entity_type == "guest" and log.entity_id:
            summary += f" (гость #{log.entity_id})"
        out.append(
            RecentActivityItem(
                id=log.id,
                created_at=log.created_at.isoformat() if log.created_at else "",
                action_type=log.action_type,
                entity_type=log.entity_type,
                entity_id=log.entity_id,
                details=log.details,
                user_display_name=user.display_name or user.email,
                user_email=user.email or "",
                summary=summary,
            )
        )
    return out


@router.get("/dashboard/user-stats", response_model=List[UserActivityStats])
async def get_user_activity_stats(
    current_user: User = Depends(require_role(["admin"])),
    session: AsyncSession = Depends(get_session),
) -> List[UserActivityStats]:
    """Сводка по пользователям: сколько броней создано, гостей добавлено, смен статусов (только админ)."""
    users_result = await session.execute(select(User).order_by(User.id))
    users = users_result.scalars().all()
    out = []
    for u in users:
        b_created = await session.execute(
            select(func.count(ActivityLog.id)).where(
                ActivityLog.user_id == u.id,
                ActivityLog.action_type == "booking_created",
            )
        )
        g_created = await session.execute(
            select(func.count(ActivityLog.id)).where(
                ActivityLog.user_id == u.id,
                ActivityLog.action_type == "guest_created",
            )
        )
        s_changes = await session.execute(
            select(func.count(ActivityLog.id)).where(
                ActivityLog.user_id == u.id,
                ActivityLog.action_type == "booking_status_changed",
            )
        )
        out.append(
            UserActivityStats(
                user_id=u.id,
                display_name=u.display_name or u.email,
                email=u.email or "",
                role=u.role or "",
                bookings_created=(b_created.scalar() or 0),
                guests_created=(g_created.scalar() or 0),
                status_changes=(s_changes.scalar() or 0),
            )
        )
    return out


@router.get("/dashboard/visits-by-date", response_model=List[VisitsByDateItem])
async def get_visits_by_date(
    from_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    to_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    current_user: User = Depends(require_role(["admin"])),
    session: AsyncSession = Depends(get_session),
) -> List[VisitsByDateItem]:
    """Количество визитов по дням для календаря (только админ). По умолчанию — последние 3 месяца."""
    tz = timezone.utc
    if to_date:
        try:
            end = datetime.strptime(to_date[:10], "%Y-%m-%d").date()
        except ValueError:
            end = date.today()
    else:
        end = date.today()
    if from_date:
        try:
            start = datetime.strptime(from_date[:10], "%Y-%m-%d").date()
        except ValueError:
            start = end - timedelta(days=90)
    else:
        start = end - timedelta(days=90)
    start_dt = datetime.combine(start, datetime.min.time()).replace(tzinfo=tz)
    end_dt = datetime.combine(end, datetime.max.time()).replace(tzinfo=tz)

    # Visit.arrived_at — дата визита; считаем количество визитов по дням
    stmt = (
        select(func.date(Visit.arrived_at).label("day"), func.count(Visit.id).label("cnt"))
        .where(Visit.arrived_at >= start_dt, Visit.arrived_at <= end_dt)
        .group_by(func.date(Visit.arrived_at))
        .order_by(func.date(Visit.arrived_at))
    )
    result = await session.execute(stmt)
    rows = result.all()
    return [VisitsByDateItem(date=str(r.day), count=r.cnt) for r in rows]


@router.get("/dashboard/activity-export")
async def export_activity(
    limit: int = Query(5000, ge=1, le=50000),
    current_user: User = Depends(require_role(["admin"])),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Выгрузка журнала активности в CSV (только админ)."""
    stmt = (
        select(ActivityLog, User)
        .join(User, ActivityLog.user_id == User.id)
        .order_by(ActivityLog.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    rows = result.all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Дата", "Пользователь", "Email", "Действие", "Тип объекта", "ID объекта", "Детали"])
    for log, user in rows:
        summary = _action_label(log.action_type, log.details)
        writer.writerow([
            log.created_at.strftime("%Y-%m-%d %H:%M:%S") if log.created_at else "",
            user.display_name or user.email or "",
            user.email or "",
            summary,
            log.entity_type,
            log.entity_id,
            log.details or "",
        ])
    body = "\ufeff" + output.getvalue()
    return Response(
        content=body.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="activity-log.csv"'},
    )
