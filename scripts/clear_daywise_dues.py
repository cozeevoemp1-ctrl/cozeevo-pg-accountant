"""
scripts/clear_daywise_dues.py
==============================
Zero out outstanding balances for all EXITED day-wise tenancies by inserting
a clearing cash payment. Assumes payment was collected but not recorded.

DOES NOT touch:
  - Active tenancies (status=active AND checkout >= today)
  - Future bookings (no checkout yet and not exited)
  - Any tenancy where balance is already 0 or negative

Usage:
    python scripts/clear_daywise_dues.py           # dry run — shows what would be cleared
    python scripts/clear_daywise_dues.py --write   # insert clearing payments in DB
    python scripts/clear_daywise_dues.py --write --sync  # DB clear + re-sync sheet
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8")
from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, selectinload

from src.database.models import (
    Tenancy, StayType, TenancyStatus, PaymentMode, PaymentFor, Payment, Room
)

DATABASE_URL = os.environ["DATABASE_URL"]
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)


async def main(args) -> None:
    engine = create_async_engine(DATABASE_URL, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    today = date.today()

    async with Session() as session:
        rows = (await session.execute(
            select(Tenancy)
            .options(
                selectinload(Tenancy.tenant),
                selectinload(Tenancy.room),
                selectinload(Tenancy.payments),
            )
            .where(Tenancy.stay_type == StayType.daily)
        )).scalars().all()

        to_clear = []

        for t in rows:
            # "Active now" = status active AND checkout not yet past
            is_still_active = (
                t.status == TenancyStatus.active
                and not (t.checkout_date and t.checkout_date < today)
            )
            if is_still_active:
                continue  # leave active/future bookings untouched

            # Compute outstanding balance
            if t.checkout_date and t.checkin_date:
                num_days = (t.checkout_date - t.checkin_date).days + 1
            else:
                num_days = 0

            daily_rate  = float(t.agreed_rent or 0)
            maintenance = float(t.maintenance_fee or 0)
            rent_due    = round(daily_rate * num_days + maintenance, 2)

            non_void   = [p for p in t.payments if not p.is_void]
            total_paid = round(sum(float(p.amount or 0) for p in non_void), 2)
            balance    = round(rent_due - total_paid, 2)

            if balance <= 0:
                continue  # already settled

            tenant_name = t.tenant.name if t.tenant else f"tenancy-{t.id}"
            room_no     = t.room.room_number if t.room else "?"
            to_clear.append((t, balance, tenant_name, room_no))

        print(f"Day-wise tenancies with outstanding balance (exited): {len(to_clear)}")
        total_clearing = sum(b for _, b, _, _ in to_clear)
        for t, balance, name, room in to_clear:
            checkin  = t.checkin_date.strftime("%d/%m/%Y")  if t.checkin_date  else "?"
            checkout = t.checkout_date.strftime("%d/%m/%Y") if t.checkout_date else "?"
            print(f"  [{room}] {name} | {checkin}→{checkout} | balance Rs.{balance:,.0f}")
        print(f"Total to clear: Rs.{total_clearing:,.0f}")

        if not args.write:
            print("\n[DRY RUN] Pass --write to insert clearing payments.")
            return

        # Insert one clearing payment per tenancy
        for t, balance, name, room in to_clear:
            clearing = Payment(
                tenancy_id   = t.id,
                amount       = balance,
                payment_date = today,
                payment_mode = PaymentMode.cash,
                for_type     = PaymentFor.rent,
                notes        = "Clearance — payment collected but not recorded in system",
                is_void      = False,
                org_id       = 1,
            )
            session.add(clearing)

        await session.commit()
        print(f"\nInserted {len(to_clear)} clearing payments. Total cleared: Rs.{total_clearing:,.0f}")

    await engine.dispose()

    if args.sync:
        print("\nRe-syncing DAY WISE sheet...")
        import subprocess
        result = subprocess.run(
            [sys.executable, str(Path(__file__).parent / "sync_daywise_from_db.py"), "--write"],
            capture_output=False,
        )
        if result.returncode != 0:
            print("[error] Sheet sync failed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="Insert clearing payments in DB")
    parser.add_argument("--sync",  action="store_true", help="Re-sync sheet after clearing")
    asyncio.run(main(parser.parse_args()))
