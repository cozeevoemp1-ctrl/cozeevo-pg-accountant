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
from sqlalchemy import select, func

from src.api.v2.auth import AppUser, get_current_user
from src.database.db_manager import get_session
from src.database.models import (
    OnboardingSession, Room, Property,
    Tenant, Tenancy, Payment, TenancyStatus, StayType, PaymentMode, PaymentFor,
)
from src.services.room_occupancy import _normalize_phone

router = APIRouter(prefix="/bookings", tags=["bookings"])


class QuickBookRequest(BaseModel):
    room_number: str
    tenant_name: str
    tenant_phone: str
    checkin_date: str       # YYYY-MM-DD
    stay_type: str = "monthly"
    monthly_rent: float = 0.0
    maintenance_fee: float = 5000.0
    security_deposit: float = 0.0   # 0 = auto = monthly_rent
    daily_rate: float = 0.0
    checkout_date: str = ""         # YYYY-MM-DD, required for daily
    booking_amount: float = 0.0     # advance paid at booking
    advance_mode: str = "upi"       # "cash" | "upi" — how advance was collected
    sharing_type: str = ""          # "premium" = full room; "" = single bed
    notes: str = ""                 # stored in onboarding_sessions.special_terms


@router.post("/quick-book")
async def quick_book(req: QuickBookRequest, user: AppUser = Depends(get_current_user)):
    if user.role not in ("admin", "staff"):
        raise HTTPException(403, "Admin or staff only")

    phone = _normalize_phone(req.tenant_phone)
    if not phone or len(phone) < 10:
        raise HTTPException(400, f"Phone must be at least 10 digits (got {len(phone) if phone else 0})")

    if not req.tenant_name.strip():
        raise HTTPException(400, "Tenant name is required")

    if req.stay_type not in ("monthly", "daily"):
        raise HTTPException(400, "stay_type must be 'monthly' or 'daily'")

    if req.stay_type == "monthly" and req.monthly_rent <= 0:
        raise HTTPException(400, "Monthly rent must be > 0")

    if req.stay_type == "daily" and req.daily_rate <= 0:
        raise HTTPException(400, "Daily rate must be > 0")

    try:
        checkin = date.fromisoformat(req.checkin_date)
    except ValueError:
        raise HTTPException(400, "Invalid date format — use YYYY-MM-DD")

    checkout: date | None = None
    if req.stay_type == "daily":
        if not req.checkout_date:
            raise HTTPException(400, "checkout_date is required for daily stays")
        try:
            checkout = date.fromisoformat(req.checkout_date)
        except ValueError:
            raise HTTPException(400, "Invalid checkout_date format — use YYYY-MM-DD")
        if checkout <= checkin:
            raise HTTPException(400, "checkout_date must be after checkin_date")

    async with get_session() as session:
        # Blacklist check
        from src.services.blacklist import check_blacklisted
        bl = await check_blacklisted(session, phone=phone)
        if bl:
            raise HTTPException(403, f"This person is on the Cozeevo blacklist: {bl['reason']}")

        # Active tenancy check (blocks current residents)
        from src.services.room_occupancy import get_active_tenancy_by_phone
        existing = await get_active_tenancy_by_phone(session, phone)
        if existing:
            _et, _etn, _er = existing
            raise HTTPException(409, f"This person is currently staying in Room {_er.room_number} — cannot pre-book an existing resident.")

        # No-show tenancy check (blocks already pre-booked tenants)
        existing_noshow = (await session.execute(
            select(Tenancy, Room)
            .join(Room, Room.id == Tenancy.room_id)
            .join(Tenant, Tenant.id == Tenancy.tenant_id)
            .where(
                Tenancy.status == TenancyStatus.no_show,
                func.right(
                    func.regexp_replace(Tenant.phone, r"[^0-9]", "", "g"), 10
                ) == phone[-10:],
            )
        )).first()
        if existing_noshow:
            _ns_ten, _ns_room = existing_noshow
            ci = _ns_ten.checkin_date.strftime("%d %b %Y") if _ns_ten.checkin_date else "unknown"
            raise HTTPException(409, f"This person is already pre-booked in Room {_ns_room.room_number} (check-in {ci}).")

        # Find room
        room = await session.scalar(select(Room).where(Room.room_number.ilike(req.room_number)))
        if not room:
            raise HTTPException(404, f"Room {req.room_number} not found")

        # Reject room 000 (placeholder) — must assign a real room at booking time
        if room.room_number == "000":
            raise HTTPException(422, "Room 000 is a placeholder. Please select a specific room for this booking.")

        # Capacity check
            from src.services.room_occupancy import get_room_occupants
            occ = await get_room_occupants(session, room)
            max_occ = room.max_occupancy or 1
            if occ.beds_occupied(max_occ) >= max_occ:
                # Allow pre-booking if enough beds will be free on the requested checkin_date.
                # A bed is free if the current tenant's checkout_date < checkin_date.
                active_rows = (await session.execute(
                    select(Tenancy.checkout_date, Tenancy.expected_checkout)
                    .where(Tenancy.room_id == room.id, Tenancy.status.in_([TenancyStatus.active, TenancyStatus.no_show]))
                )).all()
                def _eff(row): return row.checkout_date or row.expected_checkout
                beds_still_occupied = sum(1 for row in active_rows if _eff(row) is None or _eff(row) >= checkin)
                if beds_still_occupied >= max_occ:
                    ends = [_eff(row) for row in active_rows if _eff(row) is not None]
                    if ends:
                        free_from = min(ends) + timedelta(days=1)
                        detail = (
                            f"Room {room.room_number} is fully booked until {min(ends).strftime('%d %b %Y')}. "
                            f"Set check-in on or after {free_from.strftime('%d %b %Y')}."
                        )
                    else:
                        detail = f"Room {room.room_number} is full with no checkout dates set — cannot pre-book."
                    raise HTTPException(409, detail)

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
        if req.stay_type == "daily":
            _sharing = req.sharing_type.strip().lower() if req.sharing_type else None
            if _sharing not in ("single", "double", "triple", "premium"):
                _sharing = None
            obs = OnboardingSession(
                token=token,
                status="pending_tenant",
                created_by_phone=user.actor,
                tenant_phone=phone,
                room_id=room.id,
                agreed_rent=Decimal("0"),
                daily_rate=Decimal(str(req.daily_rate)),
                maintenance_fee=Decimal("0"),
                security_deposit=Decimal(str(req.security_deposit)),
                booking_amount=Decimal(str(req.booking_amount)),
                advance_mode=req.advance_mode or "",
                checkin_date=checkin,
                checkout_date=checkout,
                stay_type="daily",
                sharing_type=_sharing,
                tenant_data=json.dumps({"name": req.tenant_name.strip()}),
                special_terms=req.notes.strip() or None,
                expires_at=datetime.utcnow() + timedelta(hours=48),
            )
        else:
            if req.security_deposit <= 0:
                raise HTTPException(status_code=422, detail="security_deposit is required for monthly bookings")
            deposit = req.security_deposit
            obs = OnboardingSession(
                token=token,
                status="pending_tenant",
                created_by_phone=user.actor,
                tenant_phone=phone,
                room_id=room.id,
                agreed_rent=Decimal(str(req.monthly_rent)),
                maintenance_fee=Decimal(str(req.maintenance_fee)),
                security_deposit=Decimal(str(deposit)),
                booking_amount=Decimal(str(req.booking_amount)),
                advance_mode=req.advance_mode or "",
                checkin_date=checkin,
                stay_type="monthly",
                tenant_data=json.dumps({"name": req.tenant_name.strip()}),
                special_terms=req.notes.strip() or None,
                expires_at=datetime.utcnow() + timedelta(hours=48),
            )
        session.add(obs)
        await session.flush()

        # If advance was collected at booking, create Tenant + no_show Tenancy + Payment immediately
        # so it appears in payment history and activity log before check-in.
        if req.booking_amount > 0:
            from sqlalchemy import func as _func
            from src.services.room_occupancy import _normalize_phone as _np
            _norm10 = _np(phone)
            tenant = await session.scalar(
                select(Tenant).where(
                    _func.right(_func.regexp_replace(Tenant.phone, r"[^0-9]", "", "g"), 10) == _norm10
                )
            )
            if not tenant:
                tenant = Tenant(name=req.tenant_name.strip(), phone=phone)
                session.add(tenant)
                await session.flush()

            _stay = StayType.daily if req.stay_type == "daily" else StayType.monthly
            # Status: if checkin is today or in past → active; otherwise → no_show
            _target_status = TenancyStatus.active if checkin <= date.today() else TenancyStatus.no_show
            tenancy = Tenancy(
                tenant_id=tenant.id,
                room_id=room.id,
                stay_type=_stay,
                status=_target_status,
                checkin_date=checkin,
                checkout_date=checkout,
                agreed_rent=req.monthly_rent if req.stay_type == "monthly" else 0,
                security_deposit=req.security_deposit,
                booking_amount=Decimal(str(req.booking_amount)),
                maintenance_fee=req.maintenance_fee if req.stay_type == "monthly" else 0,
                entered_by="quick_book",
            )
            session.add(tenancy)
            await session.flush()

            _mode = PaymentMode.upi if req.advance_mode == "upi" else PaymentMode.cash
            _pmt = Payment(
                tenancy_id=tenancy.id,
                amount=Decimal(str(req.booking_amount)),
                payment_date=checkin,
                payment_mode=_mode,
                for_type=PaymentFor.booking,
                notes=f"Advance collected at pre-booking ({req.advance_mode or 'cash'})",
            )
            session.add(_pmt)
            await session.flush()  # need _pmt.id for audit entry

            from src.services.audit import write_audit_entry as _wae
            await _wae(
                session=session,
                changed_by=user.actor or str(user.user_id),
                entity_type="payment", entity_id=_pmt.id,
                field="payment.log",
                new_value=str(float(req.booking_amount)),
                entity_name=req.tenant_name.strip(),
                room_number=room.room_number,
                source="pwa",
                note=f"Advance ₹{int(req.booking_amount):,} {'upi' if req.advance_mode == 'upi' else 'cash'} — pre-booking",
            )

            obs.tenant_id = tenant.id
            obs.tenancy_id = tenancy.id

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
        try:
            from src.whatsapp.webhook_handler import _send_whatsapp_template, _send_whatsapp
            room_line = f"Room *{room.room_number}*" + (f" ({building})" if building else "")
            if req.stay_type == "daily":
                assert checkout is not None
                rate_str = f"Rs.{int(req.daily_rate):,}/night"
                try:
                    await _send_whatsapp_template(
                        phone_wa, "cozeevo_checkin_form",
                        [str(room.room_number), rate_str, onboard_link],
                    )
                    whatsapp_sent = True
                except Exception:
                    nights = (checkout - checkin).days
                    msg = (
                        f"Hello {req.tenant_name.strip()}! Welcome to *Cozeevo Co-living*\n\n"
                        f"{room_line}\n"
                        f"Rate: {rate_str}\n"
                        f"Check-in: {checkin.strftime('%d %b %Y')}\n"
                        f"Check-out: {checkout.strftime('%d %b %Y')} ({nights} night{'s' if nights != 1 else ''})\n\n"
                        f"Please complete your registration:\n{onboard_link}\n\n"
                        "This link is valid for 48 hours."
                    )
                    await _send_whatsapp(phone_wa, msg)
                    whatsapp_sent = True
            else:
                rent_str = f"Rs.{int(req.monthly_rent):,}"
                try:
                    await _send_whatsapp_template(
                        phone_wa, "cozeevo_checkin_form",
                        [str(room.room_number), rent_str, onboard_link],
                    )
                    whatsapp_sent = True
                except Exception:
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
