"""Guests API: GET list (search, page, limit), GET :id, POST, PATCH :id, POST :id/visits, GET export (CSV)."""
import csv
import io
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_role
from app.db.models import ActivityLog, Guest, Setting, User, Visit
from app.db.session import get_session
from app.services.segmentation import calc_segment

router = APIRouter(prefix="/api", tags=["guests"])


class GuestResponse(BaseModel):
    id: int
    name: Optional[str]
    phone: str
    email: Optional[str]
    segment: str
    visits_count: int
    confirmed_bookings_count: int = 0
    last_visit_at: Optional[str]
    created_at: str
    exclude_from_broadcasts: bool = False

    class Config:
        from_attributes = True


class PaginatedGuestsResponse(BaseModel):
    items: List[GuestResponse]
    total: int
    page: int
    limit: int


class CreateGuestRequest(BaseModel):
    name: Optional[str] = None
    phone: str
    email: Optional[str] = None


class UpdateGuestRequest(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    exclude_from_broadcasts: Optional[bool] = None
    # segment не редактируется вручную — рассчитывается автоматически по visits_count


def _guest_to_response(guest: Guest) -> GuestResponse:
    return GuestResponse(
        id=guest.id,
        name=guest.name,
        phone=guest.phone,
        email=guest.email,
        segment=guest.segment or "Новичок",
        visits_count=guest.visits_count or 0,
        confirmed_bookings_count=getattr(guest, "confirmed_bookings_count", 0),
        last_visit_at=guest.last_visit_at.isoformat() if guest.last_visit_at else None,
        created_at=guest.created_at.isoformat() if guest.created_at else "",
        exclude_from_broadcasts=getattr(guest, "exclude_from_broadcasts", False),
    )


class GuestStatsResponse(BaseModel):
    total: int
    vip: int
    regular: int
    new: int


@router.get("/guests/stats", response_model=GuestStatsResponse)
async def get_guest_stats(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> GuestStatsResponse:
    """Статистика гостей: всего, VIP, постоянные, новички (без удалённых)."""
    base = select(Guest).where(Guest.deleted_at.is_(None))
    total_result = await session.execute(select(func.count()).select_from(base.subquery()))
    total = (total_result.scalar() or 0)
    vip_result = await session.execute(
        select(func.count(Guest.id)).where(
            Guest.deleted_at.is_(None),
            Guest.segment == "VIP",
        )
    )
    regular_result = await session.execute(
        select(func.count(Guest.id)).where(
            Guest.deleted_at.is_(None),
            Guest.segment == "Постоянный",
        )
    )
    new_result = await session.execute(
        select(func.count(Guest.id)).where(
            Guest.deleted_at.is_(None),
            Guest.segment.in_(["Новичок", "Новички"]),
        )
    )
    vip_count = vip_result.scalar() or 0
    regular_count = regular_result.scalar() or 0
    new_count = new_result.scalar() or 0
    return GuestStatsResponse(total=total, vip=vip_count, regular=regular_count, new=new_count)


@router.get("/guests", response_model=PaginatedGuestsResponse)
async def get_guests(
    search: Optional[str] = None,
    page: int = 1,
    limit: int = 10,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> PaginatedGuestsResponse:
    """Список гостей (без удалённых), поиск по имени/телефону, пагинация."""
    limit = max(1, min(limit, 100))
    page = max(1, page)
    offset = (page - 1) * limit

    stmt = select(Guest).where(Guest.deleted_at.is_(None)).order_by(Guest.id.desc())
    if search and search.strip():
        search_arg = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                Guest.name.ilike(search_arg),
                Guest.phone.ilike(search_arg),
            )
        )

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await session.execute(count_stmt)
    total = (total_result.scalar() or 0)

    stmt = stmt.offset(offset).limit(limit)
    result = await session.execute(stmt)
    guests = result.scalars().all()

    return PaginatedGuestsResponse(
        items=[_guest_to_response(g) for g in guests],
        total=total,
        page=page,
        limit=limit,
    )


@router.get("/guests/export")
async def export_guests(
    search: Optional[str] = None,
    current_user: User = Depends(require_role(["admin"])),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Экспорт гостей в CSV (поиск по имени/телефону). Доступ: только admin."""
    stmt = select(Guest).where(Guest.deleted_at.is_(None)).order_by(Guest.id)
    if search and search.strip():
        search_arg = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                Guest.name.ilike(search_arg),
                Guest.phone.ilike(search_arg),
            )
        )
    result = await session.execute(stmt)
    guests = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Имя", "Телефон", "Email", "Сегмент", "Визиты", "Последний визит"])
    for g in guests:
        writer.writerow([
            g.name or "",
            g.phone or "",
            g.email or "",
            g.segment or "Новичок",
            g.visits_count or 0,
            g.last_visit_at.isoformat() if g.last_visit_at else "",
        ])
    body = "\ufeff" + output.getvalue()
    return Response(
        content=body.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="guests.csv"'},
    )


@router.get("/guests/{guest_id}", response_model=GuestResponse)
async def get_guest(
    guest_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> GuestResponse:
    """Один гость по ID."""
    result = await session.execute(select(Guest).where(Guest.id == guest_id))
    guest = result.scalars().one_or_none()
    if not guest or guest.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Guest not found")
    return _guest_to_response(guest)


@router.post("/guests", response_model=GuestResponse)
async def create_guest(
    body: CreateGuestRequest,
    current_user: User = Depends(require_role(["admin", "hostess"])),
    session: AsyncSession = Depends(get_session),
) -> GuestResponse:
    """Создать гостя. Телефон обязателен и уникален. Доступ: admin, hostess."""
    phone = body.phone.strip() if body.phone else ""
    if not phone:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Phone is required",
        )
    existing = await session.execute(select(Guest).where(Guest.phone == phone))
    if existing.scalars().one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Guest with this phone already exists",
        )
    now = datetime.now(timezone.utc)
    guest = Guest(
        phone=phone,
        name=(body.name.strip() or None) if body.name else None,
        email=(body.email.strip() or None) if body.email else None,
        segment="Новичок",
        visits_count=0,
        created_at=now,
    )
    session.add(guest)
    await session.flush()
    session.add(
        ActivityLog(
            user_id=current_user.id,
            action_type="guest_created",
            entity_type="guest",
            entity_id=guest.id,
            created_at=now,
        )
    )
    await session.commit()
    await session.refresh(guest)
    return _guest_to_response(guest)


@router.patch("/guests/{guest_id}", response_model=GuestResponse)
async def update_guest(
    guest_id: int,
    body: UpdateGuestRequest,
    current_user: User = Depends(require_role(["admin", "hostess"])),
    session: AsyncSession = Depends(get_session),
) -> GuestResponse:
    """Обновить данные гостя (имя, телефон, email, сегмент). Телефон уникален. Доступ: admin, hostess."""
    result = await session.execute(select(Guest).where(Guest.id == guest_id))
    guest = result.scalars().one_or_none()
    if not guest or guest.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Guest not found")
    if body.phone is not None:
        phone = body.phone.strip() if body.phone else ""
        if not phone:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Phone cannot be empty",
            )
        other = await session.execute(select(Guest).where(Guest.phone == phone, Guest.id != guest_id))
        if other.scalars().one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Another guest with this phone already exists",
            )
        guest.phone = phone
    if body.name is not None:
        guest.name = body.name.strip() if body.name else None
    if body.email is not None:
        guest.email = body.email.strip() if body.email else None
    if body.exclude_from_broadcasts is not None:
        guest.exclude_from_broadcasts = body.exclude_from_broadcasts
    # segment пересчитывается автоматически при изменении visits_count
    await session.commit()
    await session.refresh(guest)
    return _guest_to_response(guest)


async def _get_segment_thresholds(session: AsyncSession) -> tuple[int, int]:
    """Получить пороги сегментации из settings."""
    result = await session.execute(
        select(Setting).where(
            Setting.key.in_(("segment_regular_threshold", "segment_vip_threshold"))
        )
    )
    rows = result.scalars().all()
    by_key = {r.key: r.value for r in rows}
    reg = 5
    vip = 10
    if by_key.get("segment_regular_threshold"):
        try:
            reg = max(0, int(by_key["segment_regular_threshold"].strip()))
        except (ValueError, AttributeError):
            pass
    if by_key.get("segment_vip_threshold"):
        try:
            vip = max(0, int(by_key["segment_vip_threshold"].strip()))
        except (ValueError, AttributeError):
            pass
    if vip <= reg:
        vip = reg + 1
    return reg, vip


@router.post("/guests/{guest_id}/visits", response_model=GuestResponse)
async def add_guest_visit(
    guest_id: int,
    current_user: User = Depends(require_role(["admin", "hostess"])),
    session: AsyncSession = Depends(get_session),
) -> GuestResponse:
    """Добавить визит гостю: увеличить visits_count и пересчитать сегмент по правилам из Настроек (confirmed_bookings_count не меняется). Доступ: admin, hostess."""
    result = await session.execute(select(Guest).where(Guest.id == guest_id))
    guest = result.scalars().one_or_none()
    if not guest or guest.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Guest not found")

    now = datetime.now(timezone.utc)
    visit = Visit(
        guest_id=guest.id,
        arrived_at=now,
        left_at=None,
        revenue=None,
        admin_notes=None,
        created_at=now,
    )
    session.add(visit)
    await session.flush()  # чтобы INSERT визита выполнился
    # Считаем по таблице visits, чтобы не было +2 при триггере в БД
    cnt = await session.execute(
        select(func.count(Visit.id)).where(Visit.guest_id == guest_id)
    )
    guest.visits_count = cnt.scalar() or 0
    guest.last_visit_at = now
    guest.updated_at = now
    reg, vip = await _get_segment_thresholds(session)
    guest.segment = calc_segment(guest.visits_count, reg, vip)

    await session.commit()
    await session.refresh(guest)
    return _guest_to_response(guest)
