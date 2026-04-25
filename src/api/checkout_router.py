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
