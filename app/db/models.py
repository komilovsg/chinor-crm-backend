"""Модели SQLAlchemy: соответствие схеме БД Railway (guests, bookings, visits, campaigns, ...) и таблицы users, settings."""
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Базовый класс для всех моделей."""

    pass


# ——— Существующие таблицы Railway ———

class Guest(Base):
    __tablename__ = "guests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    phone: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    wa_id: Mapped[Optional[str]] = mapped_column(String(50), unique=True)
    name: Mapped[Optional[str]] = mapped_column(String(255))
    email: Mapped[Optional[str]] = mapped_column(String(255))
    source: Mapped[Optional[str]] = mapped_column(String(50))
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_visit_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_interaction_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    visits_count: Mapped[int] = mapped_column(Integer, default=0)
    total_revenue: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    segment: Mapped[str] = mapped_column(String(50), default="Новичок")
    is_in_stop_list: Mapped[bool] = mapped_column(Boolean, default=False)
    consent_marketing: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    bookings: Mapped[list["Booking"]] = relationship("Booking", back_populates="guest")


class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guest_id: Mapped[int] = mapped_column(ForeignKey("guests.id"), nullable=False)
    booking_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    guests_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    admin_notes: Mapped[Optional[str]] = mapped_column(Text)
    reminded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    alerted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    no_show_alerted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    guest: Mapped["Guest"] = relationship("Guest", back_populates="bookings")


class Visit(Base):
    __tablename__ = "visits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    booking_id: Mapped[Optional[int]] = mapped_column(ForeignKey("bookings.id"))
    guest_id: Mapped[int] = mapped_column(ForeignKey("guests.id"), nullable=False)
    arrived_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    left_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    revenue: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    admin_notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    visit_id: Mapped[int] = mapped_column(ForeignKey("visits.id"), nullable=False)
    booking_id: Mapped[Optional[int]] = mapped_column(ForeignKey("bookings.id"))
    guest_id: Mapped[int] = mapped_column(ForeignKey("guests.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="requested")
    rating: Mapped[Optional[int]] = mapped_column(Integer)
    message: Mapped[Optional[str]] = mapped_column(Text)
    review_url: Mapped[Optional[str]] = mapped_column(String(500))
    message_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    scheduled_for: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    message_text: Mapped[str] = mapped_column(Text, nullable=False)
    target_segment: Mapped[Optional[str]] = mapped_column(String(50))
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class CampaignSend(Base):
    __tablename__ = "campaign_sends"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"), nullable=False)
    guest_id: Mapped[int] = mapped_column(ForeignKey("guests.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class WhatsappMessage(Base):
    __tablename__ = "whatsapp_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guest_id: Mapped[Optional[int]] = mapped_column(ForeignKey("guests.id"))
    message_type: Mapped[Optional[str]] = mapped_column(String(50))
    message_text: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[Optional[str]] = mapped_column(String(50))
    external_message_id: Mapped[Optional[str]] = mapped_column(String(255))
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class AdminAlert(Base):
    __tablename__ = "admin_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    alert_type: Mapped[Optional[str]] = mapped_column(String(100))
    booking_id: Mapped[Optional[int]] = mapped_column(ForeignKey("bookings.id"))
    guest_id: Mapped[Optional[int]] = mapped_column(ForeignKey("guests.id"))
    message: Mapped[Optional[str]] = mapped_column(Text)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


# ——— Таблицы для CRM (auth + настройки), создаются миграциями B3 ———

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False)  # admin, hostess_1, hostess_2
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class Setting(Base):
    """Key-value настройки (pushNotifications, webhookUrl, autoBackup и др.)."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[Optional[str]] = mapped_column(Text)  # JSON string для сложных значений
