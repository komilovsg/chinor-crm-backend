"""Bookings API: GET list (search, date, page, limit), GET :id, POST, PATCH :id/status."""
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user, require_role
from app.db.models import Booking, Guest, User
from app.db.session import get_session

router = APIRouter(prefix="/api", tags=["bookings"])

ALLOWED_STATUSES = ("pending", "confirmed", "canceled", "no_show")


class GuestBrief(BaseModel):
    id: int
    name: Optional[str]
    phone: str

    class Config:
        from_attributes = True


class BookingResponse(BaseModel):
    id: int
    guest_id: int
    guest: Optional[GuestBrief] = None
    booking_time: str
    guests_count: int
    status: str
    created_at: str

    class Config:
        from_attributes = True


class PaginatedBookingsResponse(BaseModel):
    items: List[BookingResponse]
    total: int
    page: int
    limit: int


class CreateBookingRequest(BaseModel):
    guestId: int
    date: str  # YYYY-MM-DD
    time: str  # HH:MM or HH:MM:SS
    persons: int


class UpdateStatusRequest(BaseModel):
    status: str


def _booking_to_response(booking: Booking) -> BookingResponse:
    """Собрать ответ с guest (id, name, phone) и ISO-строками дат."""
    g = booking.guest
    guest_brief = GuestBrief(id=g.id, name=g.name, phone=g.phone) if g else None
    return BookingResponse(
        id=booking.id,
        guest_id=booking.guest_id,
        guest=guest_brief,
        booking_time=booking.booking_time.isoformat() if booking.booking_time else "",
        guests_count=booking.party_size,
        status=booking.status,
        created_at=(booking.created_at.isoformat() if booking.created_at else ""),
    )


@router.get("/bookings", response_model=PaginatedBookingsResponse)
async def get_bookings(
    search: Optional[str] = None,
    date: Optional[str] = None,
    page: int = 1,
    limit: int = 10,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> PaginatedBookingsResponse:
    """Список бронирований с поиском по гостю (имя/телефон), фильтром по дате, пагинацией."""
    limit = max(1, min(limit, 100))
    page = max(1, page)
    offset = (page - 1) * limit

    stmt = select(Booking).options(selectinload(Booking.guest)).order_by(Booking.booking_time.desc())
    if search and search.strip():
        search_arg = f"%{search.strip()}%"
        stmt = stmt.join(Guest, Booking.guest_id == Guest.id).where(
            or_(
                Guest.name.ilike(search_arg),
                Guest.phone.ilike(search_arg),
            )
        )
    if date:
        try:
            day = datetime.strptime(date.strip()[:10], "%Y-%m-%d").date()
        except ValueError:
            day = None
        if day is not None:
            day_start = datetime.combine(day, datetime.min.time()).replace(tzinfo=timezone.utc)
            day_end = day_start.replace(hour=23, minute=59, second=59, microsecond=999999)
            stmt = stmt.where(
                Booking.booking_time >= day_start,
                Booking.booking_time <= day_end,
            )

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await session.execute(count_stmt)
    total = (total_result.scalar() or 0)

    stmt = stmt.offset(offset).limit(limit)
    result = await session.execute(stmt)
    bookings = result.scalars().all()

    return PaginatedBookingsResponse(
        items=[_booking_to_response(b) for b in bookings],
        total=total,
        page=page,
        limit=limit,
    )


@router.get("/bookings/{booking_id}", response_model=BookingResponse)
async def get_booking(
    booking_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> BookingResponse:
    """Одна бронь по ID с данными гостя."""
    stmt = (
        select(Booking)
        .options(selectinload(Booking.guest))
        .where(Booking.id == booking_id)
    )
    result = await session.execute(stmt)
    booking = result.scalars().one_or_none()
    if not booking:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")
    return _booking_to_response(booking)


@router.post("/bookings", response_model=BookingResponse)
async def create_booking(
    body: CreateBookingRequest,
    current_user: User = Depends(require_role(["admin", "hostess_1", "hostess_2"])),
    session: AsyncSession = Depends(get_session),
) -> BookingResponse:
    """Создать бронь: guestId, date (YYYY-MM-DD), time (HH:MM), persons. Доступ: admin, hostess_1, hostess_2."""
    guest_result = await session.execute(select(Guest).where(Guest.id == body.guestId))
    guest = guest_result.scalars().one_or_none()
    if not guest:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Guest not found")

    try:
        date_part = datetime.strptime(body.date.strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid date format (use YYYY-MM-DD)")
    time_part = body.time.strip()
    if len(time_part) == 5:  # HH:MM
        time_part += ":00"
    try:
        t = datetime.strptime(time_part, "%H:%M:%S").time()
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid time format (use HH:MM or HH:MM:SS)")
    booking_time = datetime.combine(date_part, t).replace(tzinfo=timezone.utc)

    if body.persons < 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="persons must be >= 1")

    booking = Booking(
        guest_id=body.guestId,
        booking_time=booking_time,
        party_size=body.persons,
        status="pending",
        created_at=datetime.now(timezone.utc),
    )
    session.add(booking)
    await session.commit()
    await session.refresh(booking, ["guest"])
    return _booking_to_response(booking)


@router.patch("/bookings/{booking_id}/status", response_model=BookingResponse)
async def update_booking_status(
    booking_id: int,
    body: UpdateStatusRequest,
    current_user: User = Depends(require_role(["admin", "hostess_1", "hostess_2"])),
    session: AsyncSession = Depends(get_session),
) -> BookingResponse:
    """Обновить статус брони: pending, confirmed, canceled, no_show. Доступ: admin, hostess_1, hostess_2."""
    if body.status not in ALLOWED_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"status must be one of: {', '.join(ALLOWED_STATUSES)}",
        )
    stmt = select(Booking).options(selectinload(Booking.guest)).where(Booking.id == booking_id)
    result = await session.execute(stmt)
    booking = result.scalars().one_or_none()
    if not booking:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")
    booking.status = body.status
    await session.commit()
    await session.refresh(booking, ["guest"])
    return _booking_to_response(booking)
