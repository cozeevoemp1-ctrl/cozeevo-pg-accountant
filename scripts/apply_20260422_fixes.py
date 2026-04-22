"""One-off: apply Kiran's 2026-04-22 corrections.

1. Absconded exits (Sai Prashanth 621, Vijay Kumar 622, Aniket 781)
   → status=exited, checkout=2026-03-31, notes="absconded — deposit forfeited"
   → delete April RentSchedule (not present in April)

2. Room 419 Aruf (700) + Akshit (699):
   → security_deposit 13,500 → 11,500
   → April RentSchedule.rent_due 13,500 → 10,000 (special April rate; May agreed=13,500)
   → notes updated

Run:  venv/Scripts/python scripts/apply_20260422_fixes.py --write
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

from sqlalchemy import delete, select
from src.database.db_manager import init_engine, get_session
from src.database.models import RentSchedule, Tenancy, TenancyStatus


APRIL = date(2026, 4, 1)
ABSCONDED = [
    (621, "Sai Prashanth"),
    (622, "Vijay Kumar"),
    (781, "Aniket Machhindra Jagtap"),
]
RATE_OVERRIDE_419 = [(700, "Aruf Khan"), (699, "Akshit")]


async def main(write: bool):
    init_engine(os.environ["DATABASE_URL"])
    print(f"{'=== WRITING ===' if write else '=== DRY RUN ==='}\n")

    async with get_session() as s:
        # 1. Absconded exits
        for tid, name in ABSCONDED:
            t = await s.get(Tenancy, tid)
            if not t:
                print(f"[skip] {name} (id={tid}) not found")
                continue
            print(f"[absconded] {name} (id={tid})")
            print(f"  status: {t.status.value} → exited")
            print(f"  checkout_date: {t.checkout_date} → 2026-03-31")
            prev = (t.notes or "").strip()
            new_notes = (prev + " | " if prev else "") + "absconded in April — deposit forfeited, no refund"
            print(f"  notes: + 'absconded — deposit forfeited'")
            if write:
                t.status = TenancyStatus.exited
                t.checkout_date = date(2026, 3, 31)
                t.notes = new_notes[:500]
            # drop April RS
            apr_rs = (await s.execute(
                select(RentSchedule).where(
                    RentSchedule.tenancy_id == tid,
                    RentSchedule.period_month == APRIL,
                )
            )).scalar_one_or_none()
            if apr_rs:
                print(f"  April RentSchedule rent_due={apr_rs.rent_due} → DELETE")
                if write:
                    await s.delete(apr_rs)
            print()

        # 2. Room 419 rate override
        for tid, name in RATE_OVERRIDE_419:
            t = await s.get(Tenancy, tid)
            if not t:
                print(f"[skip] {name} (id={tid}) not found")
                continue
            print(f"[419 override] {name} (id={tid})")
            print(f"  security_deposit: {t.security_deposit} → 11500")
            if write:
                t.security_deposit = Decimal("11500")
            apr_rs = (await s.execute(
                select(RentSchedule).where(
                    RentSchedule.tenancy_id == tid,
                    RentSchedule.period_month == APRIL,
                )
            )).scalar_one_or_none()
            if apr_rs:
                print(f"  April rent_due: {apr_rs.rent_due} → 10000 (special April rate)")
                if write:
                    apr_rs.rent_due = Decimal("10000")
                    extra = "April special rate 10,000; May onward 13,500 agreed"
                    apr_rs.notes = (apr_rs.notes + " | " + extra) if apr_rs.notes else extra
            else:
                print(f"  (no April RS — unexpected)")
            print()

        if write:
            await s.commit()
            print("Committed.")
        else:
            print("Dry run — no changes.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    asyncio.run(main(args.write))
