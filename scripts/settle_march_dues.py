"""
scripts/settle_march_dues.py
=============================
One-off: insert settlement Payment rows for every tenancy with a
March 2026 rent_schedule balance > 0. Confirmed by Kiran 2026-04-21
that all March dues were paid (missing from DB because frozen-tab
import didn't capture every payment).

Usage:
    python scripts/settle_march_dues.py            # dry run
    python scripts/settle_march_dues.py --write    # commit
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
    Payment, RentSchedule, Tenancy, Tenant, Room,
    PaymentMode, PaymentFor, RentStatus,
)

MARCH = date(2026, 3, 1)
NOTE = "March settlement — confirmed paid by Kiran 2026-04-21"


async def main(write: bool):
    init_engine(os.environ["DATABASE_URL"])
    print(f"Mode: {'WRITE' if write else 'DRY RUN'}")

    async with get_session() as s:
        rs_rows = (await s.execute(
            select(RentSchedule).where(RentSchedule.period_month == MARCH)
        )).scalars().all()
        pay_rows = (await s.execute(
            select(Payment.tenancy_id, Payment.amount).where(
                Payment.period_month == MARCH,
                Payment.is_void == False,
                Payment.for_type == PaymentFor.rent,
            )
        )).all()
        paid = {}
        for tid, amt in pay_rows:
            paid[tid] = paid.get(tid, Decimal("0")) + Decimal(str(amt))

        settlements = []
        for rs in rs_rows:
            due = Decimal(str(rs.rent_due or 0))
            bal = due - paid.get(rs.tenancy_id, Decimal("0"))
            if bal > 0:
                settlements.append((rs.tenancy_id, bal, rs))

        total = sum(b for _, b, _ in settlements)
        print(f"Tenancies needing settlement: {len(settlements)}")
        print(f"Total amount to settle     : Rs.{total:,.0f}")

        if not write:
            for tid, bal, _ in settlements[:10]:
                t = await s.get(Tenancy, tid)
                tn = await s.get(Tenant, t.tenant_id)
                rm = await s.get(Room, t.room_id)
                print(f"  {rm.room_number:>6}  {tn.name:<30}  Rs.{bal:>10,.0f}")
            print(f"  ... ({len(settlements)-10} more)" if len(settlements) > 10 else "")
            return

        # WRITE path
        for tid, bal, rs in settlements:
            s.add(Payment(
                tenancy_id=tid,
                amount=bal,
                payment_date=MARCH,
                payment_mode=PaymentMode.cash,
                for_type=PaymentFor.rent,
                period_month=MARCH,
                notes=NOTE,
                is_void=False,
            ))
            rs.status = RentStatus.paid
        await s.commit()
        print(f"Inserted {len(settlements)} settlement payments, marked schedules PAID.")


if __name__ == "__main__":
    asyncio.run(main("--write" in sys.argv))
