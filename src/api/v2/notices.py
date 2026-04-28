"""
GET /api/v2/app/notices/active  — active tenants on notice, sorted by expected checkout
"""
from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import select

from src.api.v2.auth import AppUser, get_current_user
from src.database.db_manager import get_session
from src.database.models import Tenancy, TenancyStatus, Tenant, Room
from services.property_logic import NOTICE_BY_DAY, calc_notice_last_day

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/notices/active")
async def get_active_notices(user: AppUser = Depends(get_current_user)):
    """All active tenants on notice, sorted by expected checkout date (soonest first)."""
    today = date.today()

    async with get_session() as session:
        stmt = (
            select(Tenancy, Tenant, Room)
            .join(Tenant, Tenancy.tenant_id == Tenant.id)
            .join(Room, Tenancy.room_id == Room.id)
            .where(
                Tenancy.status == TenancyStatus.active,
                Tenancy.notice_date.isnot(None),
            )
        )
        rows = (await session.execute(stmt)).all()

        results = []
        for tenancy, tenant, room in rows:
            nd = tenancy.notice_date
            deposit_eligible = nd.day <= NOTICE_BY_DAY
            expected_checkout = calc_notice_last_day(nd)
            days_remaining = (expected_checkout - today).days

            results.append({
                "tenancy_id":        tenancy.id,
                "tenant_name":       tenant.name,
                "phone":             tenant.phone,
                "room_number":       room.room_number,
                "notice_date":       nd.isoformat(),
                "expected_checkout": expected_checkout.isoformat(),
                "deposit_eligible":  deposit_eligible,
                "security_deposit":  float(tenancy.security_deposit or 0),
                "maintenance_fee":   float(tenancy.maintenance_fee or 0),
                "agreed_rent":       float(tenancy.agreed_rent or 0),
                "days_remaining":    days_remaining,
            })

        results.sort(key=lambda x: (x["expected_checkout"], x["tenant_name"]))
        return results
