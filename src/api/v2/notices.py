"""
GET /api/v2/app/notices/active  — active monthly tenants who have given formal notice
"""
from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import select

from src.api.v2.auth import AppUser, get_current_user
from src.database.db_manager import get_session
from src.database.models import Tenancy, TenancyStatus, StayType, Tenant, Room
from services.property_logic import NOTICE_BY_DAY, calc_notice_last_day

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/notices/active")
async def get_active_notices(user: AppUser = Depends(get_current_user)):
    """Active monthly tenants who have given formal notice, sorted by expected checkout."""
    today = date.today()

    async with get_session() as session:
        notice_rows = (await session.execute(
            select(Tenancy, Tenant, Room)
            .join(Tenant, Tenancy.tenant_id == Tenant.id)
            .join(Room, Tenancy.room_id == Room.id)
            .where(
                Room.is_staff_room == False,
                Room.room_number != "UNASSIGNED",
                Tenancy.status == TenancyStatus.active,
                Tenancy.stay_type == StayType.monthly,
                Tenancy.notice_date.isnot(None),
            )
        )).all()

        results = []
        for tenancy, tenant, room in notice_rows:
            nd = tenancy.notice_date
            deposit_eligible = nd.day <= NOTICE_BY_DAY
            expected_checkout = tenancy.expected_checkout or calc_notice_last_day(nd)
            days_remaining = (expected_checkout - today).days
            results.append({
                "tenancy_id":        tenancy.id,
                "tenant_name":       tenant.name,
                "phone":             tenant.phone,
                "room_number":       room.room_number,
                "notice_date":       nd.isoformat(),
                "expected_checkout": expected_checkout.isoformat(),
                "deposit_eligible":  deposit_eligible,
                "has_notice":        True,
                "security_deposit":  float(tenancy.security_deposit or 0),
                "maintenance_fee":   float(tenancy.maintenance_fee or 0),
                "agreed_rent":       float(tenancy.agreed_rent or 0),
                "days_remaining":    days_remaining,
            })

        results.sort(key=lambda x: (x["expected_checkout"], x["tenant_name"]))
        return results
