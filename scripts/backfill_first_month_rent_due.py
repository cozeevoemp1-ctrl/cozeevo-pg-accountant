"""Backfill first-month RentSchedule.rent_due with rent + deposit.

Business rule: the check-in month's rent_due bundles the security
deposit (see memory/feedback_deposit_dues_logic.md and
src/services/rent_schedule.py). Any existing RentSchedule row where
period_month equals the tenancy's check-in month and rent_due is
missing the deposit portion needs to be corrected.

Also recomputes the row's status (paid / partial / unpaid) based on the
new rent_due vs the sum of non-void payments for that period.

Usage:
    python scripts/backfill_first_month_rent_due.py            # dry run
    python scripts/backfill_first_month_rent_due.py --apply    # write
"""
from __future__ import annotations

import argparse
import asyncio
import os
from decimal import Decimal

from sqlalchemy import select, func

from src.database.db_manager import init_db, get_session
from src.database.models import (
    RentSchedule, RentStatus, Tenancy, TenancyStatus, Payment,
)


async def _recompute_status(session, rs: RentSchedule, rent_due: Decimal) -> RentStatus:
    """Compute paid/partial/unpaid based on non-void payments for this period."""
    paid = (await session.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.tenancy_id == rs.tenancy_id,
            Payment.period_month == rs.period_month,
            Payment.is_void == False,
        )
    )) or Decimal("0")
    paid = Decimal(str(paid))
    if paid >= rent_due and rent_due > 0:
        return RentStatus.paid
    if paid > 0:
        return RentStatus.partial
    return RentStatus.pending


async def run(apply: bool) -> None:
    await init_db(os.environ["DATABASE_URL"])
    fixed = skipped = 0
    rows_out = []

    async with get_session() as s:
        tenancies = (await s.execute(
            select(Tenancy).where(Tenancy.checkin_date.isnot(None))
        )).scalars().all()

        for t in tenancies:
            checkin_month = t.checkin_date.replace(day=1)
            rs = await s.scalar(
                select(RentSchedule).where(
                    RentSchedule.tenancy_id == t.id,
                    RentSchedule.period_month == checkin_month,
                )
            )
            if not rs:
                continue
            rent = Decimal(str(t.agreed_rent or 0))
            deposit = Decimal(str(t.security_deposit or 0))
            expected = rent + deposit
            current = Decimal(str(rs.rent_due or 0))
            if current == expected or deposit == 0:
                skipped += 1
                continue
            new_status = await _recompute_status(s, rs, expected)
            rows_out.append((
                t.id, rs.id, t.tenant_id, str(checkin_month),
                str(current), str(expected),
                rs.status.value if rs.status else None,
                new_status.value,
            ))
            if apply:
                rs.rent_due = expected
                rs.status = new_status
            fixed += 1

        if apply:
            await s.commit()

    print(f"{'APPLIED' if apply else 'DRY RUN'}: fixed={fixed} unchanged={skipped}")
    print("tenancy_id | rs_id | tenant_id | period | old_rent_due → new_rent_due | old_status → new_status")
    for row in rows_out:
        print("  " + " | ".join(str(x) for x in row))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    args = p.parse_args()
    asyncio.run(run(args.apply))
