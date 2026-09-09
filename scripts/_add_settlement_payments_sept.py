"""One-off (Session AR, 2026-09-09): append two settlement rent receipts (UPI, Sep 2026) to exited tenancies.
  G19 Dhamodharan  tenancy 793  Rs.609
  512 Nirmala J.   tenancy 1278 Rs.1,600
Uses the canonical log_payment() writer. Suppresses the phantom Sept RentSchedule
row log_payment would auto-create for 793 (exited 31 Aug, no Sept due exists) --
copy that guard for any payment logged against an exited tenancy.

Run:  venv/Scripts/python scripts/_add_settlement_payments_sept.py [--write]
Already applied 2026-09-09 -> payments 22544, 22545. Re-running is blocked by
log_payment's unique_hash (same tenancy+date+amount+mode+period).
"""
import asyncio, os, sys
from dotenv import load_dotenv
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

from sqlalchemy import select
from src.database.db_manager import get_session, init_db_for_script
from src.database.models import RentSchedule, Room, Tenancy, Tenant
from src.services.payments import log_payment
from datetime import date

WRITE = "--write" in sys.argv
ROWS = [
    dict(tenancy_id=793,  amount=609,  label="G19 Dhamodharan"),
    dict(tenancy_id=1278, amount=1600, label="512 Nirmala Janakiraman"),
]
PERIOD = "2026-09"

async def main():
    await init_db_for_script(os.environ["DATABASE_URL"])
    async with get_session() as s:
        for r in ROWS:
            tc = await s.get(Tenancy, r["tenancy_id"])
            tn = await s.get(Tenant, tc.tenant_id)
            rm = await s.get(Room, tc.room_id)
            pre = await s.scalar(select(RentSchedule).where(
                RentSchedule.tenancy_id == tc.id,
                RentSchedule.period_month == date(2026, 9, 1)))
            had_rs = pre is not None
            print(f"\n{r['label']}: tenancy={tc.id} status={tc.status.value} "
                  f"room={rm.room_number} sep_rs_exists={had_rs}")
            if not WRITE:
                print(f"  DRY RUN -> would add Rs.{r['amount']} UPI rent period {PERIOD} "
                      f"date {date.today()}")
                continue
            res = await log_payment(
                tenancy_id=tc.id, amount=r["amount"], method="UPI", for_type="rent",
                period_month=PERIOD, recorded_by="7845952289", session=s,
                notes="Settlement receipt added manually (UPI reconciliation)",
                source="script", room_number=str(rm.room_number), entity_name=tn.name)
            print(f"  payment_id={res.payment_id}")
            if not had_rs:
                new_rs = await s.scalar(select(RentSchedule).where(
                    RentSchedule.tenancy_id == tc.id,
                    RentSchedule.period_month == date(2026, 9, 1)))
                if new_rs is not None:
                    await s.delete(new_rs)
                    print(f"  removed auto-created Sept RentSchedule "
                          f"(rent_due was Rs.{new_rs.rent_due}) — tenant exited, no Sept due")
        if WRITE:
            await s.commit()
            print("\nCOMMITTED")
asyncio.run(main())
