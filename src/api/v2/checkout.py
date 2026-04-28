"""
GET  /api/v2/app/checkout/tenant/{tenancy_id} — prefetch deposit + dues
POST /api/v2/app/checkout/create               — create checkout session (JWT-protected)
GET  /api/v2/app/checkout/status/{token}       — poll session status (JWT-protected)
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from src.api.v2.auth import AppUser, get_current_user
from src.database.db_manager import get_session
from src.database.models import (
    CheckoutSession, CheckoutSessionStatus,
    Tenancy, TenancyStatus, Tenant, Room,
)

logger = logging.getLogger(__name__)
router = APIRouter()

SESSION_TTL_HOURS = 2


# ── GET prefetch ─────────────────────────────────────────────────────────────

@router.get("/checkout/tenant/{tenancy_id}")
async def checkout_prefetch(
    tenancy_id: int,
    user: AppUser = Depends(get_current_user),
):
    """Prefill: fetch deposit, pending dues, notice date for a tenancy."""
    async with get_session() as session:
        tenancy = await session.get(Tenancy, tenancy_id)
        if not tenancy or tenancy.status != TenancyStatus.active:
            raise HTTPException(404, "Active tenancy not found")
        tenant = await session.get(Tenant, tenancy.tenant_id)
        room   = await session.get(Room,   tenancy.room_id)

        from src.api.checkout_router import _get_pending_dues
        dues = await _get_pending_dues(tenancy_id, session)

        return {
            "tenancy_id":       tenancy_id,
            "tenant_name":      tenant.name if tenant else "",
            "phone":            tenant.phone if tenant else "",
            "room_number":      room.room_number if room else "",
            "security_deposit": float(tenancy.security_deposit or 0),
            "pending_dues":     float(dues),
            "notice_date":      tenancy.notice_date.isoformat() if tenancy.notice_date else None,
        }


# ── POST create ──────────────────────────────────────────────────────────────

class CheckoutCreateBody(BaseModel):
    tenancy_id:            int
    checkout_date:         str     # YYYY-MM-DD
    room_key_returned:     bool
    wardrobe_key_returned: bool
    biometric_removed:     bool
    room_condition_ok:     bool
    damage_notes:          str = ""
    security_deposit:      float
    pending_dues:          float
    deductions:            float
    deduction_reason:      str = ""
    refund_amount:         float
    refund_mode:           str     # cash / upi / bank


@router.post("/checkout/create", status_code=201)
async def create_checkout(
    body: CheckoutCreateBody,
    user: AppUser = Depends(get_current_user),
):
    if user.role not in ("admin", "staff"):
        raise HTTPException(403, "admin or staff only")

    try:
        checkout_date_obj = date.fromisoformat(body.checkout_date)
    except ValueError:
        raise HTTPException(400, "Invalid checkout_date — use YYYY-MM-DD")

    async with get_session() as session:
        tenancy = await session.get(Tenancy, body.tenancy_id)
        if not tenancy or tenancy.status != TenancyStatus.active:
            raise HTTPException(404, "Active tenancy not found")
        tenant = await session.get(Tenant, tenancy.tenant_id)
        if not tenant:
            raise HTTPException(404, "Tenant not found")
        room = await session.get(Room, tenancy.room_id)

        # Cancel any existing pending session for this tenancy
        existing = await session.scalar(
            select(CheckoutSession).where(
                CheckoutSession.tenancy_id == body.tenancy_id,
                CheckoutSession.status == CheckoutSessionStatus.pending,
            )
        )
        if existing:
            existing.status = CheckoutSessionStatus.cancelled

        cs = CheckoutSession(
            token                 = str(uuid.uuid4()),
            status                = CheckoutSessionStatus.pending.value,
            created_by_phone      = user.phone or user.user_id or "pwa",
            tenant_phone          = tenant.phone,
            tenancy_id            = body.tenancy_id,
            checkout_date         = checkout_date_obj,
            room_key_returned     = body.room_key_returned,
            wardrobe_key_returned = body.wardrobe_key_returned,
            biometric_removed     = body.biometric_removed,
            room_condition_ok     = body.room_condition_ok,
            damage_notes          = body.damage_notes or None,
            security_deposit      = Decimal(str(body.security_deposit)),
            pending_dues          = Decimal(str(body.pending_dues)),
            deductions            = Decimal(str(body.deductions)),
            deduction_reason      = body.deduction_reason or None,
            refund_amount         = Decimal(str(body.refund_amount)),
            refund_mode           = body.refund_mode or None,
            expires_at            = datetime.utcnow() + timedelta(hours=SESSION_TTL_HOURS),
        )
        session.add(cs)
        await session.flush()

        base_url     = os.getenv("BASE_URL", "https://api.getkozzy.com")
        confirm_link = f"{base_url}/checkout/{cs.token}"

        room_number = room.room_number if room else "?"
        refund_line = (
            f"Rs.{int(cs.refund_amount):,} via {cs.refund_mode.upper()}"
            if cs.refund_amount > 0 else "Rs.0 (no refund)"
        )
        date_str = checkout_date_obj.strftime("%d %b %Y")
        phone_wa = f"+91{tenant.phone}" if not tenant.phone.startswith("+") else tenant.phone

        try:
            from src.whatsapp.webhook_handler import _send_whatsapp_template, _send_whatsapp
            sent = await _send_whatsapp_template(
                phone_wa, "checkout_review",
                [tenant.name, room_number, date_str, refund_line],
                url_button_token=cs.token,
            )
            if not sent:
                msg = (
                    f"Hi {tenant.name}, your checkout from Room {room_number} "
                    f"on {date_str} has been recorded.\n\n"
                    f"Refund: {refund_line}\n\n"
                    f"Please review and confirm or dispute:\n"
                    f"{confirm_link}\n\n"
                    f"If no response in 2 hours, this will be auto-confirmed."
                )
                await _send_whatsapp(phone_wa, msg)
        except Exception as e:
            logger.warning("WhatsApp notification failed for checkout: %s", e)

        await session.commit()
        return {
            "status":       "pending",
            "token":        cs.token,
            "confirm_link": confirm_link,
            "expires_at":   cs.expires_at.isoformat(),
        }


# ── GET status ───────────────────────────────────────────────────────────────

@router.get("/checkout/status/{token}")
async def checkout_status(
    token: str,
    user: AppUser = Depends(get_current_user),
):
    async with get_session() as session:
        cs = await session.scalar(
            select(CheckoutSession).where(CheckoutSession.token == token)
        )
        if not cs:
            raise HTTPException(404, "Checkout session not found")
        return {
            "token":            cs.token,
            "status":           cs.status,
            "confirmed_at":     cs.confirmed_at.isoformat() if cs.confirmed_at else None,
            "rejection_reason": cs.rejection_reason,
            "expires_at":       cs.expires_at.isoformat(),
        }
