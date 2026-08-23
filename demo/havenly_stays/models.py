"""
SQLAlchemy models for the Havenly Stays demo bot.

Fully separate from the production schema in src/database/models.py — this
Base and these tables live in their own Supabase project (DEMO_DATABASE_URL),
never the Cozeevo production database.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass


class Room(Base):
    __tablename__ = "rooms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    room_type: Mapped[str] = mapped_column(String(50), unique=True)
    price_monthly: Mapped[int] = mapped_column(Integer)
    total_beds: Mapped[int] = mapped_column(Integer)
    available_beds: Mapped[int] = mapped_column(Integer)
    available_from: Mapped[date] = mapped_column(Date)


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    phone: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class LeadSession(Base):
    """Tracks conversation state per phone number — drives the
    one-question-at-a-time flow. `pending_field` names the single slot
    we're waiting on; `context` holds any partially-collected data."""

    __tablename__ = "lead_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    phone: Mapped[str] = mapped_column(String(20), unique=True)
    pending_field: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    context: Mapped[dict] = mapped_column(JSON, default=dict)
    last_active_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class VisitBooking(Base):
    __tablename__ = "visit_bookings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"))
    slot_datetime: Mapped[datetime] = mapped_column(DateTime)
    calendar_event_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    lead: Mapped["Lead"] = relationship()
