"""
GET /api/v2/app/notices/active  — active monthly tenants who have given formal notice
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select, func

from src.api.v2.auth import AppUser, get_current_user
from src.database.db_manager import get_session
from src.database.models import Tenancy, TenancyStatus, StayType, Tenant, Room
from services.property_logic import calc_notice_last_day

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
                Room.room_number != "000",
                Tenancy.status == TenancyStatus.active,
                Tenancy.stay_type == StayType.monthly,
                Tenancy.notice_date.isnot(None),
            )
        )).all()

        # Total active monthly tenants per room (to detect full-room exits)
        room_active_rows = (await session.execute(
            select(Tenancy.room_id, func.count(Tenancy.id).label("cnt"))
            .join(Room, Tenancy.room_id == Room.id)
            .where(
                Room.is_staff_room == False,
                Room.room_number != "000",
                Tenancy.status == TenancyStatus.active,
                Tenancy.stay_type == StayType.monthly,
            )
            .group_by(Tenancy.room_id)
        )).all()
        room_active_counts: dict[int, int] = {r.room_id: r.cnt for r in room_active_rows}

        # Count notices per room + track each tenancy's expected_checkout
        room_notice_counts: dict[int, int] = defaultdict(int)
        tenancy_expected: dict[int, date] = {}
        room_notice_checkouts: dict[int, list[date]] = defaultdict(list)
        for tenancy, tenant, room in notice_rows:
            room_notice_counts[room.id] += 1
            ec = tenancy.expected_checkout or calc_notice_last_day(tenancy.notice_date)
            tenancy_expected[tenancy.id] = ec
            room_notice_checkouts[room.id].append(ec)

        results = []
        for tenancy, tenant, room in notice_rows:
            nd = tenancy.notice_date
            expected_checkout = tenancy_expected[tenancy.id]
            days_remaining = (expected_checkout - today).days

            is_premium = tenancy.sharing_type is not None and tenancy.sharing_type.value == "premium"
            beds_freed = room.max_occupancy if is_premium else 1
            room_active_count = room_active_counts.get(room.id, 0)
            room_notice_count = room_notice_counts[room.id]
            # Full exit = all active tenants have notice AND this is the last one out
            room_max_checkout = max(room_notice_checkouts[room.id])
            is_full_exit = (
                room_notice_count >= room_active_count > 0
                and expected_checkout >= room_max_checkout
            )

            results.append({
                "tenancy_id":         tenancy.id,
                "tenant_name":        tenant.name,
                "phone":              tenant.phone,
                "room_number":        room.room_number,
                "gender":             tenant.gender,
                "notice_date":        nd.isoformat(),
                "expected_checkout":  expected_checkout.isoformat(),
                "deposit_eligible":   True,   # notice given → always eligible; only forfeited with no notice
                "has_notice":         True,
                "security_deposit":   float(tenancy.security_deposit or 0),
                "maintenance_fee":    float(tenancy.maintenance_fee or 0),
                "agreed_rent":        float(tenancy.agreed_rent or 0),
                "days_remaining":     days_remaining,
                "sharing_type":       tenancy.sharing_type.value if tenancy.sharing_type else None,
                "beds_freed":         beds_freed,
                "room_max_occupancy": room.max_occupancy,
                "room_active_count":  room_active_count,
                "room_notice_count":  room_notice_count,
                "is_full_exit":       is_full_exit,
            })

        results.sort(key=lambda x: (x["expected_checkout"], x["tenant_name"]))

        # Day-stay tenants checking out within 30 days
        daily_rows = (await session.execute(
            select(Tenancy, Tenant, Room)
            .join(Tenant, Tenancy.tenant_id == Tenant.id)
            .join(Room, Tenancy.room_id == Room.id)
            .where(
                Room.is_staff_room == False,
                Room.room_number != "000",
                Tenancy.status == TenancyStatus.active,
                Tenancy.stay_type == StayType.daily,
                Tenancy.checkout_date.isnot(None),
                Tenancy.checkout_date >= today,
                Tenancy.checkout_date <= today + timedelta(days=30),
            )
        )).all()

        for tenancy, tenant, room in daily_rows:
            co = tenancy.checkout_date
            days_remaining = (co - today).days if co else 9999
            results.append({
                "tenancy_id":        tenancy.id,
                "tenant_name":       tenant.name,
                "phone":             tenant.phone,
                "room_number":       room.room_number,
                "gender":            tenant.gender,
                "notice_date":       None,
                "expected_checkout": co.isoformat() if co else None,
                "deposit_eligible":  False,
                "has_notice":        False,
                "stay_type":         "daily",
                "security_deposit":  float(tenancy.security_deposit or 0),
                "maintenance_fee":   float(tenancy.maintenance_fee or 0),
                "agreed_rent":       float(tenancy.agreed_rent or 0),
                "days_remaining":    days_remaining,
                "sharing_type":      tenancy.sharing_type.value if tenancy.sharing_type else None,
                "beds_freed":        1,
                "room_max_occupancy": room.max_occupancy,
                "room_active_count": 1,
                "room_notice_count": 1,
                "is_full_exit":      False,
            })

        return results
