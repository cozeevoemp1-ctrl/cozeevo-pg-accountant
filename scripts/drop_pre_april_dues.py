"""Drop all pre-April 2026 dues so bot + sheet only track April onwards.

Kiran's rule: April is the live-tracking boundary. Dec 2025 – Mar 2026
balances should be considered settled (they're shown in frozen monthly
tabs loaded 1:1 from source). Any lingering RentSchedule with
balance > 0 makes _calc_outstanding_dues() surface old Prev Due that
the sheet doesn't show — causing DB-vs-sheet drift (e.g. Krishnan 101
showed Rs.47,000 Due in bot but PAID on sheet).

Action per pre-April RentSchedule:
  - If rent_due > sum(payments): set status=paid, adjustment so
    balance becomes zero. We don't insert phantom payments (cash
    flow is preserved — we just stop claiming it's owed).
  - Status rows already `paid`/`na` are left alone.

Run:  venv/Scripts/python scripts/drop_pre_april_dues.py --write
"""
import argparse
import asyncio
import os
import sys
from datetime import date
from decimal import Decimal

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import select
from src.database.db_manager import init_engine, get_session
from src.database.models import Payment, PaymentFor, RentSchedule, RentStatus


APRIL = date(2026, 4, 1)


async def main(write: bool):
    init_engine(os.environ["DATABASE_URL"])
    async with get_session() as s:
        rs_rows = (await s.execute(
            select(RentSchedule).where(RentSchedule.period_month < APRIL)
        )).scalars().all()
        print(f"Pre-April RentSchedule rows: {len(rs_rows)}")

        cleared = already_clean = 0
        for rs in rs_rows:
            pays = (await s.execute(
                select(Payment).where(
                    Payment.tenancy_id == rs.tenancy_id,
                    Payment.period_month == rs.period_month,
                    Payment.is_void == False,
                    Payment.for_type == PaymentFor.rent,
                )
            )).scalars().all()
            paid = sum(float(p.amount) for p in pays)
            due = float(rs.rent_due or 0) + float(rs.adjustment or 0)
            bal = due - paid
            if bal <= 0:
                already_clean += 1
                continue

            # Force balance to 0 via adjustment so we don't rewrite rent_due
            # (keeps the historical Rent Due visible on frozen sheet tabs).
            new_adj = Decimal(str(float(rs.adjustment or 0) - bal))
            if write:
                rs.adjustment = new_adj
                rs.status = RentStatus.paid
                note_tail = f"[pre-April drop 2026-04-22: adjusted -Rs.{int(bal):,}]"
                rs.notes = ((rs.notes or "") + " " + note_tail).strip()[:500]
            cleared += 1

        if write:
            await s.commit()
        print(f"\nCleared: {cleared}  Already clean: {already_clean}")
        if not write:
            print("[DRY RUN]")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    asyncio.run(main(ap.parse_args().write))
