"""Quick pre-booking from the PWA vacant beds panel.

POST /api/v2/app/bookings/quick-book
  Admin taps a vacant room → fills name/phone/date/rent → session created + WhatsApp sent.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, date, timedelta
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy import select

from src.api.v2.auth import AppUser, get_current_user
from src.database.db_manager import get_session
from src.database.models import OnboardingSession, Room, Property

router = APIRouter(prefix="/bookings", tags=["bookings"])


class QuickBookRequest(BaseModel):
    room_number: str
    tenant_name: str
    tenant_phone: str
    checkin_date: str   # YYYY-MM-DD
    monthly_rent: float


@router.post("/quick-book")
async def quick_book(req: QuickBookRequest, user: AppUser = Depends(get_current_user)):
    if user.role != "admin":
        raise HTTPException(403, "Admin only")

    phone_digits = re.sub(r"\D", "", req.tenant_phone)
    if len(phone_digits) < 10:
        raise HTTPException(400, f"Phone must be at least 10 digits (got {len(phone_digits)})")
    phone = phone_digits[-10:]

    if not req.tenant_name.strip():
        raise HTTPException(400, "Tenant name is required")

    if req.monthly_rent <= 0:
        raise HTTPException(400, "Monthly rent must be > 0")

    try:
        checkin = date.fromisoformat(req.checkin_date)
    except ValueError:
        raise HTTPException(400, "Invalid date format — use YYYY-MM-DD")

    async with get_session() as session:
        # Blacklist check
        from src.services.blacklist import check_blacklisted
        bl = await check_blacklisted(session, phone=phone)
        if bl:
            raise HTTPException(403, f"This person is on the Cozeevo blacklist: {bl['reason']}")

        # Active tenancy check
        from src.services.room_occupancy import get_active_tenancy_by_phone
        existing = await get_active_tenancy_by_phone(session, phone)
        if existing:
            _et, _etn, _er = existing
            raise HTTPException(409, f"Phone {phone} already has an active tenancy in Room {_er.room_number}")

        # Find room
        room = await session.scalar(select(Room).where(Room.room_number.ilike(req.room_number)))
        if not room:
            raise HTTPException(404, f"Room {req.room_number} not found")

        # Capacity check
        from src.services.room_occupancy import get_room_occupants
        occ = await get_room_occupants(session, room)
        if occ.total_occupied >= (room.max_occupancy or 1):
            raise HTTPException(409, f"Room {room.room_number} is full ({occ.total_occupied}/{room.max_occupancy} beds)")

        # Cancel old pending sessions for the same phone
        old = await session.execute(
            select(OnboardingSession).where(
                OnboardingSession.tenant_phone == phone,
                OnboardingSession.status.in_(["pending_tenant", "pending_review"]),
            )
        )
        for old_obs in old.scalars().all():
            old_obs.status = "cancelled"

        # Create session — pre-fill name in tenant_data so Bookings page shows it immediately
        token = str(uuid.uuid4())
        obs = OnboardingSession(
            token=token,
            status="pending_tenant",
            created_by_phone=user.phone or "",
            tenant_phone=phone,
            room_id=room.id,
            agreed_rent=Decimal(str(req.monthly_rent)),
            security_deposit=Decimal("0"),
            checkin_date=checkin,
            stay_type="monthly",
            tenant_data=json.dumps({"name": req.tenant_name.strip()}),
            expires_at=datetime.utcnow() + timedelta(hours=48),
        )
        session.add(obs)
        await session.flush()

        # Building name for WhatsApp message
        building = ""
        if room.property_id:
            prop = await session.get(Property, room.property_id)
            building = prop.name if prop else ""

        await session.commit()

        # Send WhatsApp (template first, fall back to freeform)
        base_url = os.getenv("BASE_URL", "https://api.getkozzy.com")
        onboard_link = f"{base_url}/onboard/{token}"
        whatsapp_sent = False
        phone_wa = f"91{phone}"
        rent_str = f"Rs.{int(req.monthly_rent):,}"
        try:
            from src.whatsapp.webhook_handler import _send_whatsapp_template, _send_whatsapp
            try:
                await _send_whatsapp_template(
                    phone_wa, "cozeevo_checkin_form",
                    [room.room_number, rent_str, onboard_link],
                )
                whatsapp_sent = True
            except Exception:
                room_line = f"Room *{room.room_number}*" + (f" ({building})" if building else "")
                msg = (
                    f"Hello {req.tenant_name.strip()}! Welcome to *Cozeevo Co-living*\n\n"
                    f"{room_line}\n"
                    f"Rent: {rent_str}/month\n"
                    f"Check-in: {checkin.strftime('%d %b %Y')}\n\n"
                    f"Please complete your registration:\n{onboard_link}\n\n"
                    "This link is valid for 48 hours."
                )
                await _send_whatsapp(phone_wa, msg)
                whatsapp_sent = True
        except Exception:
            pass  # Booking succeeds even if WhatsApp fails

        return {
            "token": token,
            "session_id": obs.id,
            "whatsapp_sent": whatsapp_sent,
            "form_url": onboard_link,
        }
