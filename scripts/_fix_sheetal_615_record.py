"""One-off: correct Room 615 P Sheetal Reddy (tenancy 1316) to what actually happened.

Staff account vs DB:
  check-in       1 Aug 2026          DB had 28 Aug (typed at booking, never corrected)
  27 Jul, UPI    Rs.14,500 advance   DB had it dated 2 Aug, typed `booking`
  2 Aug, CASH    rent                MISSING from DB entirely (added by --rent)

The Rs.14,500 row started life as a Rs.2,000 advance logged at booking and was
edited to Rs.14,500 on 4 Aug (audit_log 2105) — one row doing the job of the
deposit. There was no separate Rs.2,000, so tenancy.booking_amount is zeroed;
leaving it would net a phantom Rs.2,000 off the first-month rent_due.

    python scripts/_fix_sheetal_615_record.py                      # dry run
    python scripts/_fix_sheetal_615_record.py --write              # dates/types only
    python scripts/_fix_sheetal_615_record.py --write --rent 14000 # + the 2 Aug cash rent
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import date
from decimal import Decimal

from dotenv import load_dotenv
from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

from src.database.db_manager import get_session, init_engine  # noqa: E402
from src.database.models import Payment, PaymentFor, PaymentMode, Tenancy  # noqa: E402
from src.services.rent_schedule import recalc_checkin_month_rs  # noqa: E402

TENANCY_ID = 1316
ADVANCE_PMT = 21915
TRUE_CHECKIN = date(2026, 8, 1)
ADVANCE_DATE = date(2026, 7, 27)
RENT_DATE = date(2026, 8, 2)


async def audit(session, *, entity_type, entity_id, field, old, new, note):
    await session.execute(text("""
        INSERT INTO audit_log (created_at, changed_by, entity_type, entity_id, entity_name,
                               field, old_value, new_value, room_number, source, note, org_id)
        VALUES (now(), 'Kiran', :et, :eid, 'P Sheetal Reddy', :f, :ov, :nv, '615', 'script', :note, 1)
    """), {"et": entity_type, "eid": entity_id, "f": field,
           "ov": str(old) if old is not None else None,
           "nv": str(new) if new is not None else None, "note": note})


async def main(write: bool, rent: float | None) -> None:
    init_engine(os.getenv("DATABASE_URL"))
    async with get_session() as s:
        if write:
            await s.execute(text("SET LOCAL app.allow_historical_write = 'true'"))

        tenancy = await s.get(Tenancy, TENANCY_ID)
        pmt = await s.get(Payment, ADVANCE_PMT)

        print(f"checkin_date    {tenancy.checkin_date} -> {TRUE_CHECKIN}")
        print(f"booking_amount  {tenancy.booking_amount} -> 0  (the 2,000 was overwritten, never separate money)")
        print(f"pmt {ADVANCE_PMT} date  {pmt.payment_date} -> {ADVANCE_DATE}")
        print(f"pmt {ADVANCE_PMT} type  {pmt.for_type.value if pmt.for_type else None} -> deposit  (Rs.{pmt.amount}, upi)")
        if rent:
            print(f"NEW payment     Rs.{rent:,.0f} CASH rent for Aug 2026, dated {RENT_DATE}")
        else:
            print("NEW payment     (skipped — pass --rent <amount> to add the 2 Aug cash rent)")

        if not write:
            print("\nDRY RUN — nothing written. Re-run with --write")
            return

        old_checkin, old_booking = tenancy.checkin_date, tenancy.booking_amount
        tenancy.checkin_date = TRUE_CHECKIN
        tenancy.booking_amount = Decimal("0")
        await audit(s, entity_type="tenancy", entity_id=TENANCY_ID, field="checkin_date",
                    old=old_checkin, new=TRUE_CHECKIN,
                    note="Booking was typed with the wrong check-in date; she moved in 1 Aug (staff)")
        await audit(s, entity_type="tenancy", entity_id=TENANCY_ID, field="booking_amount",
                    old=old_booking, new=0,
                    note="No separate booking advance — the 2,000 row was edited into the 14,500 deposit")

        old_date, old_type = pmt.payment_date, pmt.for_type.value if pmt.for_type else None
        pmt.payment_date = ADVANCE_DATE
        pmt.for_type = PaymentFor.deposit
        pmt.payment_mode = PaymentMode.upi
        pmt.notes = "Advance/deposit collected 27 Jul (upi) — corrected from booking-advance row"
        await audit(s, entity_type="payment", entity_id=ADVANCE_PMT, field="payment_date",
                    old=old_date, new=ADVANCE_DATE, note="Advance was collected 27 Jul, not at booking")
        await audit(s, entity_type="payment", entity_id=ADVANCE_PMT, field="for_type",
                    old=old_type, new="deposit", note="Rs.14,500 is the security deposit, not a booking advance")

        if rent:
            new_pmt = Payment(
                tenancy_id=TENANCY_ID,
                amount=Decimal(str(rent)),
                payment_date=RENT_DATE,
                payment_mode=PaymentMode.cash,
                for_type=PaymentFor.rent,
                period_month=date(2026, 8, 1),
                notes="Aug rent collected 2 Aug (cash) — backfill, was never logged",
            )
            s.add(new_pmt)
            await s.flush()
            await audit(s, entity_type="payment", entity_id=new_pmt.id, field="payment.log",
                        old=None, new=str(rent),
                        note="Aug rent paid in cash on 2 Aug, missing from DB until now")

        await s.flush()
        await recalc_checkin_month_rs(s, tenancy)
        await s.commit()
        print("\nCOMMITTED")

    async with get_session() as s:
        print("\n-- resulting state")
        for r in (await s.execute(text("""
            SELECT p.id, p.amount, p.payment_date, p.payment_mode, p.for_type, p.period_month, p.notes
            FROM payments p WHERE p.tenancy_id = :t AND p.is_void IS NOT TRUE
            ORDER BY p.payment_date"""), {"t": TENANCY_ID})).mappings():
            print("  ", dict(r))
        for r in (await s.execute(text("""
            SELECT period_month, rent_due, adjustment, status FROM rent_schedule
            WHERE tenancy_id = :t ORDER BY period_month"""), {"t": TENANCY_ID})).mappings():
            print("  RS", dict(r))


if __name__ == "__main__":
    _rent = None
    if "--rent" in sys.argv:
        _rent = float(sys.argv[sys.argv.index("--rent") + 1])
    asyncio.run(main("--write" in sys.argv, _rent))
