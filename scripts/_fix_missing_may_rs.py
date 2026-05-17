"""
Fix: Create May 2026 rent_schedule rows for active monthly tenants that are missing them.

Skips:
  - stay_type = 'daily' (day-wise tenants — no monthly RS expected)
  - room_number = '000' (pre-register placeholders)

Proration for May check-ins (checkin_date >= 2026-05-01):
  rent_due = ceil(agreed_rent * (31 - day + 1) / 31)

Run: venv/Scripts/python scripts/_fix_missing_may_rs.py
     venv/Scripts/python scripts/_fix_missing_may_rs.py --write
"""
import asyncio, math, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

import datetime
DB_URL = os.environ["DATABASE_URL"]
MAY = datetime.date(2026, 5, 1)
MAY_STR = "2026-05-01"
DRY_RUN = "--write" not in sys.argv


async def main():
    from src.database.db_manager import init_engine, get_session
    init_engine(DB_URL)
    from sqlalchemy import text

    async with get_session() as s:
        # Step 1: get all active tenants missing May RS, with stay_type
        r = await s.execute(text("""
            SELECT
                t.name, rm.room_number, tn.id as tnid,
                tn.checkin_date, tn.agreed_rent, tn.security_deposit, tn.booking_amount,
                tn.stay_type, tn.org_id,
                COALESCE((
                    SELECT SUM(p.amount) FROM payments p
                    WHERE p.tenancy_id = tn.id AND p.for_type = 'deposit' AND p.is_void = false
                ), 0) as dep_paid
            FROM tenancies tn
            JOIN tenants t ON t.id = tn.tenant_id
            JOIN rooms rm ON rm.id = tn.room_id
            WHERE tn.status = 'active'
              AND NOT EXISTS (
                SELECT 1 FROM rent_schedule rs
                WHERE rs.tenancy_id = tn.id AND rs.period_month = :may
              )
            ORDER BY rm.room_number
        """), {"may": MAY})
        rows = r.fetchall()

        print(f"Active tenants missing May RS: {len(rows)}")
        print(f"{'Name':<30} {'Room':<6} {'Stay':<8} {'Checkin':<12} {'Rent':>8} {'Action'}")
        print("-" * 80)

        to_create = []
        for row in rows:
            name, room, tnid, checkin, rent, _sec_dep, _booking, stay_type, org_id, _dep_paid = row
            rent = int(rent or 0)

            # Skip day-wise
            if stay_type == "daily":
                print(f"  {name:<28} {room:<6} {stay_type:<8} {str(checkin):<12} {rent:>8,}  SKIP (day-wise)")
                continue

            # Skip room 000 placeholders
            if room == "000":
                print(f"  {name:<28} {room:<6} {stay_type:<8} {str(checkin):<12} {rent:>8,}  SKIP (placeholder)")
                continue

            # Calculate rent_due
            checkin_date = checkin if hasattr(checkin, "day") else datetime.date.fromisoformat(str(checkin))

            if checkin_date >= MAY:
                # First month — prorate
                days_in_month = 31
                days_occupied = days_in_month - checkin_date.day + 1
                rent_due = math.ceil(rent * days_occupied / days_in_month / 100) * 100
                note = f"Prorated {days_occupied}/{days_in_month} days (checkin {checkin_date})"
            else:
                # Full month
                rent_due = rent
                note = "Full month (continuing tenant)"

            # adjustment: booking_amount acts as advance credit in first cycle if not yet credited
            # For now — no adjustment; operator will set manually if needed
            adj = 0

            print(f"  {name:<28} {room:<6} {(stay_type or 'monthly'):<8} {str(checkin_date):<12} {rent:>8,}  CREATE RS rent_due={rent_due:,}  [{note}]")
            to_create.append({
                "tenancy_id": tnid,
                "period_month": MAY,
                "rent_due": rent_due,
                "adjustment": adj,
                "status": "pending",
                "org_id": org_id,
                "note": note,
                "name": name,
                "room": room,
            })

        print(f"\nTo create: {len(to_create)} RS rows")

        if DRY_RUN:
            print("\n[DRY RUN] Pass --write to create these rows.")
            return

        # Step 2: Create RS rows
        created = 0
        for rec in to_create:
            try:
                await s.execute(text("""
                    INSERT INTO rent_schedule (tenancy_id, period_month, rent_due, adjustment, status, org_id)
                    VALUES (:tid, :pm, :rd, :adj, 'pending', :org)
                    ON CONFLICT (tenancy_id, period_month) DO NOTHING
                """), {
                    "tid": rec["tenancy_id"],
                    "pm": rec["period_month"],
                    "rd": rec["rent_due"],
                    "adj": rec["adjustment"],
                    "org": rec["org_id"],
                })
                print(f"  Created: {rec['name']} (Room {rec['room']})  rent_due={rec['rent_due']:,}")
                created += 1
            except Exception as e:
                print(f"  ERROR {rec['name']}: {e}")

        await s.commit()
        print(f"\nDone. {created} RS rows created.")

        # Step 3: Verify — re-run the missing-RS check
        r2 = await s.execute(text("""
            SELECT COUNT(*) FROM tenancies tn
            JOIN rooms rm ON rm.id = tn.room_id
            WHERE tn.status = 'active'
              AND rm.room_number != '000'
              AND tn.stay_type != 'daily'
              AND NOT EXISTS (
                SELECT 1 FROM rent_schedule rs
                WHERE rs.tenancy_id = tn.id AND rs.period_month = :may
              )
        """), {"may": MAY})
        remaining = r2.scalar()
        print(f"Remaining active monthly tenants with no May RS: {remaining}")


if __name__ == "__main__":
    asyncio.run(main())
