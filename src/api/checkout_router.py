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
            status                = CheckoutSessionStatus.confirmed.value,
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

        from src.whatsapp.handlers.owner_handler import _do_confirm_checkout
        await _do_confirm_checkout(cs, session)

        await session.commit()
        return {
            "status": "confirmed",
            "token": cs.token,
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


# ── Tenant-facing endpoints (token is the auth) ──────────────────────────────

@router.get("/summary/{token}")
async def get_checkout_summary(token: str):
    """Tenant opens this to see checkout summary before confirming."""
    async with get_session() as session:
        cs = await session.scalar(
            select(CheckoutSession).where(CheckoutSession.token == token)
        )
        if not cs:
            raise HTTPException(404, "Checkout session not found")
        tenancy = await session.get(Tenancy, cs.tenancy_id)
        tenant  = await session.get(Tenant, tenancy.tenant_id) if tenancy else None
        room    = await session.get(Room, tenancy.room_id) if tenancy else None
        return {
            "token": cs.token,
            "status": cs.status,
            "tenant_name": tenant.name if tenant else "",
            "room_number": room.room_number if room else "?",
            "checkout_date": cs.checkout_date.isoformat(),
            "room_key_returned": cs.room_key_returned,
            "wardrobe_key_returned": cs.wardrobe_key_returned,
            "biometric_removed": cs.biometric_removed,
            "room_condition_ok": cs.room_condition_ok,
            "damage_notes": cs.damage_notes or "",
            "security_deposit": float(cs.security_deposit),
            "pending_dues": float(cs.pending_dues),
            "deductions": float(cs.deductions),
            "deduction_reason": cs.deduction_reason or "",
            "refund_amount": float(cs.refund_amount),
            "refund_mode": cs.refund_mode or "",
            "expires_at": cs.expires_at.isoformat(),
        }


class TenantRespondRequest(BaseModel):
    decision: str   # "confirm" or "dispute"
    reason: str = ""


@router.post("/respond/{token}")
async def tenant_respond(token: str, req: TenantRespondRequest):
    """Tenant confirms or disputes checkout via the web link."""
    if req.decision not in ("confirm", "dispute"):
        raise HTTPException(400, "decision must be 'confirm' or 'dispute'")

    async with get_session() as session:
        cs = await session.scalar(
            select(CheckoutSession)
            .where(CheckoutSession.token == token)
            .with_for_update()
        )
        if not cs:
            raise HTTPException(404, "Checkout session not found")
        if cs.status != CheckoutSessionStatus.pending.value:
            raise HTTPException(409, f"Session already {cs.status}")

        if req.decision == "confirm":
            cs.status = CheckoutSessionStatus.confirmed.value
            from src.whatsapp.handlers.owner_handler import _do_confirm_checkout
            summary = await _do_confirm_checkout(cs, session)

            # Notify tenant
            phone_wa = (
                f"+91{cs.tenant_phone}"
                if not cs.tenant_phone.startswith("+") else cs.tenant_phone
            )
            tenancy = await session.get(Tenancy, cs.tenancy_id)
            room    = await session.get(Room, tenancy.room_id) if tenancy else None
            room_no = room.room_number if room else "?"
            refund_line = (
                f"Refund of Rs.{int(cs.refund_amount):,} will be processed by the receptionist."
                if cs.refund_amount > 0 else ""
            )
            confirmed_msg = (
                f"Your checkout from Room {room_no} on "
                f"{cs.checkout_date.strftime('%d %b %Y')} is confirmed.\n"
                + (f"{refund_line}\n" if refund_line else "")
                + "Thank you for staying with Cozeevo."
            )
            try:
                from src.whatsapp.webhook_handler import _send_whatsapp
                await _send_whatsapp(phone_wa, confirmed_msg)
            except Exception as _e:
                logger.warning("Failed to send checkout confirmed to tenant: %s", _e)

            # Notify receptionist
            try:
                recep_phone = (
                    f"+91{cs.created_by_phone}"
                    if not cs.created_by_phone.startswith("+") else cs.created_by_phone
                )
                await _send_whatsapp(recep_phone, summary)
            except Exception as _e:
                logger.warning("Failed to notify receptionist: %s", _e)

            await session.commit()
            return {"status": "confirmed"}

        else:  # dispute
            cs.status = CheckoutSessionStatus.rejected.value
            cs.rejection_reason = req.reason or "Tenant disputed via web form"
            await session.flush()

            # Notify receptionist
            try:
                tenancy = await session.get(Tenancy, cs.tenancy_id)
                tenant  = await session.get(Tenant, tenancy.tenant_id) if tenancy else None
                room    = await session.get(Room, tenancy.room_id) if tenancy else None
                tenant_name = tenant.name if tenant else "Tenant"
                room_no = room.room_number if room else "?"
                recep_phone = (
                    f"+91{cs.created_by_phone}"
                    if not cs.created_by_phone.startswith("+") else cs.created_by_phone
                )
                from src.whatsapp.webhook_handler import _send_whatsapp
                await _send_whatsapp(
                    recep_phone,
                    f"{tenant_name} (Room {room_no}) disputed the checkout.\n"
                    f"Reason: {cs.rejection_reason}\n"
                    "Please follow up and create a new checkout session."
                )
            except Exception as _e:
                logger.warning("Failed to notify receptionist of dispute: %s", _e)

            await session.commit()
            return {"status": "disputed"}
