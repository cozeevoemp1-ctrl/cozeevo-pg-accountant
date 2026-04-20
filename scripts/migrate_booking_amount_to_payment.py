"""
scripts/migrate_booking_amount_to_payment.py
One-time migration — for every Tenancy with booking_amount > 0 that has NO
Payment(for_type=booking) row, create the missing advance Payment.

Why: Excel-imported tenants carry `tenancy.booking_amount` in DB but the
actual money received was never logged as a Payment row. Bot's balance
calculation sums Payments, not tenancy.booking_amount → advance not
subtracted from first-month dues.

Safety:
- Dry-run by default. Pass --write to commit.
- Idempotent: skips tenancies that already have ANY Payment(for_type=booking).
- Creates AuditLog per insert for traceability.
- Period_month = tenancy.checkin_date.replace(day=1).
- Payment mode = cash (unknown from Excel; receptionist can correct later).

Usage:
    python scripts/migrate_booking_amount_to_payment.py          # dry-run
    python scripts/migrate_booking_amount_to_payment.py --write  # commit
"""
from __future__ import annotations

import asyncio
import os
import sys
from decimal import Decimal

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import select, func

from src.database.db_manager import init_engine, get_session
from src.database.models import (
    Tenancy, Payment, PaymentFor, PaymentMode, AuditLog,
)


async def migrate(write: bool = False) -> dict:
    init_engine(os.getenv("DATABASE_URL", ""))
    stats = {"candidates": 0, "already_logged": 0, "created": 0, "skipped_no_checkin": 0}

    async with get_session() as session:
        # All tenancies with a positive booking_amount.
        candidates = (await session.execute(
            select(Tenancy).where(Tenancy.booking_amount > 0)
        )).scalars().all()

        stats["candidates"] = len(candidates)

        for tn in candidates:
            # Skip if already has any booking Payment (idempotent).
            existing = (await session.execute(
                select(func.count()).select_from(Payment).where(
                    Payment.tenancy_id == tn.id,
                    Payment.for_type == PaymentFor.booking,
                    Payment.is_void == False,
                )
            )).scalar() or 0
            if existing > 0:
                stats["already_logged"] += 1
                continue

            if not tn.checkin_date:
                stats["skipped_no_checkin"] += 1
                continue

            period = tn.checkin_date.replace(day=1)
            amt = Decimal(str(tn.booking_amount or 0))

            print(f"  tenancy_id={tn.id} checkin={tn.checkin_date} "
                  f"booking_amount=Rs.{int(amt):,} → would create Payment")

            if write:
                new_pay = Payment(
                    tenancy_id=tn.id,
                    amount=amt,
                    payment_date=tn.checkin_date,
                    payment_mode=PaymentMode.cash,  # unknown; receptionist can correct
                    for_type=PaymentFor.booking,
                    period_month=period,
                    notes="Backfilled from tenancy.booking_amount (Excel import)",
                )
                session.add(new_pay)
                await session.flush()
                session.add(AuditLog(
                    changed_by="migration_script",
                    entity_type="payment",
                    entity_id=new_pay.id,
                    field="backfill_booking",
                    old_value=None,
                    new_value=str(int(amt)),
                    source="migration",
                    note=f"One-time backfill — tenancy {tn.id} had "
                         f"booking_amount={int(amt)} but no Payment row",
                ))
                stats["created"] += 1

        if write:
            await session.commit()
            print(f"\nCommitted {stats['created']} Payment rows.")
        else:
            print(f"\nDry-run. {stats['candidates']} candidates, "
                  f"{stats['already_logged']} already have Payment, "
                  f"{stats['candidates'] - stats['already_logged'] - stats['skipped_no_checkin']} "
                  f"would be created.")

    return stats


if __name__ == "__main__":
    write_flag = "--write" in sys.argv
    print("=" * 60)
    print("Backfill tenancy.booking_amount → Payment(for_type=booking)")
    print(f"Mode: {'WRITE' if write_flag else 'DRY-RUN'}")
    print("=" * 60)
    stats = asyncio.run(migrate(write=write_flag))
    print("\nSummary:", stats)
