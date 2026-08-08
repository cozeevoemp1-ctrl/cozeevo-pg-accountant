"""
GET /api/v2/app/checkouts?month=YYYY-MM  — tenants who checked out in a given month
"""
from __future__ import annotations

from datetime import date
import calendar

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, and_

from src.api.v2.auth import AppUser, get_current_user
from src.database.db_manager import get_session
from src.database.models import Tenancy, TenancyStatus, Tenant, Room, CheckoutRecord

router = APIRouter()


@router.get("/checkouts")
async def get_checkouts(
    month: str | None = Query(None, description="YYYY-MM, defaults to current month"),
    user: AppUser = Depends(get_current_user),
):
    """All tenants (monthly + day-wise) who checked out in the given month."""
    today = date.today()
    if month:
        try:
            year, m = int(month[:4]), int(month[5:7])
        except (ValueError, IndexError):
            year, m = today.year, today.month
    else:
        year, m = today.year, today.month

    month_start = date(year, m, 1)
    month_end   = date(year, m, calendar.monthrange(year, m)[1])

    async with get_session() as session:
        rows = (await session.execute(
            select(Tenancy, Tenant, Room)
            .join(Tenant, Tenancy.tenant_id == Tenant.id)
            .join(Room, Tenancy.room_id == Room.id)
            .where(
                Tenancy.status == TenancyStatus.exited,
                Tenancy.checkout_date >= month_start,
                Tenancy.checkout_date <= month_end,
                Room.is_staff_room == False,
                Room.room_number != "000",
            )
            .order_by(Tenancy.checkout_date.desc(), Room.room_number)
        )).all()

        # Fetch checkout records for refund amounts
        tenancy_ids = [t.id for t, _, _ in rows]
        refund_map: dict[int, float] = {}
        if tenancy_ids:
            cr_rows = (await session.execute(
                select(CheckoutRecord.tenancy_id, CheckoutRecord.deposit_refunded_amount)
                .where(CheckoutRecord.tenancy_id.in_(tenancy_ids))
            )).all()
            refund_map = {r.tenancy_id: float(r.deposit_refunded_amount or 0) for r in cr_rows}

        return [
            {
                "tenancy_id":       tenancy.id,
                "name":             tenant.name,
                "phone":            tenant.phone,
                "room_number":      room.room_number,
                "checkout_date":    tenancy.checkout_date.isoformat(),
                "stay_type":        tenancy.stay_type.value,
                "security_deposit": float(tenancy.security_deposit or 0),
                "refund_amount":    refund_map.get(tenancy.id, 0.0),
                "agreed_rent":      float(tenancy.agreed_rent or 0),
            }
            for tenancy, tenant, room in rows
        ]
