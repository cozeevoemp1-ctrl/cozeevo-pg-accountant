"""One-off: Room 621 Harshit Srivastava (tenancy 1301) — record the check-in that never happened in the app.

What actually happened (Kiran, 5 Sep 2026):
  5 Jul 2026   physically checked in to Room 621, has lived there since
  5 Jul  CASH  Rs.20,000  rent          MISSING from DB
  5 Jul  UPI   Rs.12,500  deposit       MISSING from DB
  Aug    CASH  Rs.14,000  Aug rent      MISSING from DB
  Sep    CASH  Rs.14,000  Sep rent      MISSING from DB

Why the DB was wrong: the booking was raised on 17 Jul (back-dated to 5 Jul) with a
Rs.2,500 advance, but the onboarding link was never opened, so the tenancy stayed
`no_show` and was never activated. scripts/_cleanup_2026_08_06.py step F1 then
cancelled onboarding session 279 as a "32-day stale hold" (audit_log 2274) without
touching the tenancy — leaving him invisible everywhere except the "Awaiting
check-in" tile, and holding a phantom bed in a double room.

Only Rs.2,500 (payment 21849, booking, 5 Jul) was ever recorded. Kiran recalls this
as "2k in June"; the DB row is the authority for the amount and is left untouched.

Aug/Sep payment DATES are not known to the day — both default to the 5th and can be
corrected in the PWA payment editor. Everything written here lands in audit_log so it
shows in the activity feed and the tenant history panel.

    py -3 scripts/_fix_harshit_621_checkin.py            # dry run
    py -3 scripts/_fix_harshit_621_checkin.py --write
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

from dotenv import load_dotenv
from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

from src.database.db_manager import get_session, init_engine  # noqa: E402
from src.database.models import Tenancy  # noqa: E402
from src.services.rent_schedule import first_month_rent_due  # noqa: E402

TENANCY_ID = 1301
SESSION_ID = 279
ROOM = "621"
NAME = "Harshit Srivastava"

# (payment_date, amount, mode, for_type, period_month, note)
PAYMENTS = [
    (date(2026, 7, 5), Decimal("20000"), "cash", "rent",    date(2026, 7, 1),
     "Jul 2026 rent - back-entered 5 Sep (paid at check-in, never logged)"),
    (date(2026, 7, 5), Decimal("12500"), "upi",  "deposit", None,
     "Security deposit - back-entered 5 Sep (paid at check-in, never logged)"),
    (date(2026, 8, 5), Decimal("14000"), "cash", "rent",    date(2026, 8, 1),
     "Aug 2026 rent - back-entered 5 Sep (date approximate)"),
    (date(2026, 9, 5), Decimal("14000"), "cash", "rent",    date(2026, 9, 1),
     "Sep 2026 rent - back-entered 5 Sep"),
]

MONTHS = [date(2026, 7, 1), date(2026, 8, 1), date(2026, 9, 1)]


async def audit(s, *, entity_type, entity_id, field, old, new, note):
    await s.execute(text(
        "INSERT INTO audit_log (created_at, changed_by, entity_type, entity_id, entity_name, "
        "                       field, old_value, new_value, room_number, source, note, org_id) "
        "VALUES (now(), 'Kiran', :et, :eid, :nm, :f, :ov, :nv, :rm, 'script', :note, 1)"
    ), {"et": entity_type, "eid": entity_id, "nm": NAME, "f": field,
        "ov": str(old) if old is not None else None,
        "nv": str(new) if new is not None else None,
        "rm": ROOM, "note": note})


async def main(write: bool) -> None:
    init_engine(os.getenv("DATABASE_URL"))
    async with get_session() as s:
        if write:
            await s.execute(text("SET LOCAL app.allow_historical_write = 'true'"))

        tenancy = await s.get(Tenancy, TENANCY_ID)
        if tenancy is None:
            sys.exit("tenancy %s not found" % TENANCY_ID)

        print("tenancy %s  %s  Room %s" % (TENANCY_ID, NAME, ROOM))
        print("  status         %s -> active" % tenancy.status.value)
        print("  checkin_date   %s (unchanged)" % tenancy.checkin_date)
        print("  agreed_rent    Rs.%s   deposit Rs.%s   booking Rs.%s"
              % (tenancy.agreed_rent, tenancy.security_deposit, tenancy.booking_amount))

        # rent schedule
        print("\nrent schedule")
        rs_plan = []
        for period in MONTHS:
            due = first_month_rent_due(tenancy, period)
            row = (await s.execute(text(
                "SELECT id, rent_due, status FROM rent_schedule "
                "WHERE tenancy_id=:t AND period_month=:p"),
                {"t": TENANCY_ID, "p": period})).fetchone()
            rs_plan.append((period, due, row))
            label = period.strftime("%b %Y")
            if row:
                print("  %s  Rs.%s (%s) -> Rs.%s (paid)" % (label, row.rent_due, row.status, due))
            else:
                print("  %s  MISSING -> create Rs.%s (paid)" % (label, due))

        # payments
        print("\npayments to add")
        total_new = Decimal("0")
        to_add = []
        for pdate, amt, mode, ftype, period, note in PAYMENTS:
            dupe = (await s.execute(text(
                "SELECT id FROM payments WHERE tenancy_id=:t AND amount=:a AND payment_date=:d "
                "AND for_type=:f AND is_void=false"),
                {"t": TENANCY_ID, "a": amt, "d": pdate, "f": ftype})).fetchone()
            if dupe:
                print("  SKIP  %s  Rs.%9s %-4s %-8s already present (payment %s)"
                      % (pdate, int(amt), mode, ftype, dupe.id))
                continue
            print("  ADD   %s  Rs.%9s %-4s %s" % (pdate, int(amt), mode, ftype))
            to_add.append((pdate, amt, mode, ftype, period, note))
            total_new += amt

        charged = sum(due for _, due, _ in rs_plan)
        existing_paid = Decimal((await s.execute(text(
            "SELECT coalesce(sum(amount),0) FROM payments WHERE tenancy_id=:t AND is_void=false "
            "AND for_type<>'booking'"), {"t": TENANCY_ID})).scalar())
        paid = existing_paid + total_new
        print("\nledger  charged Rs.%s  (booking Rs.%s already netted into Jul)"
              % (charged, tenancy.booking_amount))
        print("        paid    Rs.%s" % paid)
        print("        balance Rs.%s   (negative = credit to tenant)" % (charged - paid))

        print("\nonboarding session %s: cancelled -> pending_tenant, fresh token + 7-day expiry"
              % SESSION_ID)

        if not write:
            print("\nDRY RUN - nothing written. Re-run with --write")
            return

        # 1. activate tenancy
        old_status = tenancy.status.value
        await s.execute(text("UPDATE tenancies SET status='active', updated_at=now() WHERE id=:i"),
                        {"i": TENANCY_ID})
        await audit(s, entity_type="tenancy", entity_id=TENANCY_ID, field="status",
                    old=old_status, new="active",
                    note="Physical check-in 5 Jul 2026 recorded retroactively - Room %s "
                         "(tenancy was stuck no_show since booking; onboarding link never opened)" % ROOM)

        # 2. rent schedule
        for period, due, row in rs_plan:
            label = period.strftime("%b %Y")
            if row:
                await s.execute(text(
                    "UPDATE rent_schedule SET rent_due=:d, status='paid' WHERE id=:i"),
                    {"d": due, "i": row.id})
                await audit(s, entity_type="rent_schedule", entity_id=row.id,
                            field="rent_schedule_one_off",
                            old="%s (%s)" % (row.rent_due, row.status), new="%s (paid)" % due,
                            note="%s rent restored - row was zeroed while tenancy sat no_show" % label)
            else:
                new_id = (await s.execute(text(
                    "INSERT INTO rent_schedule (tenancy_id, period_month, rent_due, maintenance_due, "
                    "                           status, due_date, adjustment, org_id) "
                    "VALUES (:t, :p, :d, 0, 'paid', :p, 0, 1) RETURNING id"),
                    {"t": TENANCY_ID, "p": period, "d": due})).scalar()
                await audit(s, entity_type="rent_schedule", entity_id=new_id,
                            field="rent_schedule_one_off", old=None, new="%s (paid)" % due,
                            note="%s rent schedule created - never existed, tenant was billed nothing" % label)

        # 3. payments
        for pdate, amt, mode, ftype, period, note in to_add:
            pid = (await s.execute(text(
                "INSERT INTO payments (tenancy_id, amount, payment_date, payment_mode, for_type, "
                "                      period_month, notes, is_void, created_at, org_id) "
                "VALUES (:t, :a, :d, :m, :f, :p, :n, false, now(), 1) RETURNING id"),
                {"t": TENANCY_ID, "a": amt, "d": pdate, "m": mode,
                 "f": ftype, "p": period, "n": note})).scalar()
            for_label = period.strftime("%b %Y") if period else ftype
            await audit(s, entity_type="payment", entity_id=pid, field="payment.log",
                        old=None, new=str(float(amt)),
                        note="Payment Rs.%s %s for %s - back-entered, paid at the time but never logged"
                             % (int(amt), mode.upper(), for_label))

        # 4. reopen onboarding session
        token = str(uuid.uuid4())
        await s.execute(text(
            "UPDATE onboarding_sessions "
            "SET status='pending_tenant', token=:tok, expires_at=:exp, cancellation_reason=NULL "
            "WHERE id=:i"),
            {"tok": token, "exp": datetime.utcnow() + timedelta(days=7), "i": SESSION_ID})
        await audit(s, entity_type="onboarding_session", entity_id=SESSION_ID, field="status",
                    old="cancelled", new="pending_tenant",
                    note="Reopened with fresh 7-day link - tenant is resident since 5 Jul but has no KYC, "
                         "no ID proof and no signed agreement on file")

        await s.commit()

        base = os.getenv("PUBLIC_BASE_URL") or "https://api.getkozzy.com"
        print("\nWRITTEN.")
        print("onboarding link: %s/onboard/%s" % (base, token))


if __name__ == "__main__":
    asyncio.run(main("--write" in sys.argv))
