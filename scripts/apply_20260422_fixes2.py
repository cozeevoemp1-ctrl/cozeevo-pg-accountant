"""Batch 2 of 2026-04-22 corrections.

1. G13 Ankit, G13 Shubham Varma, G14 Anudeep, G14 Yogesh — Rs.100 discount
   → April RentSchedule.adjustment = -100 each

2. G08 Praveen — rent change 11,000 → 10,000
   → agreed_rent 11,000 → 10,000 + April rent_due 11,000 → 10,000
   → RentRevision 11,000 → 10,000 effective 2026-04-01

3. 618 Priyanshi — missed booking payment from source
   → add Payment: booking 2,000 cash, date=2026-04-11

4. 602 Mahika — April 15,000, May 15,500
   → April RS rent_due 15,500 → 15,000 (May onward stays 15,500 agreed)
"""
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
from src.database.models import (
    RentSchedule, Tenancy, Payment, PaymentFor, PaymentMode, RentRevision,
)


APRIL = date(2026, 4, 1)


async def main():
    init_engine(os.environ["DATABASE_URL"])
    async with get_session() as s:
        # 1. Rs.100 discount for 4 tenancies
        for tid, name in [(782, "Ankit Kumar"), (780, "Shubham Varma"),
                          (785, "Anudeep Bhist"), (783, "Yogesh Bhist")]:
            rs = (await s.execute(select(RentSchedule).where(
                RentSchedule.tenancy_id == tid, RentSchedule.period_month == APRIL
            ))).scalar_one_or_none()
            if rs:
                rs.adjustment = Decimal("-100")
                rs.notes = (rs.notes + " | " if rs.notes else "") + "Rs.100 discount (per Kiran 2026-04-22)"
                print(f"[discount] {name}: Apr adjustment = -100")

        # 2. Praveen G08 — rent 11,000 → 10,000
        t = await s.get(Tenancy, 771)
        if t:
            old = t.agreed_rent
            t.agreed_rent = Decimal("10000")
            print(f"[Praveen] agreed_rent: {old} → 10,000")
            rs = (await s.execute(select(RentSchedule).where(
                RentSchedule.tenancy_id == 771, RentSchedule.period_month == APRIL
            ))).scalar_one_or_none()
            if rs:
                rs.rent_due = Decimal("10000")
                rs.notes = "Rent revised to 10,000 effective April per Kiran 2026-04-22"
            s.add(RentRevision(
                tenancy_id=771,
                old_rent=old,
                new_rent=Decimal("10000"),
                effective_date=APRIL,
                changed_by="+917845952289",
                reason="Kiran 2026-04-22 — agreed 10,000",
            ))

        # 3. Priyanshi 618 — missed booking 2,000 from source
        existing = (await s.execute(select(Payment).where(
            Payment.tenancy_id == 853, Payment.for_type == PaymentFor.booking,
            Payment.is_void == False,
        ))).scalar_one_or_none()
        if not existing:
            s.add(Payment(
                tenancy_id=853,
                amount=Decimal("2000"),
                payment_mode=PaymentMode.cash,
                for_type=PaymentFor.booking,
                payment_date=date(2026, 4, 11),
                period_month=None,
                notes="Booking advance — imported from source sheet 2026-04-22",
            ))
            print("[Priyanshi] added booking Rs.2,000")

        # 4. Mahika 602 — April rent 15,500 → 15,000
        rs = (await s.execute(select(RentSchedule).where(
            RentSchedule.tenancy_id == 554, RentSchedule.period_month == APRIL
        ))).scalar_one_or_none()
        if rs:
            rs.rent_due = Decimal("15000")
            rs.notes = "April special 15,000; May onward 15,500 agreed"
            print(f"[Mahika] Apr rent_due: 15,500 → 15,000")

        await s.commit()
        print("\nCommitted.")


asyncio.run(main())
