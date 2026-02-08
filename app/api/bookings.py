"""Bookings API: GET list (search, date, page, limit), GET :id, POST, PATCH :id/status."""
import json
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user, require_role
from app.db.models import ActivityLog, Booking, Guest, Setting, User
from app.db.session import get_session
from app.services.guest_metrics import recalc_guest_metrics_from_bookings
from app.services.webhooks import schedule_webhook

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


class CreateGuestInline(BaseModel):
    """Данные для создания гостя при брони (если гость не найден)."""
    phone: str
    name: Optional[str] = None
    email: Optional[str] = None


class CreateBookingRequest(BaseModel):
    """guestId — существующий гость; guest — создать/найти по телефону (приоритет у guestId)."""
    guestId: Optional[int] = None
    guest: Optional[CreateGuestInline] = None
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
    """Создать бронь: guestId (существующий) или guest (найти/создать по телефону), date, time, persons."""
    guest: Optional[Guest] = None
    created_new_guest = False
    if body.guestId:
        guest_result = await session.execute(select(Guest).where(Guest.id == body.guestId))
        guest = guest_result.scalars().one_or_none()
        if not guest:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Guest not found")
    elif body.guest and body.guest.phone.strip():
        phone = body.guest.phone.strip()
        existing = await session.execute(select(Guest).where(Guest.phone == phone))
        guest = existing.scalars().one_or_none()
        if not guest:
            guest = Guest(
                phone=phone,
                name=(body.guest.name or "").strip() or None,
                email=(body.guest.email or "").strip() or None,
                segment="Новичок",
                visits_count=0,
                confirmed_bookings_count=0,
                created_at=datetime.now(timezone.utc),
            )
            session.add(guest)
            await session.flush()
            created_new_guest = True
    if not guest:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide guestId or guest.phone",
        )

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

    now = datetime.now(timezone.utc)
    booking = Booking(
        guest_id=guest.id,
        booking_time=booking_time,
        party_size=body.persons,
        status="pending",
        created_at=now,
    )
    session.add(booking)
    await session.flush()
    if created_new_guest:
        session.add(
            ActivityLog(
                user_id=current_user.id,
                action_type="guest_created",
                entity_type="guest",
                entity_id=guest.id,
                created_at=now,
            )
        )
    session.add(
        ActivityLog(
            user_id=current_user.id,
            action_type="booking_created",
            entity_type="booking",
            entity_id=booking.id,
            created_at=now,
        )
    )
    await session.commit()
    await session.refresh(booking, ["guest"])

    result = await session.execute(
        select(Setting).where(
            Setting.key.in_(("bookingWebhookUrl", "webhookUrl", "restaurant_place", "default_table_message"))
        )
    )
    by_key = {r.key: (r.value or "").strip() for r in result.scalars().all()}
    webhook_url = by_key.get("bookingWebhookUrl") or by_key.get("webhookUrl") or ""
    place = by_key.get("restaurant_place") or "CHINOR"
    table_msg = by_key.get("default_table_message") or "будет назначен"

    if webhook_url:
        payload = {
            "event": "booking_created",
            "booking_id": booking.id,
            "guest_phone": guest.phone or "",
            "guest_name": (guest.name or "").strip() or "",
            "date": date_part.strftime("%d.%m.%Y"),
            "time": t.strftime("%H:%M"),
            "party_size": booking.party_size,
            "place": place,
            "table": table_msg,
        }
        schedule_webhook(webhook_url, payload)

    return _booking_to_response(booking)


@router.patch("/bookings/{booking_id}/status", response_model=BookingResponse)
async def update_booking_status(
    booking_id: int,
    body: UpdateStatusRequest,
    current_user: User = Depends(require_role(["admin", "hostess_1", "hostess_2"])),
    session: AsyncSession = Depends(get_session),
) -> BookingResponse:
    """Обновить статус брони: pending, confirmed, canceled, no_show. При изменении статуса пересчитывается у гостя счётчик подтверждённых броней (confirmed_bookings_count) в разделе Гости; визиты и сегмент не трогаются."""
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

    old_status = (booking.status or "").strip().lower()
    new_status = (body.status or "").strip().lower()
    booking.status = new_status
    await session.flush()  # чтобы пересчёт видел новый статус в БД

    # Пересчёт у гостя: только confirmed_bookings_count и last_visit_at (по броням confirmed)
    await recalc_guest_metrics_from_bookings(session, booking.guest_id)

    now = datetime.now(timezone.utc)
    session.add(
        ActivityLog(
            user_id=current_user.id,
            action_type="booking_status_changed",
            entity_type="booking",
            entity_id=booking_id,
            details=json.dumps({"old_status": old_status, "new_status": new_status}),
            created_at=now,
        )
    )
    await session.commit()
    await session.refresh(booking, ["guest"])
    return _booking_to_response(booking)
