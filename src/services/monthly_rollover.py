"""
src/services/monthly_rollover.py
Monthly rollover — DB-side generator of RentSchedule rows for the next month.

Runs on the 2nd-to-last calendar day of every month (handled by scheduler).

Rules (from Kiran):
- Only ACTIVE + NO_SHOW tenancies carry forward. Exited/cancelled are excluded.
- First-month check-in (checkin_date falls inside the target month):
    * Prorated rent: floor(agreed_rent * (days_in_month - checkin.day + 1) / days_in_month)
    * Rent Due in sheet = prorated rent + deposit  (deposit-included rule)
    * In DB: rent_due = prorated rent only; maintenance_due = 0.
      Deposit is a separate Payment.for_type='deposit' — not a RentSchedule field.
- No-shows: insert RentSchedule with status=na and rent_due=0 until they check in.
- Subsequent months: rent_due = agreed_rent.
- Idempotent: existing (tenancy_id, period_month) rows are left untouched.
"""
from __future__ import annotations

import calendar
import math
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from loguru import logger

from src.database.db_manager import get_session
from src.database.models import (
    Tenancy, TenancyStatus, RentSchedule, RentStatus,
)


def _days_in_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


async def generate_rent_schedule_for_month(year: int, month: int) -> dict:
    """
    Upsert RentSchedule rows for every active/noshow tenancy for the given
    (year, month). Idempotent — skips rows that already exist.

    Returns a summary dict: {created, skipped_existing, skipped_exited, noshow, first_month}.
    """
    period = date(year, month, 1)
    days = _days_in_month(year, month)
    m_end = date(year, month, days)

    stats = {"created": 0, "skipped_existing": 0, "skipped_exited": 0,
             "noshow": 0, "first_month": 0}

    async with get_session() as session:
        # Pull only carryable tenancies (active + no_show)
        result = await session.execute(
            select(Tenancy).where(
                Tenancy.status.in_([TenancyStatus.active, TenancyStatus.no_show])
            )
        )
        tenancies = result.scalars().all()

        for tn in tenancies:
            # No-show whose checkin is AFTER target month-end: keep as noshow but
            # DO carry — so they show up every month until they actually check in.
            # No-show whose checkin falls INSIDE target month → still noshow this
            # month but rent_due=0 until CHECKIN event upgrades the row.
            if tn.status == TenancyStatus.exited or tn.status == TenancyStatus.cancelled:
                stats["skipped_exited"] += 1
                continue

            # Skip if tenancy ended before this period starts
            if tn.expected_checkout and tn.expected_checkout < period:
                stats["skipped_exited"] += 1
                continue

            # Skip if checkin is AFTER the target month end (future tenancies —
            # they'll get their own first-month row later). But NO-SHOW is kept:
            # user rule = noshows must appear every month until they check in.
            if tn.checkin_date and tn.checkin_date > m_end and tn.status != TenancyStatus.no_show:
                continue

            # Idempotency: skip if row already exists
            existing = (await session.execute(
                select(RentSchedule).where(
                    RentSchedule.tenancy_id == tn.id,
                    RentSchedule.period_month == period,
                )
            )).scalar()
            if existing:
                stats["skipped_existing"] += 1
                continue

            # Decide due_amount
            agreed = Decimal(str(tn.agreed_rent or 0))
            rs_status = RentStatus.pending
            rent_due = agreed

            if tn.status == TenancyStatus.no_show:
                rs_status = RentStatus.na
                rent_due = Decimal("0")
                stats["noshow"] += 1
            elif tn.checkin_date and period <= tn.checkin_date <= m_end:
                # First month — prorate
                prorated = math.floor(
                    float(agreed) * (days - tn.checkin_date.day + 1) / days
                )
                rent_due = Decimal(str(prorated))
                stats["first_month"] += 1

            session.add(RentSchedule(
                tenancy_id=tn.id,
                period_month=period,
                rent_due=rent_due,
                maintenance_due=Decimal("0"),
                status=rs_status,
                due_date=period,
            ))
            stats["created"] += 1

        await session.commit()

    logger.info(
        "[monthly_rollover] period=%s created=%d skipped_existing=%d "
        "skipped_exited=%d noshow=%d first_month=%d",
        period.isoformat(), stats["created"], stats["skipped_existing"],
        stats["skipped_exited"], stats["noshow"], stats["first_month"]
    )
    return stats
