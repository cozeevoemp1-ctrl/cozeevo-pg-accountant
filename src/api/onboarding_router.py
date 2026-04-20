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
    OnboardingSession, Room, Property, Tenant, Tenancy, TenancyStatus,
    RentSchedule, RentStatus, Payment, PaymentMode, PaymentFor,
)

router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])

# ── Security: Rate limiting + Admin auth ────────────────────────────────────

ADMIN_PIN = os.getenv("ONBOARDING_ADMIN_PIN", "cozeevo2026")
# Per-file cap: 4MB base64 ≈ 3MB raw. Covers a clear ID photo + selfie.
# Aggregate across 3 fields (selfie + id_proof + signature-token) stays
# well under the 10MB nginx cap set in /etc/nginx/sites-available/pg-accountant.
MAX_UPLOAD_SIZE = 4 * 1024 * 1024

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
    room_number: str
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
    """Look up room info for the create form."""
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
        return {"room_number": room.room_number, "building": building, "floor": str(room.floor or ""), "sharing": sharing}


@router.post("/create")
async def create_session(req: CreateSessionRequest, request: Request):
    _check_admin_pin(request)
    _rate_check(f"create:{request.client.host}", 10, 60)  # 10/min
    if req.booking_amount > 0 and not req.advance_mode:
        raise HTTPException(400, "Payment method (cash/upi) required when booking amount > 0")

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

        room = await session.scalar(select(Room).where(Room.room_number.ilike(req.room_number)))
        if not room:
            raise HTTPException(404, f"Room {req.room_number} not found")

        building = ""
        if room.property_id:
            prop = await session.get(Property, room.property_id)
            building = prop.name if prop else ""

        token = str(uuid.uuid4())
        obs = OnboardingSession(
            token=token,
            status="pending_tenant",
            created_by_phone=req.created_by_phone,
            tenant_phone=req.tenant_phone,
            room_id=room.id,
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
            expires_at=datetime.utcnow() + timedelta(hours=2),
        )
        session.add(obs)
        await session.flush()

        rt = room.room_type
        sharing = req.sharing_type if req.sharing_type else (rt.value if hasattr(rt, 'value') else str(rt or ""))

        # Calculate dues
        # Deposit already includes maintenance — don't double count
        total_due = float(req.agreed_rent + req.security_deposit - req.booking_amount)
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

                # Try template first (works without 24hr window)
                try:
                    await _send_whatsapp_template(
                        phone_wa, "cozeevo_checkin_form",
                        [room.room_number, rent_str, onboard_link]
                    )
                    whatsapp_sent = True
                except Exception:
                    # Fallback to regular message (needs 24hr window)
                    summary_lines = [f"Hello! Welcome to *Cozeevo Co-living*\n"]
                    summary_lines.append(f"Room *{room.room_number}* ({building}) — {sharing}")
                    summary_lines.append(f"Rent: {rent_str}/month")
                    summary_lines.append(f"\nPlease complete your registration:\n{onboard_link}")
                    summary_lines.append(f"\nThis link is valid for 2 hours.")
                    await _send_whatsapp(phone_wa, "\n".join(summary_lines))
                    whatsapp_sent = True
            except Exception as e:
                import logging
                logging.getLogger(__name__).error("WhatsApp onboarding link send failed: %s", e)

        return {
            "token": token,
            "link": f"/onboard/{token}",
            "full_link": onboard_link,
            "session_id": obs.id,
            "whatsapp_sent": whatsapp_sent,
            "dues_due": dues_due,
            "room": {"number": room.room_number, "building": building, "floor": str(room.floor or ""), "sharing": sharing},
        }


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
    """List all sessions with optional filters."""
    _check_admin_pin(request)
    async with get_session() as session:
        q = select(OnboardingSession).order_by(OnboardingSession.created_at.desc())
        if status:
            q = q.where(OnboardingSession.status == status)
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
            items.append({
                "token": obs.token,
                "status": obs.status,
                "room": room.room_number if room else "",
                "tenant_phone": obs.tenant_phone,
                "tenant_name": td.get("name", ""),
                "checkin_date": obs.checkin_date.isoformat() if obs.checkin_date else "",
                "created_at": obs.created_at.isoformat() if obs.created_at else "",
                "approved_at": obs.approved_at.isoformat() if obs.approved_at else "",
                "agreed_rent": float(obs.agreed_rent or 0),
            })
        return {"sessions": items}


@router.get("/admin/pending")
async def list_pending(request: Request):
    _check_admin_pin(request)
    async with get_session() as session:
        result = await session.execute(
            select(OnboardingSession).where(
                OnboardingSession.status.in_(["pending_tenant", "pending_review"])
            ).order_by(OnboardingSession.created_at.desc())
        )
        sessions = result.scalars().all()
        items = []
        for obs in sessions:
            room = await session.get(Room, obs.room_id) if obs.room_id else None
            items.append({
                "token": obs.token,
                "status": obs.status,
                "room": room.room_number if room else "",
                "tenant_phone": obs.tenant_phone,
                "checkin_date": obs.checkin_date.isoformat() if obs.checkin_date else "",
                "created_at": obs.created_at.isoformat() if obs.created_at else "",
                "tenant_name": json.loads(obs.tenant_data).get("name", "") if obs.tenant_data else "",
            })
        return {"sessions": items}


# ── Cancel session (admin) ─────────────────────────────────────────────────────

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
        if obs.status not in ("pending_tenant", "pending_review"):
            raise HTTPException(400, f"Cannot resend — status is {obs.status}")

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
            f"This link is valid for 2 hours."
        )
        return {"status": "sent", "token": token}


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
            "tenant_data": json.loads(obs.tenant_data) if obs.tenant_data else None,
            "signature_image": obs.signature_image or "",
        }


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

        # Save uploaded files to disk
        from pathlib import Path
        import base64 as b64mod
        media_dir = Path(os.getenv("MEDIA_DIR", "media"))
        token_short = obs.token[:8]
        saved_files = {}

        for field_name, data_url in [("selfie", req.selfie_photo), ("id_proof", req.id_photo)]:
            if not data_url or "base64," not in data_url:
                continue
            try:
                header, b64_data = data_url.split("base64,", 1)
                # Detect file type
                if "pdf" in header:
                    ext = ".pdf"
                elif "png" in header:
                    ext = ".png"
                elif "webp" in header:
                    ext = ".webp"
                else:
                    ext = ".jpg"
                save_dir = media_dir / "onboarding" / token_short
                save_dir.mkdir(parents=True, exist_ok=True)
                file_path = save_dir / f"{field_name}{ext}"
                file_path.write_bytes(b64mod.b64decode(b64_data))
                saved_files[field_name] = str(file_path.relative_to(media_dir))
            except Exception:
                pass  # non-fatal — form still submits

        # Save signature to disk too
        if req.signature_image and "base64," in req.signature_image:
            try:
                _, sig_b64 = req.signature_image.split("base64,", 1)
                save_dir = media_dir / "onboarding" / token_short
                save_dir.mkdir(parents=True, exist_ok=True)
                sig_path = save_dir / "signature.png"
                sig_path.write_bytes(b64mod.b64decode(sig_b64))
                saved_files["signature"] = str(sig_path.relative_to(media_dir))
            except Exception:
                pass

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
                    f"{os.getenv('BASE_URL', 'https://api.getkozzy.com')}/admin/onboarding"
                )
            except Exception:
                pass  # non-fatal

        return {"status": "pending_review", "message": "Submitted. Receptionist will review."}


# ── Approve session (admin) ──────────────────────────────────────────────────

class ApproveRequest(BaseModel):
    staff_signature: str = ""  # base64 PNG data URL
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

        room = await session.get(Room, obs.room_id)
        if not room:
            raise HTTPException(400, "Room not found")

        building = ""
        if room.property_id:
            prop = await session.get(Property, room.property_id)
            building = prop.name if prop else ""

        phone = td["phone"].strip()
        if len(phone) > 10:
            phone = phone[-10:]

        # Create or find tenant
        tenant = await session.scalar(select(Tenant).where(Tenant.phone == phone))
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

        rt = room.room_type
        sharing = rt.value if hasattr(rt, 'value') else str(rt or "")
        checkin = obs.checkin_date or date.today()
        is_daily = obs.stay_type == "daily"

        import asyncio as _aio
        import logging as _log
        _logger = _log.getLogger(__name__)
        gsheets_note = ""
        phone_sheet = f"+91{phone}" if len(phone) == 10 else phone

        if is_daily:
            # ── Daily stay path ────────────────────────────────────────────
            from src.database.models import DaywiseStay
            checkout = obs.checkout_date or (checkin + timedelta(days=obs.num_days or 1))
            num_days = obs.num_days or max(1, (checkout - checkin).days)
            total_amount = float(obs.agreed_rent or 0)  # agreed_rent stores total for daily

            dw = DaywiseStay(
                room_number=room.room_number,
                guest_name=td["name"],
                phone=phone,
                checkin_date=checkin,
                checkout_date=checkout,
                num_days=num_days,
                stay_period=f"{checkin.strftime('%d/%m')}-{checkout.strftime('%d/%m')}",
                sharing=1,
                booking_amount=obs.booking_amount or 0,
                daily_rate=obs.daily_rate or 0,
                total_amount=total_amount,
                maintenance=obs.maintenance_fee or 0,
                status="ACTIVE",
                comments=obs.special_terms or "",
            )
            session.add(dw)
            await session.flush()

            obs.status = "approved"
            obs.approved_at = datetime.utcnow()
            obs.tenant_id = tenant.id

            # GSheets DAY WISE tab (retry 3x)
            for attempt in range(3):
                try:
                    from src.integrations.gsheets import add_daywise_stay as gsheets_dw
                    gs_r = await gsheets_dw(
                        room_number=room.room_number, guest_name=td["name"], phone=phone_sheet,
                        checkin=checkin.strftime("%d/%m/%Y"),
                        stay_period=dw.stay_period, num_days=num_days,
                        daily_rate=float(obs.daily_rate or 0),
                        booking_amount=float(obs.booking_amount or 0),
                        total=total_amount, maintenance=float(obs.maintenance_fee or 0),
                        sharing=sharing, status="ACTIVE",
                        comments=obs.special_terms or "",
                    )
                    if gs_r.get("success"):
                        gsheets_note = " | DAY WISE Sheet updated"
                        break
                except Exception as e:
                    _logger.warning("GSheets DAY WISE attempt %d error: %s", attempt + 1, e)
                if attempt < 2:
                    await _aio.sleep(2 * (attempt + 1))

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
                tenant_id=tenant.id, room_id=room.id, checkin_date=checkin,
                agreed_rent=obs.agreed_rent or 0, security_deposit=obs.security_deposit or 0,
                booking_amount=obs.booking_amount or 0, maintenance_fee=obs.maintenance_fee or 0,
                lock_in_months=obs.lock_in_months or 0,
                sharing_type=sharing_default,
                status=TenancyStatus.active if checkin <= date.today() else TenancyStatus.no_show,
            )
            session.add(tenancy)
            await session.flush()

            # RentSchedule
            from src.services.rent_schedule import first_month_rent_due
            period = checkin.replace(day=1)
            current_month = date.today().replace(day=1)
            while period <= current_month:
                session.add(RentSchedule(
                    tenancy_id=tenancy.id, period_month=period,
                    rent_due=first_month_rent_due(tenancy, period),
                    maintenance_due=obs.maintenance_fee or 0,
                    status=RentStatus.pending, due_date=period,
                ))
                if period.month == 12:
                    period = date(period.year + 1, 1, 1)
                else:
                    period = date(period.year, period.month + 1, 1)

            # Advance payment
            if obs.booking_amount and obs.booking_amount > 0:
                adv_mode = PaymentMode.upi if obs.advance_mode == "upi" else PaymentMode.cash
                session.add(Payment(
                    tenancy_id=tenancy.id, amount=obs.booking_amount,
                    payment_date=checkin, payment_mode=adv_mode,
                    for_type=PaymentFor.booking, period_month=checkin.replace(day=1),
                    notes=f"Booking advance ({obs.advance_mode})",
                ))

            obs.status = "approved"
            obs.approved_at = datetime.utcnow()
            obs.tenant_id = tenant.id
            obs.tenancy_id = tenancy.id

            # GSheets TENANTS + monthly tab (retry 3x)
            gsheet_kwargs = dict(
                room_number=room.room_number, name=td["name"], phone=phone_sheet,
                gender=td.get("gender", ""), building=building,
                floor=str(room.floor or ""), sharing=effective_sharing or sharing,
                checkin=checkin.strftime("%d/%m/%Y"),
                agreed_rent=float(obs.agreed_rent or 0), deposit=float(obs.security_deposit or 0),
                booking=float(obs.booking_amount or 0), maintenance=float(obs.maintenance_fee or 0),
                notes=obs.special_terms or "",
                dob=td.get("date_of_birth", ""), father_name=td.get("father_name", ""),
                father_phone=td.get("father_phone", ""), address=td.get("permanent_address", ""),
                emergency_contact=td.get("emergency_contact_phone", ""),
                emergency_relationship=td.get("emergency_contact_relationship", ""),
                email=td.get("email", ""), occupation=td.get("occupation", ""),
                education=td.get("educational_qualification", ""),
                office_address=td.get("office_address", ""), office_phone=td.get("office_phone", ""),
                id_type=td.get("id_proof_type", ""), id_number=td.get("id_proof_number", ""),
                food_pref=td.get("food_preference", ""), entered_by="onboarding_form",
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

        # Save staff signature to disk
        staff_sig_path = ""
        if req and req.staff_signature and "base64," in req.staff_signature:
            try:
                import base64 as b64mod
                from pathlib import Path
                media_dir = Path(os.getenv("MEDIA_DIR", "media"))
                _, sig_b64 = req.staff_signature.split("base64,", 1)
                save_dir = media_dir / "onboarding" / obs.token[:8]
                save_dir.mkdir(parents=True, exist_ok=True)
                sig_file = save_dir / "staff_signature.png"
                sig_file.write_bytes(b64mod.b64decode(sig_b64))
                staff_sig_path = str(sig_file.relative_to(media_dir))
            except Exception:
                pass

        # PDF generation (includes both tenant + staff signatures)
        try:
            from src.services.pdf_generator import generate_agreement_pdf
            pdf_path = await generate_agreement_pdf(
                obs, td, room, building, sharing,
                staff_signature=req.staff_signature if req else "",
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
        for file_key, doc_type in doc_map.items():
            file_path = saved_files.get(file_key)
            if file_path:
                session.add(Document(
                    doc_type=doc_type,
                    file_path=file_path,
                    original_name=f"{file_key}_{td.get('name', 'tenant')}",
                    mime_type="image/png" if file_key == "signature" else "image/jpeg",
                    tenant_id=tenant.id,
                    tenancy_id=tenancy.id,
                ))
        # Agreement PDF as document
        if obs.agreement_pdf_path:
            session.add(Document(
                doc_type=DocumentType.agreement,
                file_path=obs.agreement_pdf_path,
                original_name=f"agreement_{td.get('name', 'tenant')}",
                mime_type="application/pdf",
                tenant_id=tenant.id,
                tenancy_id=tenancy.id,
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
                from pathlib import Path
                # Build public URL for the PDF
                base_url = os.getenv("BASE_URL", "https://api.getkozzy.com")
                pdf_url = f"{base_url}/static/agreements/{obs.agreement_pdf_path}"
                # Also copy PDF to static dir so it's accessible
                media_dir = Path(os.getenv("MEDIA_DIR", "media"))
                src_pdf = media_dir / obs.agreement_pdf_path
                static_pdf_dir = Path("static/agreements") / Path(obs.agreement_pdf_path).parent.name
                static_pdf_dir.mkdir(parents=True, exist_ok=True)
                static_pdf = static_pdf_dir / Path(obs.agreement_pdf_path).name
                if src_pdf.exists():
                    import shutil
                    shutil.copy2(str(src_pdf), str(static_pdf))

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
                tpl_sent = await _send_whatsapp_template(
                    phone_wa,
                    "cozeevo_booking_confirmation",
                    [tenant_name, room.room_number, checkin_str, rent_str, deposit_str],
                )
                # Fallback: if template not approved yet, send free text
                # (works only if tenant messaged us in the last 24h).
                if tpl_sent is False or tpl_sent is None:
                    await _send_whatsapp(
                        phone_wa,
                        f"Welcome to Cozeevo, {tenant_name}!\n\n"
                        f"Your booking is confirmed.\n"
                        f"Room: {room.room_number}\n"
                        f"Check-in: {checkin_str}\n"
                        f"Monthly rent: {rent_str}\n"
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
                                entity_id=tenancy.id if 'tenancy' in dir() and not is_daily else 0,
                                entity_name=tenant_name, field=k,
                                old_value=str(original_financial.get(k, "")),
                                new_value=str(final_financial.get(k, "")),
                                room_number=room.room_number, source="onboarding_review",
                                note="receptionist override at approve",
                            ))
                    # Sharing-type override — tenancy-level only, never room.
                    if effective_sharing and effective_sharing != master_sharing:
                        session.add(_AL(
                            changed_by="receptionist", entity_type="tenancy",
                            entity_id=tenancy.id if 'tenancy' in dir() and not is_daily else 0,
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
                                room_number=room.room_number, source="onboarding_review",
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
        _tenancy_id = getattr(obs, "tenancy_id", None) or (tenancy.id if 'tenancy' in dir() and not is_daily else None)

        return {
            "status": "approved", "tenant_id": tenant.id, "tenancy_id": _tenancy_id,
            "message": f"Tenant {td['name']} created{gsheets_note}{whatsapp_note} | Sheet summary refresh queued",
        }
