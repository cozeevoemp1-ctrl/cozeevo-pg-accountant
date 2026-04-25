"""
src/api/checkout_router.py
Checkout form API — receptionist creates session, tenant confirms via WhatsApp.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.db_manager import get_session
from src.database.models import (
    CheckoutSession, CheckoutSessionStatus,
    Tenancy, TenancyStatus, Tenant, Room,
)
from src.api.onboarding_router import _check_admin_pin, _rate_check

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/checkout", tags=["checkout"])

SESSION_TTL_HOURS = 2


# ── Pydantic models ──────────────────────────────────────────────────────────

class CreateCheckoutRequest(BaseModel):
    tenancy_id: int
    checkout_date: str           # ISO YYYY-MM-DD
    room_key_returned: bool
    wardrobe_key_returned: bool
    biometric_removed: bool
    room_condition_ok: bool
    damage_notes: str = ""
    security_deposit: float
    pending_dues: float
    deductions: float
    deduction_reason: str = ""
    refund_amount: float
    refund_mode: str             # cash / upi / bank
    created_by_phone: str = ""


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _get_pending_dues(tenancy_id: int, session: AsyncSession) -> Decimal:
    """Sum of unpaid rent + maintenance for a tenancy."""
    try:
        from src.whatsapp.handlers.account_handler import _calc_outstanding_dues
        o_rent, o_maint = await _calc_outstanding_dues(tenancy_id, session)
        return o_rent + o_maint
    except Exception as e:
        logger.warning("Could not calculate pending dues for tenancy %s: %s", tenancy_id, e)
        return Decimal("0")


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/tenants")
async def search_tenants(q: str, request: Request):
    """Autocomplete: active tenants matching name or room number."""
    _check_admin_pin(request)
    _rate_check(f"co_search:{request.client.host}", 60, 60)
    async with get_session() as session:
        stmt = (
            select(Tenancy, Tenant, Room)
            .join(Tenant, Tenancy.tenant_id == Tenant.id)
            .join(Room, Tenancy.room_id == Room.id)
            .where(
                Tenancy.status == TenancyStatus.active,
                Tenant.name.ilike(f"%{q}%") | Room.room_number.ilike(f"%{q}%"),
            )
            .limit(10)
        )
        rows = (await session.execute(stmt)).all()
        return [
            {
                "tenancy_id": t.id,
                "label": f"{tn.name} (Room {r.room_number})",
                "tenant_name": tn.name,
                "phone": tn.phone,
                "room_number": r.room_number,
            }
            for t, tn, r in rows
        ]


@router.get("/tenant/{tenancy_id}")
async def prefetch_tenancy(tenancy_id: int, request: Request):
    """Pre-fill: fetch deposit, pending dues, notice date for a tenancy."""
    _check_admin_pin(request)
    async with get_session() as session:
        tenancy = await session.get(Tenancy, tenancy_id)
        if not tenancy or tenancy.status != TenancyStatus.active:
            raise HTTPException(404, "Active tenancy not found")
        tenant = await session.get(Tenant, tenancy.tenant_id)
        room = await session.get(Room, tenancy.room_id)
        dues = await _get_pending_dues(tenancy_id, session)
        return {
            "tenancy_id": tenancy_id,
            "tenant_name": tenant.name if tenant else "",
            "phone": tenant.phone if tenant else "",
            "room_number": room.room_number if room else "",
            "security_deposit": float(tenancy.security_deposit or 0),
            "pending_dues": float(dues),
            "notice_date": tenancy.notice_date.isoformat() if tenancy.notice_date else None,
        }


@router.post("/create")
async def create_checkout_session(req: CreateCheckoutRequest, request: Request):
    """
    Receptionist submits checkout form.
    Creates CheckoutSession, sends WhatsApp summary to tenant for confirmation.
    """
    _check_admin_pin(request)
    _rate_check(f"co_create:{request.client.host}", 10, 60)

    try:
        checkout_date = date.fromisoformat(req.checkout_date)
    except ValueError:
        raise HTTPException(400, "Invalid checkout_date format (use YYYY-MM-DD)")

    async with get_session() as session:
        tenancy = await session.get(Tenancy, req.tenancy_id)
        if not tenancy or tenancy.status != TenancyStatus.active:
            raise HTTPException(404, "Active tenancy not found")
        tenant = await session.get(Tenant, tenancy.tenant_id)
        if not tenant:
            raise HTTPException(404, "Tenant not found")
        room = await session.get(Room, tenancy.room_id)

        # Cancel any existing pending session for this tenancy
        from sqlalchemy import select as _sel
        existing = await session.scalar(
            _sel(CheckoutSession).where(
                CheckoutSession.tenancy_id == req.tenancy_id,
                CheckoutSession.status == CheckoutSessionStatus.pending,
            )
        )
        if existing:
            existing.status = CheckoutSessionStatus.cancelled

        cs = CheckoutSession(
            token                 = str(uuid.uuid4()),
            status                = CheckoutSessionStatus.pending.value,
            created_by_phone      = req.created_by_phone or "unknown",
            tenant_phone          = tenant.phone,
            tenancy_id            = req.tenancy_id,
            checkout_date         = checkout_date,
            room_key_returned     = req.room_key_returned,
            wardrobe_key_returned = req.wardrobe_key_returned,
            biometric_removed     = req.biometric_removed,
            room_condition_ok     = req.room_condition_ok,
            damage_notes          = req.damage_notes or None,
            security_deposit      = Decimal(str(req.security_deposit)),
            pending_dues          = Decimal(str(req.pending_dues)),
            deductions            = Decimal(str(req.deductions)),
            deduction_reason      = req.deduction_reason or None,
            refund_amount         = Decimal(str(req.refund_amount)),
            refund_mode           = req.refund_mode or None,
            expires_at            = datetime.utcnow() + timedelta(hours=SESSION_TTL_HOURS),
        )
        session.add(cs)
        await session.flush()

        room_number = room.room_number if room else "?"
        key_line    = f"Room key: {'Returned' if cs.room_key_returned else 'Not returned'}"
        ward_line   = f"Wardrobe key: {'Returned' if cs.wardrobe_key_returned else 'Not returned'}"
        bio_line    = f"Biometric: {'Removed' if cs.biometric_removed else 'Not removed'}"
        room_line   = f"Room condition: {'OK' if cs.room_condition_ok else 'Damage noted'}"
        refund_line = (
            f"Refund: Rs.{int(cs.refund_amount):,} via {cs.refund_mode}"
            if cs.refund_amount > 0 else "Refund: Rs.0"
        )

        msg = (
            f"Hi {tenant.name}, your checkout from Room {room_number} "
            f"on {checkout_date.strftime('%d %b %Y')} has been recorded.\n\n"
            f"Summary:\n"
            f"- {key_line}\n"
            f"- {ward_line}\n"
            f"- {bio_line}\n"
            f"- {room_line}\n"
            f"- {refund_line}\n\n"
            f"Reply *YES* to confirm.\n"
            f"If you disagree, reply *NO* followed by your reason "
            f"(e.g. NO the damage charge is wrong).\n"
            f"If no response in 2 hours, this will be auto-confirmed."
        )

        phone_wa = f"+91{tenant.phone}" if not tenant.phone.startswith("+") else tenant.phone
        try:
            from src.whatsapp.webhook_handler import _send_whatsapp
            await _send_whatsapp(phone_wa, msg)
        except Exception as _e:
            logger.warning("WhatsApp send failed for checkout request: %s", _e)

        await session.commit()
        return {
            "status": "pending",
            "token": cs.token,
            "expires_at": cs.expires_at.isoformat(),
        }


@router.get("/status/{token}")
async def poll_session_status(token: str, request: Request):
    """Admin page polls this to know when tenant has responded."""
    _check_admin_pin(request)
    async with get_session() as session:
        cs = await session.scalar(
            select(CheckoutSession).where(CheckoutSession.token == token)
        )
        if not cs:
            raise HTTPException(404, "Session not found")
        return {
            "token": cs.token,
            "status": cs.status,
            "confirmed_at": cs.confirmed_at.isoformat() if cs.confirmed_at else None,
            "rejection_reason": cs.rejection_reason,
            "expires_at": cs.expires_at.isoformat(),
        }
