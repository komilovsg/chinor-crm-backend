"""Guests API: GET list (search, page, limit), GET :id, POST, PATCH :id, GET export (CSV)."""
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
from app.db.models import Guest, User
from app.db.session import get_session

router = APIRouter(prefix="/api", tags=["guests"])


class GuestResponse(BaseModel):
    id: int
    name: Optional[str]
    phone: str
    email: Optional[str]
    segment: str
    visits_count: int
    last_visit_at: Optional[str]
    created_at: str

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


def _guest_to_response(guest: Guest) -> GuestResponse:
    return GuestResponse(
        id=guest.id,
        name=guest.name,
        phone=guest.phone,
        email=guest.email,
        segment=guest.segment or "Новичок",
        visits_count=guest.visits_count or 0,
        last_visit_at=guest.last_visit_at.isoformat() if guest.last_visit_at else None,
        created_at=guest.created_at.isoformat() if guest.created_at else "",
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
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Экспорт гостей в CSV (поиск по имени/телефону)."""
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
    current_user: User = Depends(require_role(["admin", "hostess_1", "hostess_2"])),
    session: AsyncSession = Depends(get_session),
) -> GuestResponse:
    """Создать гостя. Телефон уникален. Доступ: admin, hostess_1, hostess_2."""
    existing = await session.execute(select(Guest).where(Guest.phone == body.phone.strip()))
    if existing.scalars().one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Guest with this phone already exists",
        )
    guest = Guest(
        phone=body.phone.strip(),
        name=(body.name.strip() or None) if body.name is not None else None,
        email=(body.email.strip() or None) if body.email is not None else None,
        segment="Новичок",
        visits_count=0,
        created_at=datetime.now(timezone.utc),
    )
    session.add(guest)
    await session.commit()
    await session.refresh(guest)
    return _guest_to_response(guest)


@router.patch("/guests/{guest_id}", response_model=GuestResponse)
async def update_guest(
    guest_id: int,
    body: UpdateGuestRequest,
    current_user: User = Depends(require_role(["admin", "hostess_1", "hostess_2"])),
    session: AsyncSession = Depends(get_session),
) -> GuestResponse:
    """Обновить данные гостя. Телефон должен оставаться уникальным. Доступ: admin, hostess_1, hostess_2."""
    result = await session.execute(select(Guest).where(Guest.id == guest_id))
    guest = result.scalars().one_or_none()
    if not guest or guest.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Guest not found")
    if body.phone is not None:
        phone = body.phone.strip()
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
    await session.commit()
    await session.refresh(guest)
    return _guest_to_response(guest)
