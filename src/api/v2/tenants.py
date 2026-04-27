"""GET /api/v2/app/tenants/search — tenant search for the Owner PWA.
GET /api/v2/app/tenants/{tenancy_id}/dues — dues for current month.
"""
from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_, select

from src.api.v2.auth import AppUser, get_current_user
from src.database.db_manager import get_session
from src.database.models import (
    Payment,
    PaymentFor,
    Property,
    RentSchedule,
    Room,
    Tenancy,
    TenancyStatus,
    Tenant,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _building_code(property_name: str) -> str:
    """Extract building code from property name, e.g. 'Cozeevo THOR' → 'THOR'."""
    return property_name.split()[-1] if property_name else ""


@router.get("/tenants/search")
async def search_tenants(
    q: str = Query(default=None),
    user: AppUser = Depends(get_current_user),
):
    if not q or not q.strip():
        raise HTTPException(status_code=400, detail="q must not be empty")

    term = q.strip().lower()

    async with get_session() as session:
        stmt = (
            select(Tenancy, Tenant, Room, Property)
            .join(Tenant, Tenancy.tenant_id == Tenant.id)
            .join(Room, Tenancy.room_id == Room.id)
            .join(Property, Room.property_id == Property.id)
            .where(
                Tenancy.status.in_([TenancyStatus.active, TenancyStatus.no_show]),
                or_(
                    func.lower(Tenant.name).contains(term),
                    func.lower(Room.room_number).contains(term),
                    func.lower(Tenant.phone).contains(term),
                ),
            )
            .order_by(Tenant.name)
            .limit(10)
        )
        rows = (await session.execute(stmt)).all()

    return [
        {
            "tenancy_id": tenancy.id,
            "tenant_id": tenant.id,
            "name": tenant.name,
            "phone": tenant.phone,
            "room_number": room.room_number,
            "building_code": _building_code(prop.name),
            "rent": float(tenancy.agreed_rent) if tenancy.agreed_rent is not None else 0.0,
            "status": tenancy.status.value,
        }
        for tenancy, tenant, room, prop in rows
    ]


@router.get("/tenants/{tenancy_id}/dues")
async def get_tenant_dues(
    tenancy_id: int,
    user: AppUser = Depends(get_current_user),
):
    async with get_session() as session:
        row = await session.execute(
            select(Tenancy, Tenant, Room, Property)
            .join(Tenant, Tenancy.tenant_id == Tenant.id)
            .join(Room, Tenancy.room_id == Room.id)
            .join(Property, Room.property_id == Property.id)
            .where(Tenancy.id == tenancy_id)
        )
        result = row.first()

    if result is None:
        raise HTTPException(status_code=404, detail=f"Tenancy {tenancy_id} not found")

    tenancy, tenant, room, prop = result

    # Current period: first day of current month
    today = date.today()
    period_month = date(today.year, today.month, 1)

    next_m = today.month % 12 + 1
    next_y = today.year + (1 if today.month == 12 else 0)
    period_end = date(next_y, next_m, 1)

    async with get_session() as session:
        # Rent paid this period — includes deposit/booking paid in same calendar month
        paid_result = await session.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0)).where(
                Payment.tenancy_id == tenancy_id,
                Payment.is_void == False,
                or_(
                    and_(Payment.for_type == PaymentFor.rent, Payment.period_month == period_month),
                    and_(
                        Payment.for_type.in_([PaymentFor.deposit, PaymentFor.booking]),
                        Payment.period_month == None,
                        Payment.payment_date >= period_month,
                        Payment.payment_date < period_end,
                    ),
                ),
            )
        )
        # RentSchedule for this period (has correct rent_due: rent+deposit for first month)
        rs = await session.scalar(
            select(RentSchedule).where(
                RentSchedule.tenancy_id == tenancy_id,
                RentSchedule.period_month == period_month,
            )
        )

    rent = float(tenancy.agreed_rent) if tenancy.agreed_rent is not None else 0.0
    paid = float(paid_result) if paid_result is not None else 0.0

    # rent_due from RentSchedule is the source of truth — already set from ops sheet
    # (fix_april_dues.py locked these to exact sheet balances, advance already factored in)
    rent_due = float(rs.rent_due) if rs else rent

    dues = max(rent_due - paid, 0.0)
    booking_amount = float(tenancy.booking_amount) if tenancy.booking_amount else 0.0

    # Last payment (any type, not voided) for this tenancy
    async with get_session() as session:
        last_payment = await session.scalar(
            select(Payment)
            .where(
                Payment.tenancy_id == tenancy_id,
                Payment.is_void == False,
            )
            .order_by(Payment.payment_date.desc())
            .limit(1)
        )

    return {
        "tenancy_id": tenancy.id,
        "tenant_id": tenant.id,
        "name": tenant.name,
        "phone": tenant.phone,
        "room_number": room.room_number,
        "building_code": _building_code(prop.name),
        "rent": rent,
        "rent_due": rent_due,
        "booking_amount": booking_amount,
        "dues": dues,
        "checkin_date": tenancy.checkin_date.isoformat() if tenancy.checkin_date else None,
        "security_deposit": float(tenancy.security_deposit) if tenancy.security_deposit is not None else 0.0,
        "maintenance_fee": float(tenancy.maintenance_fee) if tenancy.maintenance_fee is not None else 0.0,
        "last_payment_date": last_payment.payment_date.isoformat() if last_payment else None,
        "last_payment_amount": float(last_payment.amount) if last_payment else None,
        "period_month": period_month.strftime("%Y-%m"),
    }
