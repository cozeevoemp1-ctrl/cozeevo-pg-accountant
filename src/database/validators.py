"""
Pre-write validation guards for PG Accountant.

Called before any new record is inserted via WhatsApp bot or API.
Each function returns (ok: bool, reason: str).

Guards:
  - check_no_active_tenancy  → blocks duplicate check-in for same phone
  - check_no_duplicate_payment → blocks double-logging same payment
  - check_tenancy_exists     → verifies tenancy_id is real and active before payment
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional, Tuple

from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import (
    Payment, PaymentFor, PaymentMode,
    Tenant, Tenancy, TenancyStatus,
)


async def check_no_active_tenancy(
    phone: str,
    session: AsyncSession,
) -> Tuple[bool, str]:
    """
    Before adding a new tenant check-in:
    Ensure the phone number has no existing ACTIVE tenancy.

    Returns:
      (True, "")                     → safe to proceed
      (False, "reason message")      → block and show reason to operator
    """
    result = await session.execute(
        select(Tenancy, Tenant)
        .join(Tenant, Tenant.id == Tenancy.tenant_id)
        .where(
            Tenant.phone == phone,
            Tenancy.status == TenancyStatus.active,
        )
    )
    rows = result.fetchall()

    if not rows:
        return True, ""

    tenancy, tenant = rows[0]
    # Fetch room number
    from src.database.models import Room
    room = await session.get(Room, tenancy.room_id)
    room_no = room.room_number if room else f"room_id={tenancy.room_id}"

    return False, (
        f"⚠️ *{tenant.name}* already has an active tenancy in Room {room_no} "
        f"(since {tenancy.checkin_date.strftime('%d %b %Y')}).\n"
        f"Checkout the current stay first before adding a new one."
    )


async def check_no_duplicate_payment(
    tenancy_id: int,
    amount: Decimal,
    payment_date: date,
    payment_mode: str,
    period_month: Optional[date],
    session: AsyncSession,
) -> Tuple[bool, str]:
    """
    Before logging a payment:
    Check if an identical payment already exists (same tenancy, amount, date, mode).

    Returns:
      (True, "")                     → safe to proceed
      (False, "reason message")      → likely a double-entry, show warning
    """
    conditions = [
        Payment.tenancy_id == tenancy_id,
        Payment.amount == amount,
        Payment.payment_date == payment_date,
        Payment.payment_mode == payment_mode,
        Payment.is_void == False,
        Payment.for_type == PaymentFor.rent,
    ]
    if period_month:
        conditions.append(Payment.period_month == period_month)

    existing = await session.scalar(select(func.count()).where(and_(*conditions)))

    if existing and existing > 0:
        period_str = period_month.strftime("%b %Y") if period_month else "unknown period"
        return False, (
            f"⚠️ *Duplicate payment detected.*\n"
            f"A {payment_mode} payment of Rs.{int(amount):,} "
            f"on {payment_date.strftime('%d %b %Y')} for {period_str} "
            f"is already recorded for this tenant.\n"
            f"Reply *confirm* to log it anyway, or ignore if it was a mistake."
        )

    return True, ""


async def check_tenancy_active(
    tenancy_id: int,
    session: AsyncSession,
) -> Tuple[bool, str]:
    """
    Before logging any payment or update:
    Verify that the tenancy exists and is currently active.

    Returns:
      (True, "")                     → safe to proceed
      (False, "reason message")      → tenancy not found or already exited
    """
    tenancy = await session.get(Tenancy, tenancy_id)

    if not tenancy:
        return False, f"Tenancy ID {tenancy_id} not found."

    if tenancy.status == TenancyStatus.exited:
        tenant = await session.get(Tenant, tenancy.tenant_id)
        name = tenant.name if tenant else f"tenant_id={tenancy.tenant_id}"
        return False, (
            f"⚠️ *{name}* has already checked out "
            f"({tenancy.checkout_date.strftime('%d %b %Y') if tenancy.checkout_date else 'date unknown'}).\n"
            f"Cannot log payment for an exited tenancy."
        )

    if tenancy.status in (TenancyStatus.cancelled, TenancyStatus.no_show):
        return False, f"Tenancy ID {tenancy_id} is {tenancy.status.value} — cannot accept payments."

    return True, ""
