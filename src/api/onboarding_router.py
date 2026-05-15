"""
src/api/onboarding_router.py
Onboarding form API — receptionist creates session, tenant fills, receptionist approves.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, date
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from typing import Optional

from src.database.db_manager import get_session
from src.database.models import (
    OnboardingSession, Room, Property, Tenant, Tenancy, TenancyStatus, StayType,
    RentSchedule, RentStatus, Payment, PaymentMode, PaymentFor, AuthorizedUser,
    RentRevision,
)
from src.services.pdf_generator import HOUSE_RULES

router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])

# ── Security: Rate limiting + Admin auth ────────────────────────────────────

ADMIN_PIN = os.getenv("ONBOARDING_ADMIN_PIN", "cozeevo2026")
# Per-file cap: 10MB base64 ≈ 7.3MB raw. Matches the client-side 10MB guard.
# Aggregate stays well under the 200MB nginx cap on /etc/nginx/sites-enabled/pg-accountant.
MAX_UPLOAD_SIZE = 10 * 1024 * 1024

# Simple in-memory rate limiter
_rate_limits: dict[str, list[float]] = defaultdict(list)

def _rate_check(key: str, max_requests: int, window_secs: int):
    """Raise 429 if key exceeds max_requests in window_secs."""
    now = time.time()
    hits = _rate_limits[key]
    # Prune old entries
    _rate_limits[key] = [t for t in hits if now - t < window_secs]
    if len(_rate_limits[key]) >= max_requests:
        raise HTTPException(429, "Too many requests. Please wait and try again.")
    _rate_limits[key].append(now)

def _check_admin_pin(request: Request):
    """Check admin PIN from header or query param."""
    pin = request.headers.get("X-Admin-Pin") or request.query_params.get("pin")
    if pin != ADMIN_PIN:
        raise HTTPException(403, "Invalid admin PIN")


# ── Pydantic models ──────────────────────────────────────────────────────────

class CreateSessionRequest(BaseModel):
    room_number: str = ""  # Optional — for future check-ins, room can be assigned later
    sharing_type: str = ""  # single/double/triple — override room default
    agreed_rent: float
    security_deposit: float = 0
    maintenance_fee: float = 0
    booking_amount: float = 0
    advance_mode: str = ""
    checkin_date: str  # ISO YYYY-MM-DD
    stay_type: str = "monthly"
    lock_in_months: int = 0
    # Daily stay fields
    checkout_date: str = ""
    num_days: int = 0
    daily_rate: float = 0
    special_terms: str = ""
    tenant_phone: str
    created_by_phone: str = ""
    future_rent: float = 0
    future_rent_after_months: int = 0


class TenantSubmitRequest(BaseModel):
    name: str
    phone: str
    gender: str
    date_of_birth: str = ""
    age: str = ""
    email: str = ""
    food_preference: str
    father_name: str = ""
    father_phone: str = ""
    emergency_contact_name: str
    emergency_contact_phone: str
    emergency_contact_relationship: str
    permanent_address: str = ""
    occupation: str = ""
    educational_qualification: str = ""
    office_address: str = ""
    office_phone: str = ""
    id_proof_type: str = ""
    id_proof_number: str = ""
    id_photo: str = ""       # base64 image or PDF data URL
    selfie_photo: str = ""   # base64 image data URL
    signature_image: str     # base64 PNG


# ── Create session (receptionist) ────────────────────────────────────────────

@router.get("/room-lookup/{room_number}")
async def room_lookup(room_number: str, request: Request):
    _check_admin_pin(request)
    _rate_check(f"lookup:{request.client.host}", 30, 60)  # 30/min
    """Look up room info + live occupancy for the create form."""
    async with get_session() as session:
        room = await session.scalar(select(Room).where(Room.room_number.ilike(room_number)))
        if not room:
            raise HTTPException(404, "Room not found")
        building = ""
        if room.property_id:
            prop = await session.get(Property, room.property_id)
            building = prop.name if prop else ""
        rt = room.room_type
        sharing = rt.value if hasattr(rt, 'value') else str(rt or "")

        from src.services.room_occupancy import get_room_occupants
        occ = await get_room_occupants(session, room)
        occupant_names = [t.name for t, _ in occ.tenancies] + [tc.tenant.name for tc in occ.daywise if tc.tenant]
        max_occ = room.max_occupancy or 1

        return {
            "room_number": room.room_number,
            "building": building,
            "floor": str(room.floor or ""),
            "sharing": sharing,
            "max_occupancy": max_occ,
            "occupied": occ.total_occupied,
            "is_full": occ.total_occupied >= max_occ,
            "occupants": occupant_names,
        }


@router.post("/create")
async def create_session(req: CreateSessionRequest, request: Request):
    _check_admin_pin(request)
    _rate_check(f"create:{request.client.host}", 10, 60)  # 10/min

    # Phone must have exactly 10 digits after stripping country code/punctuation
    import re as _re
    _phone_digits = _re.sub(r"\D", "", req.tenant_phone or "")
    if len(_phone_digits) < 10:
        raise HTTPException(
            400,
            f"Tenant phone must be at least 10 digits — got {len(_phone_digits)} "
            f"from '{req.tenant_phone}'. Enter 10-digit number without country code."
        )

    if req.booking_amount > 0 and not req.advance_mode:
        raise HTTPException(400, "Payment method (cash/upi) required when booking amount > 0")

    # Floor checks
    if req.agreed_rent <= 0:
        raise HTTPException(422, "agreed_rent must be > 0")
    if req.security_deposit < 0:
        raise HTTPException(422, "security_deposit cannot be negative")
    if req.maintenance_fee < 0:
        raise HTTPException(422, "maintenance_fee cannot be negative")
    if req.daily_rate < 0:
        raise HTTPException(422, "daily_rate cannot be negative")

    async with get_session() as session:
        # Auto-cancel old pending sessions for same tenant phone
        if req.tenant_phone:
            old = await session.execute(
                select(OnboardingSession).where(
                    OnboardingSession.tenant_phone == req.tenant_phone,
                    OnboardingSession.status.in_(["pending_tenant", "pending_review"])
                )
            )
            for old_obs in old.scalars().all():
                old_obs.status = "cancelled"
                old_obs.cancellation_reason = "superseded"

        # Blacklist check (phone only at create time — name comes in at KYC submit)
        from src.services.blacklist import check_blacklisted as _check_bl
        _bl = await _check_bl(session, phone=req.tenant_phone)
        if _bl:
            raise HTTPException(
                403,
                f"This person is on the Cozeevo blacklist: {_bl['reason']}. "
                "Contact Kiran if this is a mistake."
            )

        # Hard-block if this phone already has an active tenancy anywhere
        if req.tenant_phone:
            from src.services.room_occupancy import get_active_tenancy_by_phone
            existing_active = await get_active_tenancy_by_phone(session, req.tenant_phone)
            if existing_active:
                _et, _etn, _er = existing_active
                raise HTTPException(
                    409,
                    f"Phone {req.tenant_phone} already has an active tenancy for "
                    f"{_et.name} in Room {_er.room_number}. "
                    "Checkout their current room first, or use a different phone number."
                )

        # Lookup room if provided, otherwise allow future room assignment
        room = None
        building = ""
        if req.room_number and req.room_number.strip():
            room = await session.scalar(select(Room).where(Room.room_number.ilike(req.room_number)))
            if not room:
                raise HTTPException(404, f"Room {req.room_number} not found")
            if room.property_id:
                prop = await session.get(Property, room.property_id)
                building = prop.name if prop else ""
            # Capacity check at session-create time — warn receptionist before sending link
            from src.services.room_occupancy import get_room_occupants
            occ = await get_room_occupants(session, room)
            if occ.total_occupied >= (room.max_occupancy or 1):
                occ_names = [t.name for t, _ in occ.tenancies] + [d.tenant.name for d in occ.daywise]
                raise HTTPException(
                    409,
                    f"Room {room.room_number} is full "
                    f"({occ.total_occupied}/{room.max_occupancy} beds — "
                    f"{', '.join(occ_names)}). "
                    "Checkout an existing tenant or choose a different room."
                )

        token = str(uuid.uuid4())
        obs = OnboardingSession(
            token=token,
            status="pending_tenant",
            created_by_phone=req.created_by_phone,
            tenant_phone=req.tenant_phone,
            room_id=room.id if room else None,
            agreed_rent=Decimal(str(req.agreed_rent)),
            security_deposit=Decimal(str(req.security_deposit)),
            maintenance_fee=Decimal(str(req.maintenance_fee)),
            booking_amount=Decimal(str(req.booking_amount)),
            advance_mode=req.advance_mode if req.booking_amount > 0 else "",
            sharing_type=(req.sharing_type or "").strip().lower() or None,
            checkin_date=date.fromisoformat(req.checkin_date),
            stay_type=req.stay_type,
            lock_in_months=req.lock_in_months,
            checkout_date=date.fromisoformat(req.checkout_date) if req.checkout_date else None,
            num_days=req.num_days,
            daily_rate=Decimal(str(req.daily_rate)) if req.daily_rate else 0,
            special_terms=req.special_terms,
            expires_at=datetime.utcnow() + timedelta(hours=48),
            future_rent=Decimal(str(req.future_rent)) if req.future_rent else None,
            future_rent_after_months=req.future_rent_after_months if req.future_rent_after_months else None,
        )
        session.add(obs)
        await session.flush()

        # Determine sharing type (from override, room master data, or request param)
        sharing = req.sharing_type if req.sharing_type else (
            (room.room_type.value if hasattr(room.room_type, 'value') else str(room.room_type)) if room else ""
        )

        # Calculate dues
        # Monthly stay: first-month rent is prorated by default on check-in date.
        # Daily stay: agreed_rent already holds the total stay amount — no proration.
        # Deposit already includes maintenance — don't double count.
        from src.services.rent_schedule import prorated_first_month_rent
        checkin_for_dues = date.fromisoformat(req.checkin_date)
        if req.stay_type == "monthly":
            first_month_rent = float(prorated_first_month_rent(req.agreed_rent, checkin_for_dues))
        else:
            first_month_rent = float(req.agreed_rent)
        total_due = float(first_month_rent + req.security_deposit - req.booking_amount)
        dues_due = max(0, total_due)

        # Auto-send onboarding link to tenant via WhatsApp
        base_url = os.getenv("BASE_URL", "https://api.getkozzy.com")
        onboard_link = f"{base_url}/onboard/{token}"
        whatsapp_sent = False
        if req.tenant_phone:
            try:
                from src.whatsapp.webhook_handler import _send_whatsapp_template, _send_whatsapp
                phone_wa = req.tenant_phone.strip()
                if not phone_wa.startswith("91"):
                    phone_wa = "91" + phone_wa
                rent_str = f"Rs.{int(req.agreed_rent):,}" if req.agreed_rent else "Rs.0"

                # Try template first if room is assigned (works without 24hr window)
                if room:
                    try:
                        await _send_whatsapp_template(
                            phone_wa, "cozeevo_checkin_form",
                            [room.room_number, rent_str, onboard_link]
                        )
                        whatsapp_sent = True
                    except Exception:
                        pass  # Fall through to regular message

                # Fallback to regular message (needs 24hr window, or room not yet assigned)
                if not whatsapp_sent:
                    summary_lines = [f"Hello! Welcome to *Cozeevo Co-living*\n"]
                    if room:
                        summary_lines.append(f"Room *{room.room_number}* ({building}) — {sharing}")
                    rent_line = f"Rent: {rent_str}/month"
                    if req.future_rent and req.future_rent_after_months:
                        future_str = f"Rs.{int(req.future_rent):,}"
                        _ci = date.fromisoformat(req.checkin_date)
                        _N = req.future_rent_after_months
                        _MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
                        _eff = _MONTHS[(_ci.month - 1 + _N) % 12]
                        rent_line += f" → {future_str}/month from {_eff}"
                    summary_lines.append(rent_line)
                    summary_lines.append(f"\nPlease complete your registration:\n{onboard_link}")
                    summary_lines.append(f"\nThis link is valid for 48 hours.")
                    await _send_whatsapp(phone_wa, "\n".join(summary_lines))
                    whatsapp_sent = True
            except Exception as e:
                import logging, traceback
                logger = logging.getLogger(__name__)
                logger.error("WhatsApp onboarding link send FAILED for %s: %s\n%s",
                            req.tenant_phone, e, traceback.format_exc())

        return {
            "token": token,
            "link": f"/onboard/{token}",
            "full_link": onboard_link,
            "session_id": obs.id,
            "whatsapp_sent": whatsapp_sent,
            "dues_due": dues_due,
            "room": {
                "number": room.room_number if room else "TBD",
                "building": building if room else "",
                "floor": str(room.floor or "") if room else "",
                "sharing": sharing
            },
            "warning": None,
        }


# ── [REMOVED] Direct check-in endpoint was removed 2026-05-13.
# All check-ins now go through the booking/onboarding form flow.
# Use POST /create to start a session, or GET /qr?building=THOR for walk-ins.

@router.post("/direct-checkin")
async def direct_checkin_removed(_request: Request):
    """Removed 2026-05-13 — all check-ins go through the booking/form flow."""
    raise HTTPException(status_code=410, detail="Direct check-in removed. Use POST /create to start a session.")


# ── List pending sessions (admin) ────────────────────────────────────────────

@router.get("/admin/stats")
async def onboarding_stats(request: Request, date_from: str = "", date_to: str = ""):
    _check_admin_pin(request)
    """Onboarding stats with optional date filter."""
    from sqlalchemy import func
    async with get_session() as session:
        q = select(OnboardingSession.status, func.count()).group_by(OnboardingSession.status)
        if date_from:
            q = q.where(OnboardingSession.created_at >= date.fromisoformat(date_from))
        if date_to:
            q = q.where(OnboardingSession.created_at < date.fromisoformat(date_to) + timedelta(days=1))
        result = await session.execute(q)
        counts = {row[0]: row[1] for row in result.all()}

        # Today's approved count
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_q = select(func.count()).where(
            OnboardingSession.status == "approved",
            OnboardingSession.approved_at >= today_start
        )
        today_approved = await session.scalar(today_q) or 0

        return {
            "total": sum(counts.values()),
            "approved": counts.get("approved", 0),
            "pending_tenant": counts.get("pending_tenant", 0),
            "pending_review": counts.get("pending_review", 0),
            "cancelled": counts.get("cancelled", 0),
            "expired": counts.get("expired", 0),
            "today_approved": today_approved,
        }


@router.get("/admin/all")
async def list_all_sessions(request: Request, status: str = "", date_from: str = "", date_to: str = ""):
    """List all sessions with optional filters. Superseded sessions hidden by default.
    pending_tenant sessions past their expires_at are lazily shown as expired."""
    _check_admin_pin(request)
    from sqlalchemy import or_
    now = datetime.utcnow()
    async with get_session() as session:
        q = select(OnboardingSession).order_by(OnboardingSession.created_at.desc())
        not_superseded = (
            (OnboardingSession.cancellation_reason == None) |
            (OnboardingSession.cancellation_reason != "superseded")
        )
        if status == "superseded":
            q = q.where(OnboardingSession.cancellation_reason == "superseded")
        elif status == "expired":
            # Match both DB-expired and pending_tenant sessions that have since expired
            q = q.where(not_superseded)
            q = q.where(or_(
                OnboardingSession.status == "expired",
                (OnboardingSession.status == "pending_tenant") &
                (OnboardingSession.expires_at != None) &
                (OnboardingSession.expires_at < now),
            ))
        elif status:
            q = q.where(OnboardingSession.status == status)
            q = q.where(not_superseded)
            q = q.where(OnboardingSession.status != "draft")
            # When filtering "pending_tenant", exclude those that have silently expired
            if status == "pending_tenant":
                q = q.where(
                    (OnboardingSession.expires_at == None) |
                    (OnboardingSession.expires_at >= now)
                )
        else:
            q = q.where(not_superseded)
            q = q.where(OnboardingSession.status != "draft")
        if date_from:
            q = q.where(OnboardingSession.created_at >= date.fromisoformat(date_from))
        if date_to:
            q = q.where(OnboardingSession.created_at < date.fromisoformat(date_to) + timedelta(days=1))
        result = await session.execute(q.limit(100))
        sessions = result.scalars().all()
        items = []
        for obs in sessions:
            room = await session.get(Room, obs.room_id) if obs.room_id else None
            td = json.loads(obs.tenant_data) if obs.tenant_data else {}
            # Lazily compute effective status — pending sessions past expiry show as expired
            effective_status = obs.status
            if obs.status == "pending_tenant" and obs.expires_at and obs.expires_at < now:
                effective_status = "expired"
            # Checkin status: read from linked tenancy
            checkin_status = ""
            if obs.tenancy_id:
                tenancy = await session.get(Tenancy, obs.tenancy_id)
                if tenancy:
                    checkin_status = tenancy.status.value if tenancy.status else ""
            # How long ago the link expired (for expired sessions)
            expired_ago = ""
            if effective_status == "expired" and obs.expires_at:
                delta = now - obs.expires_at
                hours = int(delta.total_seconds() // 3600)
                if hours < 24:
                    expired_ago = f"{hours}h ago"
                else:
                    expired_ago = f"{hours // 24}d ago"
            items.append({
                "token": obs.token,
                "status": effective_status,
                "db_status": obs.status,
                "cancellation_reason": obs.cancellation_reason or "",
                "room": room.room_number if room else "",
                "tenant_phone": obs.tenant_phone,
                "tenant_name": td.get("name", ""),
                "checkin_date": obs.checkin_date.isoformat() if obs.checkin_date else "",
                "created_at": obs.created_at.isoformat() if obs.created_at else "",
                "approved_at": obs.approved_at.isoformat() if obs.approved_at else "",
                "approved_by_phone": obs.approved_by_phone or "",
                "agreed_rent": float(obs.agreed_rent or 0),
                "checkin_status": checkin_status,
                "expires_at": obs.expires_at.isoformat() if obs.expires_at else "",
                "expired_ago": expired_ago,
            })
        return {"sessions": items}


@router.get("/admin/{token}/detail")
async def get_session_detail(token: str, request: Request):
    """Full detail for any session status — used by admin dashboard expand."""
    _check_admin_pin(request)
    async with get_session() as session:
        obs = await session.scalar(select(OnboardingSession).where(OnboardingSession.token == token))
        if not obs:
            raise HTTPException(404, "Session not found")

        room = await session.get(Room, obs.room_id) if obs.room_id else None
        building = ""
        if room and room.property_id:
            prop = await session.get(Property, room.property_id)
            building = prop.name if prop else ""
        rt = room.room_type if room else None
        sharing = rt.value if hasattr(rt, "value") else str(rt or "")

        # Resolve approved_by name from AuthorizedUser table
        approved_by_name = obs.approved_by_phone or ""
        if obs.approved_by_phone:
            staff = await session.scalar(
                select(AuthorizedUser).where(AuthorizedUser.phone == obs.approved_by_phone)
            )
            if staff and staff.name:
                approved_by_name = f"{staff.name} ({obs.approved_by_phone})"

        td = json.loads(obs.tenant_data) if obs.tenant_data else {}
        return {
            "status": obs.status,
            "token": obs.token,
            "stay_type": obs.stay_type or "monthly",
            "room": {
                "number": room.room_number if room else "",
                "building": building,
                "floor": str(room.floor or "") if room else "",
                "sharing": sharing,
            },
            "agreed_rent": float(obs.agreed_rent or 0),
            "security_deposit": float(obs.security_deposit or 0),
            "maintenance_fee": float(obs.maintenance_fee or 0),
            "booking_amount": float(obs.booking_amount or 0),
            "advance_mode": obs.advance_mode or "",
            "checkin_date": obs.checkin_date.isoformat() if obs.checkin_date else "",
            "lock_in_months": obs.lock_in_months or 0,
            "special_terms": obs.special_terms or "",
            "sharing_type": obs.sharing_type or "",
            "tenant_data": td,
            "signature_image": obs.signature_image or "",
            "agreement_pdf_path": obs.agreement_pdf_path or "",
            "checkout_date": obs.checkout_date.isoformat() if obs.checkout_date else "",
            "num_days": obs.num_days or 0,
            "daily_rate": float(obs.daily_rate or 0),
            "future_rent": float(obs.future_rent or 0) if obs.future_rent else 0,
            "future_rent_after_months": obs.future_rent_after_months or 0,
            "created_by_phone": obs.created_by_phone or "",
            "approved_by_phone": obs.approved_by_phone or "",
            "approved_by_name": approved_by_name,
            "created_at": obs.created_at.isoformat() if obs.created_at else "",
            "approved_at": obs.approved_at.isoformat() if obs.approved_at else "",
            "completed_at": obs.completed_at.isoformat() if obs.completed_at else "",
        }


@router.get("/admin/pending")
async def list_pending(request: Request):
    _check_admin_pin(request)
    now = datetime.utcnow()
    async with get_session() as session:
        result = await session.execute(
            select(OnboardingSession).where(
                OnboardingSession.status.in_(["pending_tenant", "pending_review", "expired"])
            ).order_by(OnboardingSession.created_at.desc()).limit(100)
        )
        sessions = result.scalars().all()
        items = []
        for obs in sessions:
            room = await session.get(Room, obs.room_id) if obs.room_id else None
            td = json.loads(obs.tenant_data) if obs.tenant_data else {}
            # Lazily compute effective status
            effective_status = obs.status
            if obs.status == "pending_tenant" and obs.expires_at and obs.expires_at < now:
                effective_status = "expired"
            expired_ago = ""
            if effective_status == "expired" and obs.expires_at:
                delta = now - obs.expires_at
                hours = int(delta.total_seconds() // 3600)
                expired_ago = f"{hours}h ago" if hours < 24 else f"{hours // 24}d ago"
            items.append({
                "token": obs.token,
                "status": effective_status,
                "room": room.room_number if room else "",
                "tenant_phone": obs.tenant_phone,
                "checkin_date": obs.checkin_date.isoformat() if obs.checkin_date else "",
                "created_at": obs.created_at.isoformat() if obs.created_at else "",
                "tenant_name": td.get("name", ""),
                "agreed_rent": float(obs.agreed_rent or 0),
                "maintenance_fee": float(obs.maintenance_fee or 0),
                "security_deposit": float(obs.security_deposit or 0),
                "booking_amount": float(obs.booking_amount or 0),
                "daily_rate": float(obs.daily_rate or 0) if hasattr(obs, "daily_rate") else 0,
                "stay_type": obs.stay_type or "monthly",
                "tenancy_id": obs.tenancy_id,
                "expires_at": obs.expires_at.isoformat() if obs.expires_at else "",
                "expired_ago": expired_ago,
                "is_qr": (obs.created_by_phone or "") == "qr_scan",
            })
        return {"sessions": items}


# ── Cancel session (admin) ─────────────────────────────────────────────────────

class UpdateSessionRequest(BaseModel):
    agreed_rent: Optional[float] = None
    checkin_date: Optional[str] = None   # YYYY-MM-DD
    room_number: Optional[str] = None
    maintenance_fee: Optional[float] = None
    security_deposit: Optional[float] = None
    booking_amount: Optional[float] = None  # advance / token payment
    advance_mode: Optional[str] = None      # "cash" | "upi"
    tenant_phone: Optional[str] = None
    tenant_name: Optional[str] = None


@router.patch("/admin/{token}")
async def update_session(token: str, req: UpdateSessionRequest, request: Request):
    """Edit a pending_tenant or pending_review session before check-in."""
    import re as _re
    _check_admin_pin(request)
    async with get_session() as session:
        obs = await session.scalar(select(OnboardingSession).where(OnboardingSession.token == token))
        if not obs:
            raise HTTPException(404, "Session not found")
        if obs.status not in ("pending_tenant", "pending_review"):
            raise HTTPException(400, f"Cannot edit — status is {obs.status}")

        if req.agreed_rent is not None:
            obs.agreed_rent = Decimal(str(req.agreed_rent))
        if req.checkin_date is not None:
            obs.checkin_date = date.fromisoformat(req.checkin_date)
        if req.room_number is not None:
            room = await session.scalar(select(Room).where(Room.room_number.ilike(req.room_number)))
            if not room:
                raise HTTPException(404, f"Room {req.room_number} not found")
            obs.room_id = room.id
        if req.maintenance_fee is not None:
            obs.maintenance_fee = Decimal(str(req.maintenance_fee))
        if req.security_deposit is not None:
            obs.security_deposit = Decimal(str(req.security_deposit))
        if req.booking_amount is not None:
            obs.booking_amount = Decimal(str(req.booking_amount))
        if req.advance_mode is not None:
            obs.advance_mode = req.advance_mode
        if req.tenant_phone is not None:
            digits = _re.sub(r"\D", "", req.tenant_phone)
            if len(digits) < 10:
                raise HTTPException(400, "Phone must be at least 10 digits")
            obs.tenant_phone = digits[-10:]
        if req.tenant_name is not None:
            data = json.loads(obs.tenant_data) if obs.tenant_data else {}
            data["name"] = req.tenant_name.strip()
            obs.tenant_data = json.dumps(data)

        await session.commit()
        return {"ok": True, "token": token}


@router.post("/admin/{token}/cancel")
async def cancel_session(token: str, request: Request):
    _check_admin_pin(request)
    async with get_session() as session:
        obs = await session.scalar(select(OnboardingSession).where(OnboardingSession.token == token))
        if not obs:
            raise HTTPException(404, "Session not found")
        if obs.status in ("approved", "cancelled"):
            raise HTTPException(400, f"Cannot cancel — status is {obs.status}")
        obs.status = "cancelled"
        await session.commit()
        return {"status": "cancelled", "token": token}


# ── Resend WhatsApp link (admin) ───────────────────────────────────────────────

@router.post("/admin/{token}/resend")
async def resend_link(token: str, request: Request):
    _check_admin_pin(request)
    async with get_session() as session:
        obs = await session.scalar(select(OnboardingSession).where(OnboardingSession.token == token))
        if not obs:
            raise HTTPException(404, "Session not found")

        is_expired = obs.status == "expired" or (
            obs.status == "pending_tenant"
            and obs.expires_at is not None
            and obs.expires_at < datetime.utcnow()
        )

        if obs.status not in ("pending_tenant", "pending_review", "expired") and not is_expired:
            raise HTTPException(400, f"Cannot resend — status is {obs.status}")

        # For expired sessions: reset so tenant can fill again
        if is_expired or obs.status == "expired":
            obs.status = "pending_tenant"
            obs.expires_at = datetime.utcnow() + timedelta(hours=48)

        base_url = os.getenv("BASE_URL", "https://api.getkozzy.com")
        onboard_link = f"{base_url}/onboard/{token}"

        if not obs.tenant_phone:
            raise HTTPException(400, "No tenant phone on this session")

        from src.whatsapp.webhook_handler import _send_whatsapp
        phone_wa = obs.tenant_phone.strip()
        if not phone_wa.startswith("91"):
            phone_wa = "91" + phone_wa
        await _send_whatsapp(
            phone_wa,
            f"Reminder from *Cozeevo Co-living*\n\n"
            f"Please complete your registration:\n{onboard_link}\n\n"
            f"This link is valid for 48 hours."
        )
        return {"status": "sent", "token": token, "regenerated": is_expired or obs.status == "expired"}


@router.post("/admin/{token}/regen-pdf")
async def regen_pdf(token: str, request: Request):
    """Re-generate the agreement PDF for an approved session and optionally resend via WhatsApp."""
    _check_admin_pin(request)
    async with get_session() as session:
        obs = await session.scalar(select(OnboardingSession).where(OnboardingSession.token == token))
        if not obs:
            raise HTTPException(404, "Session not found")
        if obs.status != "approved":
            raise HTTPException(400, f"Session is not approved (status={obs.status})")

        td = json.loads(obs.tenant_data) if obs.tenant_data else {}
        if not td.get("name") or not td.get("phone"):
            raise HTTPException(400, "Tenant data incomplete — cannot generate PDF")

        room = await session.get(Room, obs.room_id) if obs.room_id else None
        building = ""
        if room and room.property_id:
            prop = await session.get(Property, room.property_id)
            building = prop.name if prop else ""
        rt = room.room_type if room else None
        sharing = rt.value if hasattr(rt, "value") else str(rt or "")

        from src.services.pdf_generator import generate_agreement_pdf
        receptionist_name = ""
        if obs.approved_by_phone:
            au = await session.scalar(
                select(AuthorizedUser).where(AuthorizedUser.phone == obs.approved_by_phone)
            )
            if au:
                receptionist_name = au.name
        pdf_path = await generate_agreement_pdf(obs, td, room, building, sharing, receptionist_name)
        obs.agreement_pdf_path = pdf_path
        await session.commit()

        # Copy to static so dashboard link works
        whatsapp_sent = False
        try:
            from pathlib import Path
            media_dir = Path(os.getenv("MEDIA_DIR", "media"))
            src_pdf = media_dir / pdf_path
            static_pdf_dir = Path("static/agreements") / Path(pdf_path).parent.name
            static_pdf_dir.mkdir(parents=True, exist_ok=True)
            static_pdf = static_pdf_dir / Path(pdf_path).name
            import shutil
            shutil.copy2(str(src_pdf), str(static_pdf))
        except Exception:
            pass

        # Optionally resend to tenant
        send = (request.query_params.get("send") or "").lower() in ("1", "true", "yes")
        if send and obs.tenant_phone:
            try:
                from src.whatsapp.webhook_handler import _send_whatsapp_document
                base_url = os.getenv("BASE_URL", "https://api.getkozzy.com")
                pdf_url = f"{base_url}/static/{pdf_path}"
                phone_wa = obs.tenant_phone.strip()
                if not phone_wa.startswith("91"):
                    phone_wa = "91" + phone_wa
                await _send_whatsapp_document(
                    phone_wa, pdf_url,
                    f"Cozeevo_Agreement_{td.get('name', 'tenant').replace(' ', '_')}.pdf",
                    caption="Your Cozeevo Co-living rental agreement (re-sent).",
                )
                whatsapp_sent = True
            except Exception:
                pass

        return {"status": "ok", "pdf_path": pdf_path, "whatsapp_sent": whatsapp_sent}


# ── Staff signature store / retrieve ─────────────────────────────────────────

@router.get("/staff-signature/{phone}")
async def get_staff_signature(phone: str, request: Request):
    """Return saved staff signature as base64 PNG, or 404 if not saved yet."""
    _check_admin_pin(request)
    import base64
    from src.services import storage as _storage
    try:
        data = await _storage.download(_storage.BUCKET_KYC, f"staff-signatures/{phone.strip()}.png")
        return {"data_url": f"data:image/png;base64,{base64.b64encode(data).decode()}"}
    except FileNotFoundError:
        raise HTTPException(404, "No saved signature for this phone")


@router.post("/staff-signature/{phone}")
async def save_staff_signature(phone: str, request: Request):
    """Save (or overwrite) a staff member's signature. Accepts base64 PNG data URL."""
    _check_admin_pin(request)
    body = await request.json()
    data_url = body.get("data_url", "")
    if not data_url or "base64," not in data_url:
        raise HTTPException(400, "data_url required (base64 PNG)")
    import base64
    from src.services import storage as _storage
    raw = base64.b64decode(data_url.split("base64,", 1)[1])
    await _storage.upload(_storage.BUCKET_KYC, f"staff-signatures/{phone.strip()}.png", raw, "image/png")
    return {"status": "saved", "phone": phone}


@router.get("/staff-sign", response_class=HTMLResponse)
async def staff_sign_page(request: Request, phone: str = ""):
    """One-time signature collection page for staff. Opens signature pad, saves on submit."""
    _check_admin_pin(request)
    phone_val = phone or ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Staff Signature — Cozeevo</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, sans-serif; background: #F9FAFB; display: flex; align-items: center;
            justify-content: center; min-height: 100vh; padding: 20px; }}
    .card {{ background: #fff; border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,.1);
              padding: 32px; max-width: 480px; width: 100%; }}
    h2 {{ color: #1A202C; font-size: 20px; margin-bottom: 6px; }}
    p {{ color: #718096; font-size: 13px; margin-bottom: 24px; }}
    label {{ font-size: 12px; font-weight: 700; color: #4A5568; text-transform: uppercase;
              letter-spacing: .4px; display: block; margin-bottom: 6px; }}
    input {{ width: 100%; padding: 10px 12px; border: 1px solid #CBD5E1; border-radius: 6px;
              font-size: 14px; margin-bottom: 18px; }}
    canvas {{ border: 2px dashed #CBD5E1; border-radius: 8px; display: block; width: 100%;
               height: 130px; touch-action: none; cursor: crosshair; background: #fff; }}
    .row {{ display: flex; justify-content: space-between; align-items: center; margin-top: 6px; margin-bottom: 20px; }}
    .row a {{ font-size: 12px; color: #EF1F9C; cursor: pointer; text-decoration: none; }}
    .row span {{ font-size: 12px; color: #718096; }}
    button {{ width: 100%; padding: 12px; background: #EF1F9C; color: #fff; border: none;
               border-radius: 8px; font-size: 15px; font-weight: 700; cursor: pointer; }}
    button:disabled {{ opacity: .5; cursor: not-allowed; }}
    #msg {{ margin-top: 16px; padding: 12px; border-radius: 6px; font-size: 13px; display: none; }}
    #msg.ok {{ background: #F0FFF4; color: #276749; border: 1px solid #9AE6B4; }}
    #msg.err {{ background: #FFF5F5; color: #C53030; border: 1px solid #FC8181; }}
  </style>
</head>
<body>
<div class="card">
  <h2>Staff Signature</h2>
  <p>Sign once — this will be auto-used for all future approvals from your phone number.</p>
  <label>Your Phone Number</label>
  <input id="phone" type="tel" maxlength="10" placeholder="10-digit phone" value="{phone_val}">
  <label>Draw Your Signature Below</label>
  <canvas id="sig-canvas" width="800" height="200"></canvas>
  <div class="row">
    <span>Use your finger or mouse</span>
    <a onclick="clearSig()">Clear</a>
  </div>
  <button id="saveBtn" onclick="save()">Save My Signature</button>
  <div id="msg"></div>
</div>
<script>
  const canvas = document.getElementById('sig-canvas');
  const ctx = canvas.getContext('2d');
  ctx.strokeStyle = '#00AEED'; ctx.lineWidth = 2.5; ctx.lineCap = 'round'; ctx.lineJoin = 'round';
  let drawing = false, lx = 0, ly = 0, drawn = false;
  function pos(e) {{
    const r = canvas.getBoundingClientRect();
    const scx = canvas.width / r.width, scy = canvas.height / r.height;
    if (e.touches) return {{ x: (e.touches[0].clientX - r.left)*scx, y: (e.touches[0].clientY - r.top)*scy }};
    return {{ x: (e.clientX - r.left)*scx, y: (e.clientY - r.top)*scy }};
  }}
  canvas.addEventListener('mousedown', e => {{ const p = pos(e); drawing=true; lx=p.x; ly=p.y; }});
  canvas.addEventListener('mousemove', e => {{
    if (!drawing) return;
    const p = pos(e);
    ctx.beginPath(); ctx.moveTo(lx,ly); ctx.lineTo(p.x,p.y); ctx.stroke();
    lx=p.x; ly=p.y; drawn=true;
  }});
  canvas.addEventListener('mouseup', () => drawing=false);
  canvas.addEventListener('mouseleave', () => drawing=false);
  canvas.addEventListener('touchstart', e => {{ e.preventDefault(); const p = pos(e); drawing=true; lx=p.x; ly=p.y; }}, {{passive:false}});
  canvas.addEventListener('touchmove', e => {{
    e.preventDefault(); if (!drawing) return;
    const p = pos(e);
    ctx.beginPath(); ctx.moveTo(lx,ly); ctx.lineTo(p.x,p.y); ctx.stroke();
    lx=p.x; ly=p.y; drawn=true;
  }}, {{passive:false}});
  canvas.addEventListener('touchend', () => drawing=false);

  function clearSig() {{ ctx.clearRect(0,0,canvas.width,canvas.height); drawn=false; }}

  async function save() {{
    const phone = document.getElementById('phone').value.trim();
    if (!phone || phone.length !== 10) {{ showMsg('Enter a valid 10-digit phone number.', false); return; }}
    if (!drawn) {{ showMsg('Please draw your signature first.', false); return; }}
    const dataUrl = canvas.toDataURL('image/png');
    const btn = document.getElementById('saveBtn');
    btn.disabled = true; btn.textContent = 'Saving...';
    try {{
      const r = await fetch('/api/onboarding/staff-signature/' + phone, {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json', 'X-Admin-Pin': '{ADMIN_PIN}' }},
        body: JSON.stringify({{ data_url: dataUrl }}),
      }});
      if (r.ok) {{
        showMsg('Signature saved! This will be used automatically on future approvals.', true);
      }} else {{
        showMsg('Save failed: ' + (await r.text()), false);
      }}
    }} catch(e) {{ showMsg('Network error: ' + e, false); }}
    btn.disabled = false; btn.textContent = 'Save My Signature';
  }}

  function showMsg(text, ok) {{
    const el = document.getElementById('msg');
    el.textContent = text; el.className = ok ? 'ok' : 'err'; el.style.display = 'block';
  }}
</script>
</body>
</html>"""


_AADHAAR_EXTRACT_PROMPT = """You are extracting identity details from an Indian Aadhaar card photo.
Return ONLY valid JSON with these fields. No markdown, no explanation.

{
  "aadhaar_number": "",
  "name": "",
  "dob": "",
  "gender": "",
  "address": ""
}

Rules:
- aadhaar_number: 12 digits, no spaces (e.g. "123456789012"). Look for the bold 12-digit number on the card.
- name: full name as printed on card
- dob: DD/MM/YYYY format
- gender: "male" or "female" (lowercase)
- address: full address as printed, single line, comma-separated
- If a field is unreadable or not visible, use ""
- For the back of the card: extract address. For the front: extract name, dob, gender, aadhaar_number.
- If both sides are in one image, extract all fields.
"""


@router.post("/{token}/extract-id")
async def extract_id_photo(token: str, request: Request):
    """Extract Aadhaar details from an uploaded ID photo using Claude Haiku vision."""
    async with get_session() as session:
        obs = await session.scalar(select(OnboardingSession).where(OnboardingSession.token == token))
    if not obs:
        raise HTTPException(404, "Session not found")

    body = await request.json()
    image_b64 = body.get("image_b64", "")
    mime_type = body.get("mime_type", "image/jpeg")

    if not image_b64:
        raise HTTPException(400, "image_b64 required")

    # Strip data URI prefix if present
    if "base64," in image_b64:
        image_b64 = image_b64.split("base64,", 1)[1]

    import base64
    try:
        image_bytes = base64.b64decode(image_b64)
    except Exception:
        raise HTTPException(400, "Invalid base64 image")

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key or api_key.startswith("sk-ant-your"):
        return {"error": "extraction_unavailable", "fields": {}}

    try:
        import anthropic
        media_type = mime_type if mime_type in ("image/jpeg", "image/png", "image/webp") else "image/jpeg"
        b64_str = base64.b64encode(image_bytes).decode()
        client = anthropic.AsyncAnthropic(api_key=api_key)
        msg = await client.messages.create(
            model=os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001"),
            max_tokens=512,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64_str}},
                    {"type": "text", "text": _AADHAAR_EXTRACT_PROMPT},
                ],
            }],
        )
        raw = msg.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        fields = json.loads(raw)
        return {"fields": fields}
    except Exception as e:
        import logging
        logging.getLogger(__name__).error("ID extract failed: %s", e)
        return {"error": str(e), "fields": {}}


# ── Get session data (tenant form) ───────────────────────────────────────────

@router.get("/{token}")
async def get_session_data(token: str, request: Request):
    _rate_check(f"token:{request.client.host}", 20, 60)  # 20/min per IP
    async with get_session() as session:
        obs = await session.scalar(select(OnboardingSession).where(OnboardingSession.token == token))
        if not obs:
            raise HTTPException(404, "Not found")  # generic error to prevent enumeration
        if obs.status == "expired" or (obs.expires_at and obs.expires_at < datetime.utcnow()):
            raise HTTPException(410, "This onboarding link has expired")
        if obs.status not in ("pending_tenant", "pending_review"):
            raise HTTPException(400, "This form is no longer available")

        room = await session.get(Room, obs.room_id) if obs.room_id else None
        building = ""
        if room and room.property_id:
            prop = await session.get(Property, room.property_id)
            building = prop.name if prop else ""
        rt = room.room_type if room else ""
        sharing = rt.value if hasattr(rt, 'value') else str(rt or "")

        return {
            "status": obs.status,
            "room": {"number": room.room_number if room else "", "building": building, "floor": str(room.floor or "") if room else "", "sharing": sharing},
            "agreed_rent": float(obs.agreed_rent or 0),
            "security_deposit": float(obs.security_deposit or 0),
            "maintenance_fee": float(obs.maintenance_fee or 0),
            "booking_amount": float(obs.booking_amount or 0),
            "advance_mode": obs.advance_mode or "",
            "stay_type": obs.stay_type or "",
            "checkin_date": obs.checkin_date.isoformat() if obs.checkin_date else "",
            "lock_in_months": obs.lock_in_months or 0,
            "special_terms": obs.special_terms or "",
            "future_rent": float(obs.future_rent) if obs.future_rent else None,
            "future_rent_after_months": obs.future_rent_after_months or None,
            "tenant_data": json.loads(obs.tenant_data) if obs.tenant_data else None,
            "signature_image": obs.signature_image or "",
            "rules": _substitute_house_rules(obs),
        }


def _substitute_house_rules(obs: OnboardingSession) -> list[str]:
    rent = f"Rs.{int(obs.agreed_rent or 0):,}"
    deposit = f"Rs.{int(obs.security_deposit or 0):,}"
    lock_in = str(obs.lock_in_months or 3)
    maintenance = f"Rs.{int(obs.maintenance_fee or 0):,}"
    tenant_data = json.loads(obs.tenant_data) if obs.tenant_data else {}
    food = (tenant_data.get("food_preference") if isinstance(tenant_data, dict) else None) or "Veg"
    return [rule.format(rent=rent, deposit=deposit, lock_in=lock_in, food=food, maintenance=maintenance) for rule in HOUSE_RULES]


# ── Tenant submits form ──────────────────────────────────────────────────────

@router.post("/{token}/submit")
async def tenant_submit(token: str, req: TenantSubmitRequest, request: Request):
    _rate_check(f"submit:{request.client.host}", 5, 60)  # 5/min per IP
    # File size check (base64 ~1.37x original). Signature is now a short
    # text token ("I_AGREE:<name>:<timestamp>") so it always passes.
    for field_name, data in [("selfie", req.selfie_photo), ("id_proof", req.id_photo), ("signature", req.signature_image)]:
        if data and len(data) > MAX_UPLOAD_SIZE:
            raise HTTPException(413, f"{field_name} file too large (max 4MB)")
    async with get_session() as session:
        obs = await session.scalar(select(OnboardingSession).where(OnboardingSession.token == token))
        if not obs:
            raise HTTPException(404, "Session not found")
        if obs.status != "pending_tenant":
            raise HTTPException(400, f"Cannot submit — status is {obs.status}")
        if obs.expires_at and obs.expires_at < datetime.utcnow():
            obs.status = "expired"
            raise HTTPException(410, "This onboarding link has expired")

        # Upload files to Supabase Storage
        import base64 as b64mod
        import logging as _logging
        from src.services import storage as _storage
        _log = _logging.getLogger(__name__)
        token_short = obs.token[:8]
        saved_files = {}

        for field_name, data_url in [("selfie", req.selfie_photo), ("id_proof", req.id_photo)]:
            if not data_url or "base64," not in data_url:
                continue
            try:
                header, b64_data = data_url.split("base64,", 1)
                if "pdf" in header:
                    ext, ct = ".pdf", "application/pdf"
                elif "png" in header:
                    ext, ct = ".png", "image/png"
                elif "webp" in header:
                    ext, ct = ".webp", "image/webp"
                else:
                    ext, ct = ".jpg", "image/jpeg"
                file_bytes = b64mod.b64decode(b64_data)
                path = f"onboarding/{token_short}/{field_name}{ext}"
                url = await _storage.upload(_storage.BUCKET_KYC, path, file_bytes, ct)
                saved_files[field_name] = url
            except Exception as _e:
                _log.warning("KYC upload %s failed: %s", field_name, _e)

        # Upload signature (base64 image) to Supabase
        if req.signature_image and "base64," in req.signature_image:
            try:
                _, sig_b64 = req.signature_image.split("base64,", 1)
                path = f"onboarding/{token_short}/signature.png"
                url = await _storage.upload(_storage.BUCKET_KYC, path, b64mod.b64decode(sig_b64), "image/png")
                saved_files["signature"] = url
            except Exception as _e:
                _log.warning("Signature upload failed: %s", _e)

        # Phone uniqueness checks — run BEFORE saving tenant_data
        import re as _re2
        _phone_raw = _re2.sub(r"\D", "", req.phone or "")
        _phone10 = _phone_raw[-10:] if len(_phone_raw) >= 10 else _phone_raw

        # Block if this phone already has an active/no_show tenancy
        from src.services.room_occupancy import get_active_tenancy_by_phone
        _existing = await get_active_tenancy_by_phone(session, _phone10)
        if _existing:
            _et, _etn, _er = _existing
            raise HTTPException(
                409,
                f"Phone {req.phone} is already registered to {_et.name} in Room {_er.room_number}. "
                "Each person must use their own phone number."
            )

        # Cancel any other pending sessions for this phone (avoid duplicate bookings)
        from sqlalchemy import text as _text
        await session.execute(
            _text(
                "UPDATE onboarding_sessions SET status='cancelled', cancellation_reason='superseded' "
                "WHERE tenant_phone=:phone AND status IN ('pending_tenant','pending_review') AND token != :token"
            ),
            {"phone": _phone10, "token": token},
        )

        # Store normalised phone on session so receptionist-side dedup sees it
        await session.execute(
            _text("UPDATE onboarding_sessions SET tenant_phone=:phone WHERE token=:token"),
            {"phone": _phone10, "token": token},
        )

        tenant_data = req.model_dump(exclude={"signature_image", "id_photo", "selfie_photo"})
        tenant_data["saved_files"] = saved_files  # paths for approve step
        obs.tenant_data = json.dumps(tenant_data)
        obs.signature_image = req.signature_image
        obs.status = "pending_review"
        obs.completed_at = datetime.utcnow()

        # Notify receptionist via WhatsApp
        if obs.created_by_phone:
            try:
                from src.whatsapp.webhook_handler import _send_whatsapp
                notify_phone = obs.created_by_phone.strip()
                if not notify_phone.startswith("91"):
                    notify_phone = "91" + notify_phone
                room = await session.get(Room, obs.room_id) if obs.room_id else None
                room_str = room.room_number if room else "—"
                await _send_whatsapp(
                    notify_phone,
                    f"*Onboarding form submitted*\n\n"
                    f"Tenant: *{req.name}*\n"
                    f"Phone: {req.phone}\n"
                    f"Room: {room_str}\n\n"
                    f"Please review and approve:\n"
                    f"{os.getenv('PWA_URL', 'https://app.getkozzy.com')}/onboarding/bookings"
                )
            except Exception:
                pass  # non-fatal

        return {"status": "pending_review", "message": "Submitted. Receptionist will review."}


# ── Approve session (admin) ──────────────────────────────────────────────────

class ApproveRequest(BaseModel):
    staff_signature: str = ""  # base64 PNG data URL
    approved_by_phone: str = ""  # phone of the staff member approving
    entry_source: str = "onboarding_form"  # "onboarding_form" | "physical_form"
    instant_checkin: bool = False  # True → force status=active even if checkin_date is future
    # Payments collected at check-in (recorded as Payment rows immediately)
    collected_rent: float = 0      # first-month rent received (usually pro-rata)
    collected_deposit: float = 0   # security deposit received
    collected_advance: float = 0   # any advance/token payment received
    collected_dues: float = 0      # additional amount collected against outstanding dues
    rent_mode: str = "cash"        # "cash" | "upi" per field
    deposit_mode: str = "cash"
    advance_mode: str = "cash"
    dues_mode: str = "cash"
    # legacy single-mode field — kept for backward compat; per-field modes take precedence
    checkin_payment_mode: str = "cash"
    # Optional receptionist overrides — any field name in this dict replaces
    # the tenant-submitted value. Editable from the admin review screen.
    # Supported keys (financial): agreed_rent, security_deposit, maintenance_fee,
    # booking_amount, checkin_date.
    # Supported keys (KYC): name, phone, gender, date_of_birth, email,
    # father_name, father_phone, emergency_contact_name,
    # emergency_contact_phone, emergency_contact_relationship,
    # permanent_address, occupation, educational_qualification,
    # food_preference, id_proof_type, id_proof_number.
    overrides: dict = {}


_KYC_FIELD_LABELS = {
    "name": "Name", "phone": "Phone", "gender": "Gender",
    "date_of_birth": "Date of Birth", "email": "Email",
    "father_name": "Father Name", "father_phone": "Father Phone",
    "emergency_contact_name": "Emergency Contact",
    "emergency_contact_phone": "Emergency Phone",
    "emergency_contact_relationship": "Emergency Relationship",
    "permanent_address": "Address", "occupation": "Occupation",
    "educational_qualification": "Education",
    "food_preference": "Food Preference",
    "id_proof_type": "ID Type", "id_proof_number": "ID Number",
}
_FINANCIAL_FIELD_LABELS = {
    "agreed_rent": "Monthly Rent", "security_deposit": "Deposit",
    "maintenance_fee": "Maintenance", "booking_amount": "Booking Advance",
    "checkin_date": "Check-in Date",
}


def _format_diff_value(field: str, value) -> str:
    """Pretty-print a value for the diff message (Rs. for money, dd-mmm for dates)."""
    if value is None or value == "":
        return "—"
    if field in ("agreed_rent", "security_deposit", "maintenance_fee", "booking_amount"):
        try:
            return f"Rs.{int(float(value)):,}"
        except (TypeError, ValueError):
            return str(value)
    if field == "checkin_date":
        try:
            return date.fromisoformat(str(value)).strftime("%d %b %Y")
        except (TypeError, ValueError):
            return str(value)
    return str(value)


@router.post("/{token}/approve")
async def approve_session(token: str, request: Request, req: ApproveRequest = None):
    _check_admin_pin(request)
    try:
        return await _approve_session_impl(token, req)
    except HTTPException:
        raise
    except Exception as e:
        import logging, traceback
        logging.getLogger(__name__).error(
            "Approve failed for token %s: %s\n%s", token[:8], e, traceback.format_exc()
        )
        # Surface a readable reason to the admin UI instead of a blank 500
        raise HTTPException(500, f"Approve failed: {type(e).__name__}: {e}")


async def _approve_session_impl(token: str, req: ApproveRequest | None):
    async with get_session() as session:
        obs = await session.scalar(select(OnboardingSession).where(OnboardingSession.token == token))
        if not obs:
            raise HTTPException(404, "Session not found")
        if obs.status != "pending_review":
            raise HTTPException(400, f"Cannot approve — status is {obs.status}")

        td = json.loads(obs.tenant_data) if obs.tenant_data else {}
        # Snapshot ORIGINAL submitted values before overrides — used for diff.
        # KYC came from the tenant's form fill; financial came from the
        # receptionist's session-create call.
        original_kyc = {k: td.get(k, "") for k in _KYC_FIELD_LABELS.keys()}
        original_financial = {
            "agreed_rent": float(obs.agreed_rent or 0),
            "security_deposit": float(obs.security_deposit or 0),
            "maintenance_fee": float(obs.maintenance_fee or 0),
            "booking_amount": float(obs.booking_amount or 0),
            "checkin_date": obs.checkin_date.isoformat() if obs.checkin_date else "",
        }

        # Apply receptionist overrides
        overrides = (req.overrides if req and req.overrides else {}) or {}
        # Financial overrides go onto obs (used by tenancy creation below)
        if "agreed_rent" in overrides:
            obs.agreed_rent = Decimal(str(overrides["agreed_rent"]))
        if "security_deposit" in overrides:
            obs.security_deposit = Decimal(str(overrides["security_deposit"]))
        if "maintenance_fee" in overrides:
            obs.maintenance_fee = Decimal(str(overrides["maintenance_fee"]))
        if "booking_amount" in overrides:
            obs.booking_amount = Decimal(str(overrides["booking_amount"]))
        if "checkin_date" in overrides:
            try:
                obs.checkin_date = date.fromisoformat(overrides["checkin_date"])
            except ValueError:
                pass
        # KYC overrides patch td so the tenant/tenancy creation downstream
        # uses the corrected values.
        for k in _KYC_FIELD_LABELS.keys():
            if k in overrides:
                td[k] = overrides[k]
        if not td.get("name") or not td.get("phone"):
            raise HTTPException(400, "Tenant data incomplete")

        # Blacklist check (name + phone from KYC — catches name-only entries)
        from src.services.blacklist import check_blacklisted as _check_bl
        _bl = await _check_bl(session, name=td.get("name"), phone=td.get("phone"))
        if _bl:
            raise HTTPException(
                403,
                f"This person is on the Cozeevo blacklist: {_bl['reason']}. "
                "Contact Kiran if this is a mistake."
            )

        # If room was not assigned at creation time (future booking), allow override now
        room = None
        if obs.room_id:
            room = await session.get(Room, obs.room_id)

        # Check if receptionist is assigning room at approval time via override
        if "room_id" in overrides or "room_number" in overrides:
            room_identifier = overrides.get("room_number") or overrides.get("room_id")
            if room_identifier:
                # Try to look up by room_number if it's a string
                if isinstance(room_identifier, str):
                    room = await session.scalar(select(Room).where(Room.room_number.ilike(room_identifier)))
                else:
                    room = await session.get(Room, room_identifier)
                if room:
                    obs.room_id = room.id

        # Room can be unassigned for future bookings (assigned later via ASSIGN_ROOM)
        building = ""
        if room and room.property_id:
            prop = await session.get(Property, room.property_id)
            building = prop.name if prop else ""

        from src.services.room_occupancy import canonical_phone as _canon
        phone = _canon(td["phone"])

        # Create or find tenant (normalized lookup so +91/91/bare all match)
        from src.services.room_occupancy import _normalize_phone as _np2
        from sqlalchemy import func as _func2
        _norm10 = _np2(phone)
        tenant = await session.scalar(
            select(Tenant).where(
                _func2.right(_func2.regexp_replace(Tenant.phone, r"[^0-9]", "", "g"), 10) == _norm10
            )
        )
        if not tenant:
            tenant = Tenant(
                name=td["name"], phone=phone, gender=td.get("gender"),
                food_preference=td.get("food_preference"), email=td.get("email"),
                father_name=td.get("father_name"), father_phone=td.get("father_phone"),
                emergency_contact_name=td.get("emergency_contact_name"),
                emergency_contact_phone=td.get("emergency_contact_phone"),
                emergency_contact_relationship=td.get("emergency_contact_relationship"),
                permanent_address=td.get("permanent_address"), occupation=td.get("occupation"),
                educational_qualification=td.get("educational_qualification"),
                office_address=td.get("office_address"), office_phone=td.get("office_phone"),
                id_proof_type=td.get("id_proof_type"), id_proof_number=td.get("id_proof_number"),
            )
            dob_str = td.get("date_of_birth", "")
            if dob_str:
                for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
                    try:
                        tenant.date_of_birth = datetime.strptime(dob_str, fmt).date()
                        break
                    except ValueError:
                        continue
            session.add(tenant)
            await session.flush()

        rt = room.room_type if room else None
        sharing = rt.value if hasattr(rt, 'value') else str(rt or "")
        checkin = obs.checkin_date or date.today()
        is_daily = obs.stay_type == "daily"

        # Phone dedup guard — block if this phone already has an active tenancy
        from src.services.room_occupancy import check_room_bookable, get_active_tenancy_by_phone
        existing_active = await get_active_tenancy_by_phone(session, phone)
        if existing_active:
            _et, _etn, _er = existing_active
            if _etn.id != (obs.tenancy_id or -1):  # don't block re-approvals of same session
                raise HTTPException(
                    409,
                    f"Phone {phone} already has an active tenancy for "
                    f"{_et.name} in Room {_er.room_number}. "
                    "Cannot create duplicate. Checkout their current room first."
                )

        # Double-booking guard — only if room is assigned
        if room:
            _guard_checkout = None
            if is_daily:
                _guard_checkout = obs.checkout_date or (checkin + timedelta(days=obs.num_days or 1))
            _, _guard_err = await check_room_bookable(
                session, room.room_number, checkin, _guard_checkout,
                property_id=room.property_id,
            )
            if _guard_err:
                raise HTTPException(409, _guard_err)

        import asyncio as _aio
        import logging as _log
        _logger = _log.getLogger(__name__)
        gsheets_note = ""
        phone_sheet = f"+91{phone}" if len(phone) == 10 else phone
        # Set in monthly branch; stays None for daily stays (no tenancy row)
        tenancy = None
        # effective_sharing is only assigned in the monthly branch but is read
        # later by the diff/WhatsApp block unconditionally — init here so
        # day-stay approvals don't crash with UnboundLocalError.
        effective_sharing = None

        if is_daily:
            # ── Daily stay path — writes Tenancy(stay_type=daily) ──────────
            checkout = obs.checkout_date or (checkin + timedelta(days=obs.num_days or 1))
            num_days = obs.num_days or max(1, (checkout - checkin).days)
            total_paid = float(obs.agreed_rent or 0)  # agreed_rent stores total paid for daily

            tenancy = Tenancy(
                tenant_id=tenant.id,
                room_id=room.id if room else None,
                stay_type=StayType.daily,
                status=TenancyStatus.active,
                checkin_date=checkin,
                checkout_date=checkout,
                expected_checkout=checkout,
                agreed_rent=obs.daily_rate or 0,        # per-day rate
                booking_amount=obs.booking_amount or 0,
                maintenance_fee=obs.maintenance_fee or 0,
                notes=obs.special_terms or "",
                entered_by="onboarding_form",
            )
            session.add(tenancy)
            await session.flush()

            if total_paid > 0:
                session.add(Payment(
                    tenancy_id=tenancy.id,
                    amount=obs.agreed_rent,
                    payment_date=checkin,
                    payment_mode=PaymentMode.upi if obs.advance_mode == "upi" else PaymentMode.cash,
                    for_type=PaymentFor.rent,
                    notes="day-stay onboarding payment",
                ))

            obs.status = "approved"
            obs.approved_at = datetime.utcnow()
            obs.approved_by_phone = (req.approved_by_phone or "").strip() if req else ""
            obs.tenant_id = tenant.id
            obs.tenancy_id = tenancy.id

            # GSheets DAY WISE tab (retry 3x)
            for attempt in range(3):
                try:
                    from src.integrations.gsheets import add_daywise_stay as gsheets_dw
                    gs_r = await gsheets_dw(
                        room_number=room.room_number if room else "TBD",
                        tenant_name=td["name"],
                        phone=phone_sheet,
                        building=building,
                        sharing=sharing,
                        daily_rate=float(obs.daily_rate or 0),
                        num_days=num_days,
                        booking_amount=float(obs.booking_amount or 0),
                        total_paid=total_paid,
                        maintenance=float(obs.maintenance_fee or 0),
                        checkin=checkin.strftime("%d/%m/%Y"),
                        checkout=checkout.strftime("%d/%m/%Y"),
                        status="ACTIVE",
                        notes=obs.special_terms or "",
                        entered_by="onboarding_form",
                    )
                    if gs_r.get("success"):
                        gsheets_note = " | DAY WISE Sheet updated"
                        break
                except Exception as e:
                    _logger.warning("GSheets DAY WISE attempt %d error: %s", attempt + 1, e)
                if attempt < 2:
                    await _aio.sleep(2 * (attempt + 1))

            # GSheets TENANTS master tab (day-wise guests still appear in master)
            try:
                from src.integrations.gsheets import add_tenant as gsheets_add_tenant
                await gsheets_add_tenant(
                    room_number=room.room_number if room else "TBD",
                    name=td["name"],
                    phone=phone_sheet,
                    gender=td.get("gender", ""),
                    building=building,
                    floor=td.get("floor", ""),
                    sharing=sharing,
                    checkin=checkin.strftime("%d/%m/%Y"),
                    agreed_rent=float(obs.daily_rate or 0),
                    deposit=0.0,
                    booking=float(obs.booking_amount or 0),
                    maintenance=float(obs.maintenance_fee or 0),
                    notes=obs.special_terms or "",
                    dob=td.get("dob", ""),
                    father_name=td.get("father_name", ""),
                    father_phone=td.get("father_phone", ""),
                    address=td.get("address", ""),
                    emergency_contact=td.get("emergency_contact", ""),
                    emergency_contact_phone=td.get("emergency_contact_phone", ""),
                    emergency_relationship=td.get("emergency_relationship", ""),
                    email=td.get("email", ""),
                    occupation=td.get("occupation", ""),
                    education=td.get("education", ""),
                    office_address=td.get("office_address", ""),
                    office_phone=td.get("office_phone", ""),
                    id_type=td.get("id_type", ""),
                    id_number=td.get("id_number", ""),
                    food_pref=td.get("food_pref", ""),
                    entered_by="onboarding_form",
                    tenants_only=True,
                )
            except Exception as e:
                _logger.warning("GSheets TENANTS tab update failed for day-wise %s: %s", td["name"], e)

        else:
            # ── Monthly stay path ──────────────────────────────────────────
            # Resolve tenancy.sharing_type in this priority:
            #   1. receptionist override from review form (overrides["sharing_type"])
            #   2. receptionist pick at CREATE time (obs.sharing_type)
            #   3. room.room_type (master data default — never mutated)
            # This lets us book a "premium" tenancy in a "double" master room
            # (one tenant paying for both beds) without changing master data.
            from src.database.models import SharingType
            effective_sharing = (
                overrides.get("sharing_type")
                or (obs.sharing_type or "")
                or sharing
                or ""
            ).strip().lower()
            sharing_default = None
            if effective_sharing in ("single", "double", "triple", "premium"):
                try:
                    sharing_default = SharingType(effective_sharing)
                except ValueError:
                    sharing_default = None
            tenancy = Tenancy(
                tenant_id=tenant.id, room_id=room.id if room else None, checkin_date=checkin,
                agreed_rent=obs.agreed_rent or 0, security_deposit=obs.security_deposit or 0,
                booking_amount=obs.booking_amount or 0, maintenance_fee=obs.maintenance_fee or 0,
                lock_in_months=obs.lock_in_months or 0,
                sharing_type=sharing_default,
                entered_by=(req.entry_source or "onboarding_form") if req else "onboarding_form",
                status=TenancyStatus.active if (req and req.instant_checkin) or checkin <= date.today() else TenancyStatus.no_show,
            )
            session.add(tenancy)
            await session.flush()

            # RentSchedule — first-month rent prorated by default on check-in
            # date (canonical helper handles the rule).
            from src.services.rent_schedule import first_month_rent_due
            period = checkin.replace(day=1)
            current_month = date.today().replace(day=1)
            while period <= current_month:
                session.add(RentSchedule(
                    tenancy_id=tenancy.id, period_month=period,
                    rent_due=first_month_rent_due(tenancy, period),
                    maintenance_due=0,
                    status=RentStatus.pending, due_date=period,
                ))
                if period.month == 12:
                    period = date(period.year + 1, 1, 1)
                else:
                    period = date(period.year, period.month + 1, 1)

            # Advance payment (from onboarding session)
            if obs.booking_amount and obs.booking_amount > 0:
                adv_mode = PaymentMode.upi if obs.advance_mode == "upi" else PaymentMode.cash
                session.add(Payment(
                    tenancy_id=tenancy.id, amount=obs.booking_amount,
                    payment_date=checkin, payment_mode=adv_mode,
                    for_type=PaymentFor.booking, period_month=checkin.replace(day=1),
                    notes=f"Booking advance ({obs.advance_mode})",
                ))

            # Payments collected at check-in (entered by receptionist on the bookings screen)
            def _ci_mode(field_mode: str) -> PaymentMode:
                return PaymentMode.upi if field_mode == "upi" else PaymentMode.cash

            if req and req.collected_rent > 0:
                session.add(Payment(
                    tenancy_id=tenancy.id, amount=req.collected_rent,
                    payment_date=checkin, payment_mode=_ci_mode(req.rent_mode),
                    for_type=PaymentFor.rent, period_month=checkin.replace(day=1),
                    notes=f"Collected at check-in ({req.rent_mode})",
                ))
            if req and req.collected_deposit > 0:
                session.add(Payment(
                    tenancy_id=tenancy.id, amount=req.collected_deposit,
                    payment_date=checkin, payment_mode=_ci_mode(req.deposit_mode),
                    for_type=PaymentFor.deposit,
                    notes=f"Security deposit collected at check-in ({req.deposit_mode})",
                ))
            if req and req.collected_advance > 0:
                session.add(Payment(
                    tenancy_id=tenancy.id, amount=req.collected_advance,
                    payment_date=checkin, payment_mode=_ci_mode(req.advance_mode),
                    for_type=PaymentFor.booking, period_month=checkin.replace(day=1),
                    notes=f"Advance collected at check-in ({req.advance_mode})",
                ))
            if req and req.collected_dues > 0:
                session.add(Payment(
                    tenancy_id=tenancy.id, amount=req.collected_dues,
                    payment_date=checkin, payment_mode=_ci_mode(req.dues_mode),
                    for_type=PaymentFor.rent, period_month=checkin.replace(day=1),
                    notes=f"Dues collected at check-in ({req.dues_mode})",
                ))

            obs.status = "approved"
            obs.approved_at = datetime.utcnow()
            obs.approved_by_phone = (req.approved_by_phone or "").strip() if req else ""
            obs.tenant_id = tenant.id
            obs.tenancy_id = tenancy.id

            # Pre-schedule rent increase: insert rent_revision so monthly rollover
            # applies new rate automatically on effective_date.
            # Formula: effective_date = 1st of (checkin_month + N)
            # current month counts as month 1, so N=2 on April → June 1.
            if obs.future_rent and obs.future_rent_after_months:
                N = obs.future_rent_after_months
                eff_month_idx = checkin.month - 1 + N   # 0-based from Jan
                eff_year  = checkin.year + eff_month_idx // 12
                eff_month = eff_month_idx % 12 + 1
                session.add(RentRevision(
                    tenancy_id=tenancy.id,
                    old_rent=obs.agreed_rent,
                    new_rent=obs.future_rent,
                    effective_date=date(eff_year, eff_month, 1),
                    changed_by=(req.approved_by_phone or "onboarding") if req else "onboarding",
                    reason="planned_rent_increase",
                    org_id=1,
                ))

            # GSheets TENANTS + monthly tab (retry 3x)
            gsheet_kwargs = dict(
                room_number=room.room_number if room else "TBD", name=td["name"], phone=phone_sheet,
                gender=td.get("gender", ""), building=building,
                floor=str(room.floor or "") if room else "", sharing=effective_sharing or sharing,
                checkin=checkin.strftime("%d/%m/%Y"),
                agreed_rent=float(obs.agreed_rent or 0), deposit=float(obs.security_deposit or 0),
                booking=float(obs.booking_amount or 0), maintenance=float(obs.maintenance_fee or 0),
                notes=obs.special_terms or "",
                dob=td.get("date_of_birth", ""), father_name=td.get("father_name", ""),
                father_phone=td.get("father_phone", ""), address=td.get("permanent_address", ""),
                emergency_contact=td.get("emergency_contact_name", ""),
                emergency_contact_phone=td.get("emergency_contact_phone", ""),
                emergency_relationship=td.get("emergency_contact_relationship", ""),
                email=td.get("email", ""), occupation=td.get("occupation", ""),
                education=td.get("educational_qualification", ""),
                office_address=td.get("office_address", ""), office_phone=td.get("office_phone", ""),
                id_type=td.get("id_proof_type", ""), id_number=td.get("id_proof_number", ""),
                food_pref=td.get("food_preference", ""),
                entered_by=(req.entry_source or "onboarding_form") if req else "onboarding_form",
                advance_amount=float(obs.booking_amount or 0), advance_mode=obs.advance_mode or "",
            )
            for attempt in range(3):
                try:
                    from src.integrations.gsheets import add_tenant as gsheets_add
                    gs_r = await gsheets_add(**gsheet_kwargs)
                    if gs_r.get("success"):
                        gsheets_note = " | Sheet updated"
                        break
                    else:
                        _logger.warning("GSheets attempt %d failed: %s", attempt + 1, gs_r.get("error"))
                except Exception as e:
                    _logger.warning("GSheets attempt %d error: %s", attempt + 1, e)
                if attempt < 2:
                    await _aio.sleep(2 * (attempt + 1))
            if not gsheets_note:
                _logger.error("GSheets FAILED after 3 attempts for token %s", obs.token[:8])

        # Save staff signature to Supabase Storage
        if req and req.staff_signature and "base64," in req.staff_signature:
            try:
                import base64 as b64mod
                from src.services import storage as _storage
                _, sig_b64 = req.staff_signature.split("base64,", 1)
                path = f"onboarding/{obs.token[:8]}/staff_signature.png"
                await _storage.upload(_storage.BUCKET_KYC, path, b64mod.b64decode(sig_b64), "image/png")
            except Exception:
                pass

        # PDF generation
        try:
            from src.services.pdf_generator import generate_agreement_pdf
            receptionist_name = ""
            if obs.approved_by_phone:
                au = await session.scalar(
                    select(AuthorizedUser).where(AuthorizedUser.phone == obs.approved_by_phone)
                )
                if au:
                    receptionist_name = au.name
            pdf_path = await generate_agreement_pdf(
                obs, td, room, building, sharing, receptionist_name,
            )
            obs.agreement_pdf_path = pdf_path
        except Exception as e:
            import logging
            logging.getLogger(__name__).error("PDF generation failed: %s", e)

        # Save documents (selfie, ID proof, signature, agreement PDF) linked to tenant
        from src.database.models import Document, DocumentType
        saved_files = td.get("saved_files", {})
        doc_map = {
            "selfie": DocumentType.photo,
            "id_proof": DocumentType.id_proof,
            "signature": DocumentType.photo,
        }
        _tenancy_id_for_docs = tenancy.id if tenancy is not None else None
        for file_key, doc_type in doc_map.items():
            file_path = saved_files.get(file_key)
            if file_path:
                session.add(Document(
                    doc_type=doc_type,
                    file_path=file_path,
                    original_name=f"{file_key}_{td.get('name', 'tenant')}",
                    mime_type="image/png" if file_key == "signature" else "image/jpeg",
                    tenant_id=tenant.id,
                    tenancy_id=_tenancy_id_for_docs,
                ))
        # Agreement PDF as document
        if obs.agreement_pdf_path:
            session.add(Document(
                doc_type=DocumentType.agreement,
                file_path=obs.agreement_pdf_path,
                original_name=f"agreement_{td.get('name', 'tenant')}",
                mime_type="application/pdf",
                tenant_id=tenant.id,
                tenancy_id=_tenancy_id_for_docs,
            ))

        # Send booking confirmation to tenant via WhatsApp.
        # Uses an approved Meta template first (works even when the
        # tenant has never messaged us — needed for first-time check-ins),
        # then sends the signed PDF as a document.
        whatsapp_note = ""
        if obs.agreement_pdf_path and obs.tenant_phone:
            try:
                from src.whatsapp.webhook_handler import (
                    _send_whatsapp_document, _send_whatsapp, _send_whatsapp_template,
                )
                # agreement_pdf_path is now a full Supabase Storage URL
                pdf_url = obs.agreement_pdf_path

                phone_wa = obs.tenant_phone.strip()
                if not phone_wa.startswith("91"):
                    phone_wa = "91" + phone_wa

                tenant_name = td.get('name', '')
                checkin_str = checkin.strftime('%d %b %Y')

                # 1. Booking confirmation TEMPLATE (works for first-time contact)
                # Template name: cozeevo_booking_confirmation (5 vars)
                # Body params: {{1}}=name {{2}}=room {{3}}=checkin date
                #              {{4}}=rent amount {{5}}=deposit amount
                rent_str = f"Rs.{int(obs.agreed_rent or 0):,}"
                deposit_str = f"Rs.{int(obs.security_deposit or 0):,}"
                room_for_msg = room.room_number if room else "TBD"
                tpl_sent = await _send_whatsapp_template(
                    phone_wa,
                    "cozeevo_booking_confirmation",
                    [tenant_name, room_for_msg, checkin_str, rent_str, deposit_str],
                )
                # Fallback: if template not approved yet, send free text
                # (works only if tenant messaged us in the last 24h).
                if tpl_sent is False or tpl_sent is None:
                    _rent_increase_note = ""
                    if obs.future_rent and obs.future_rent_after_months:
                        _MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
                        _N = obs.future_rent_after_months
                        _eff = _MONTHS[(checkin.month - 1 + _N) % 12]
                        _rent_increase_note = f"\nNote: Rent increases to Rs.{int(obs.future_rent):,}/month from {_eff}."
                    await _send_whatsapp(
                        phone_wa,
                        f"Welcome to Cozeevo, {tenant_name}!\n\n"
                        f"Your booking is confirmed.\n"
                        f"Room: {room_for_msg}\n"
                        f"Check-in: {checkin_str}\n"
                        f"Monthly rent: {rent_str}{_rent_increase_note}\n"
                        f"Deposit: {deposit_str}\n\n"
                        f"If any amount shown differs from what was agreed in the form, please contact the receptionist or call 8548884455.",
                        intent="BOOKING_CONFIRMATION",
                    )

                # 2. Diff message — only if receptionist modified any
                # tenant-submitted value during review. Free text (24-hr
                # window already opened by template above).
                final_kyc = {k: td.get(k, "") for k in _KYC_FIELD_LABELS.keys()}
                final_financial = {
                    "agreed_rent": float(obs.agreed_rent or 0),
                    "security_deposit": float(obs.security_deposit or 0),
                    "maintenance_fee": float(obs.maintenance_fee or 0),
                    "booking_amount": float(obs.booking_amount or 0),
                    "checkin_date": obs.checkin_date.isoformat() if obs.checkin_date else "",
                }
                diff_lines = []
                for k, label in _FINANCIAL_FIELD_LABELS.items():
                    if str(original_financial.get(k, "")) != str(final_financial.get(k, "")):
                        diff_lines.append(
                            f"• {label}: {_format_diff_value(k, original_financial.get(k))}"
                            f" → {_format_diff_value(k, final_financial.get(k))}"
                        )
                # Sharing-type diff — room master type (original) vs the
                # receptionist's effective pick for this tenancy.
                master_sharing = (sharing or "").lower()
                if effective_sharing and effective_sharing != master_sharing:
                    diff_lines.append(
                        f"• Sharing Type: {master_sharing or '—'}"
                        f" → {effective_sharing}"
                    )
                for k, label in _KYC_FIELD_LABELS.items():
                    if str(original_kyc.get(k, "") or "") != str(final_kyc.get(k, "") or ""):
                        diff_lines.append(
                            f"• {label}: {_format_diff_value(k, original_kyc.get(k))}"
                            f" → {_format_diff_value(k, final_kyc.get(k))}"
                        )
                if diff_lines:
                    diff_msg = (
                        f"Hi {tenant_name}, the receptionist updated some details after "
                        f"reviewing your form:\n\n" + "\n".join(diff_lines) +
                        f"\n\nIf anything looks wrong, please call 8548884455."
                    )
                    await _send_whatsapp(phone_wa, diff_msg, intent="BOOKING_DIFF")
                    # Audit log — one entry per changed field
                    from src.database.models import AuditLog as _AL
                    for k in _FINANCIAL_FIELD_LABELS.keys():
                        if str(original_financial.get(k, "")) != str(final_financial.get(k, "")):
                            session.add(_AL(
                                changed_by="receptionist", entity_type="tenancy",
                                entity_id=tenancy.id if (tenancy is not None and not is_daily) else 0,
                                entity_name=tenant_name, field=k,
                                old_value=str(original_financial.get(k, "")),
                                new_value=str(final_financial.get(k, "")),
                                room_number=room.room_number if room else "TBD", source="onboarding_review",
                                note="receptionist override at approve",
                            ))
                    # Sharing-type override — tenancy-level only, never room.
                    if effective_sharing and effective_sharing != master_sharing:
                        session.add(_AL(
                            changed_by="receptionist", entity_type="tenancy",
                            entity_id=tenancy.id if (tenancy is not None and not is_daily) else 0,
                            entity_name=tenant_name, field="sharing_type",
                            old_value=master_sharing, new_value=effective_sharing,
                            room_number=room.room_number, source="onboarding_review",
                            note="receptionist override at approve (master data unchanged)",
                        ))
                    for k in _KYC_FIELD_LABELS.keys():
                        if str(original_kyc.get(k, "") or "") != str(final_kyc.get(k, "") or ""):
                            session.add(_AL(
                                changed_by="receptionist", entity_type="tenant",
                                entity_id=tenant.id, entity_name=tenant_name, field=k,
                                old_value=str(original_kyc.get(k, "") or ""),
                                new_value=str(final_kyc.get(k, "") or ""),
                                room_number=room.room_number if room else "TBD", source="onboarding_review",
                                note="receptionist override at approve",
                            ))

                # 3. Signed agreement PDF
                await _send_whatsapp_document(
                    phone_wa, pdf_url,
                    f"Cozeevo_Agreement_{tenant_name.replace(' ', '_')}.pdf",
                    "Your signed rental agreement"
                )
                whatsapp_note = " | Booking confirmation + PDF sent"
            except Exception as e:
                import logging
                logging.getLogger(__name__).error("WhatsApp PDF delivery failed: %s", e)
                whatsapp_note = f" | WhatsApp send FAILED: {e}"

        # Trigger full sheet sync in background so the monthly tab summary
        # rows (Active/Beds/Collection/Status) reflect the new tenant
        # without waiting for the 3am nightly cron. Per-row write done
        # earlier via add_tenant; this updates the aggregate counts.
        try:
            import asyncio as _aio
            import subprocess as _sp
            today = date.today()

            def _run_sync():
                try:
                    _sp.run(
                        ["venv/bin/python", "scripts/sync_sheet_from_db.py",
                         "--month", str(today.month), "--year", str(today.year), "--write"],
                        capture_output=True, text=True, timeout=300, cwd="/opt/pg-accountant",
                    )
                except Exception as _e:
                    import logging as _l
                    _l.getLogger(__name__).warning("Post-onboarding sheet sync failed: %s", _e)

            _aio.get_event_loop().run_in_executor(None, _run_sync)
        except Exception as _e:
            import logging as _l
            _l.getLogger(__name__).warning("Could not schedule post-onboarding sync: %s", _e)

        # Fallback: tenancy_id may not be set in the daily-stay branch
        _tenancy_id = getattr(obs, "tenancy_id", None) or (tenancy.id if (tenancy is not None and not is_daily) else None)

        return {
            "status": "approved", "tenant_id": tenant.id, "tenancy_id": _tenancy_id,
            "message": f"Tenant {td['name']} created{gsheets_note}{whatsapp_note} | Sheet summary refresh queued",
        }


# ── Session creation form (redirects to PWA) ────────────────────────────────
@router.get('/admin/onboarding')
async def redirect_to_pwa_bookings():
    """Redirects legacy admin onboarding page to PWA bookings page."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url='https://app.getkozzy.com/onboarding/bookings', status_code=302)
