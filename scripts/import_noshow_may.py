"""
scripts/import_noshow_may.py
Import 12 no-show tenants (checking in May 2026) from source sheet into DB.

Usage:
    python scripts/import_noshow_may.py          # dry run
    python scripts/import_noshow_may.py --write  # commit to DB
"""
import asyncio, argparse, os, sys, re
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv; load_dotenv()

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from src.database.models import (
    Tenant, Tenancy, Room, Property, Payment,
    TenancyStatus, SharingType, PaymentFor, PaymentMode,
)
from src.services.room_occupancy import canonical_phone

DB = os.environ["DATABASE_URL"].replace("postgresql://", "postgresql+asyncpg://", 1)

# ── Source data from April Month Collection sheet ──────────────────────────
NO_SHOWS = [
    # room, name, phone, gender, checkin, booking_amt, deposit, maintenance, rent, sharing, block, booking_paid_upi
    ("520", "Prasad Vadlamani", "7842274020",  "Male",   "2026-05-01", 2000, 13500, 5000, 13500, "double", "HULK", 0),
    ("309", "Aravind",          "7010432821",  "Male",   "2026-05-01", 2000, 13000, 5000, 13000, "double", "HULK", 0),
    ("309", "Santhosh",         "8668108281",  "Male",   "2026-05-01", 2000, 13000, 5000, 13000, "double", "HULK", 0),
    ("G17", "Ajay Ramchandra",  "9762787689",  "Male",   "2026-05-01", 2000, 12000, 5000, 12000, "double", "HULK", 0),
    ("210", "Alma Siddique",    "9340019654",  "Female", "2026-05-02", 5000, 13500, 5000, 13500, "double", "HULK", 5000),
    ("610", "Baisali Das",      "9810028352",  "Female", "2026-05-01", 2000, 12500, 5000, 12500, "single", "THOR", 2000),
    ("219", "Ganesh Magi",      "7899402470",  "Male",   "2026-05-01", 2000, 13500, 5000, 13500, "double", "HULK", 2000),
    ("221", "Arnab Roy",        "7586924842",  "Male",   "2026-05-01", 2000, 13500, 5000, 13500, "double", "HULK", 2000),
    ("304", "Saksham Tapadia",  "8058123877",  "Male",   "2026-05-01", 2000, 16000, 5000, 16000, "double", "THOR", 2000),
    ("304", "Anush Sharma",     "7014705985",  "Male",   "2026-05-01", 2000, 16000, 5000, 16000, "double", "THOR", 2000),
    ("514", "Ayush Kolte",      "8888012597",  "Male",   "2026-05-01", 2000, 13000, 5000, 13000, "double", "HULK", 2000),
    ("514", "Diksha",           "8295625664",  "Female", "2026-05-01", 2000, 13000, 5000, 13000, "double", "HULK", 2000),
]

SHARING_MAP = {"double": SharingType.double, "single": SharingType.single,
               "triple": SharingType.triple, "premium": SharingType.premium}


async def main(write: bool):
    engine = create_async_engine(DB, echo=False)
    Sess   = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Sess() as s:
        # Pre-load rooms by room_number
        room_map: dict[str, Room] = {
            r.room_number: r
            for r in (await s.execute(select(Room))).scalars().all()
        }

        results = []
        for (room_no, name, raw_phone, gender, checkin_str,
             booking_amt, deposit, maintenance, rent,
             sharing, block, paid_upi) in NO_SHOWS:

            phone     = canonical_phone(raw_phone)
            checkin   = date.fromisoformat(checkin_str)
            room      = room_map.get(room_no)

            issues = []
            if room is None:
                issues.append(f"ROOM {room_no} not found in DB")

            # Check if tenant already exists by phone
            tenant = (await s.execute(
                select(Tenant).where(Tenant.phone == phone)
            )).scalars().first()

            # Check if tenancy already exists for this tenant + room
            existing_tenancy = None
            if tenant and room:
                existing_tenancy = (await s.execute(
                    select(Tenancy).where(
                        Tenancy.tenant_id == tenant.id,
                        Tenancy.room_id   == room.id,
                        Tenancy.status    == TenancyStatus.no_show,
                    )
                )).scalars().first()

            # Check room capacity for May 1
            beds_taken = 0
            if room:
                existing_occ = (await s.execute(
                    select(Tenancy).where(
                        Tenancy.room_id == room.id,
                        Tenancy.status.in_([TenancyStatus.active, TenancyStatus.no_show]),
                    )
                )).scalars().all()
                beds_taken = len(existing_occ)
                max_occ = room.max_occupancy or 1
                if beds_taken >= max_occ and not existing_tenancy:
                    issues.append(
                        f"ROOM FULL: {room_no} has {beds_taken}/{max_occ} beds taken"
                    )

            status_str = "SKIP (already exists)" if existing_tenancy else \
                         "ERROR" if issues else "OK"

            bal_check = deposit + rent - booking_amt
            results.append({
                "room": room_no, "name": name, "phone": phone,
                "checkin": checkin_str, "rent": rent, "deposit": deposit,
                "booking_amt": booking_amt, "paid_upi": paid_upi,
                "bal_check": bal_check, "sharing": sharing,
                "status": status_str, "issues": issues,
                "tenant": tenant, "room_obj": room,
                "existing_tenancy": existing_tenancy,
                "gender": gender, "maintenance": maintenance,
                "checkin_date": checkin,
            })

        # Print plan
        print(f"{'Room':<5} {'Name':<22} {'Checkin':<11} {'Rent':>6} {'Dep':>6} "
              f"{'Bk':>5} {'PaidUPI':>7} {'BalCheck':>9} {'Status'}")
        print("-" * 95)
        for r in results:
            print(f"{r['room']:<5} {r['name'][:22]:<22} {r['checkin']:<11} "
                  f"{r['rent']:>6,} {r['deposit']:>6,} {r['booking_amt']:>5,} "
                  f"{r['paid_upi']:>7,} {r['bal_check']:>9,} {r['status']}")
            for iss in r["issues"]:
                print(f"       !! {iss}")
        print()

        ok_count = sum(1 for r in results if r["status"] == "OK")
        skip_count = sum(1 for r in results if r["status"].startswith("SKIP"))
        err_count  = sum(1 for r in results if r["status"] == "ERROR")
        print(f"Will import: {ok_count}  Already exists: {skip_count}  Errors: {err_count}")

        if not write:
            print("\n[DRY RUN] — run with --write to import.")
            await engine.dispose()
            return

        if err_count:
            print(f"\nAborting — fix {err_count} error(s) first.")
            await engine.dispose()
            return

        # ── Write ──────────────────────────────────────────────────────────
        imported = 0
        for r in results:
            if r["status"] != "OK":
                continue

            room     = r["room_obj"]
            checkin  = r["checkin_date"]

            # Upsert tenant
            tenant = r["tenant"]
            if tenant is None:
                tenant = Tenant(
                    name    = r["name"],
                    phone   = r["phone"],
                    gender  = r["gender"].lower(),
                )
                s.add(tenant)
                await s.flush()  # get tenant.id

            # Create tenancy
            sharing_type = SHARING_MAP.get(r["sharing"], SharingType.double)
            tenancy = Tenancy(
                tenant_id       = tenant.id,
                room_id         = room.id,
                status          = TenancyStatus.no_show,
                checkin_date    = checkin,
                agreed_rent     = r["rent"],
                security_deposit= r["deposit"],
                maintenance_fee = r["maintenance"],
                booking_amount  = r["booking_amt"],
                sharing_type    = sharing_type,
            )
            s.add(tenancy)
            await s.flush()  # get tenancy.id

            # Record booking advance payment if actually paid
            if r["paid_upi"] > 0:
                pay = Payment(
                    tenancy_id    = tenancy.id,
                    amount        = r["paid_upi"],
                    payment_mode  = PaymentMode.upi,
                    for_type      = PaymentFor.booking,
                    payment_date  = date(2026, 4, 26),
                    period_month  = date(2026, 5, 1),
                    notes         = "Booking advance from source sheet import",
                )
                s.add(pay)

            print(f"  [ok] {r['room']} {r['name']} — tenancy {tenancy.id}"
                  f"  booking_paid={r['paid_upi']:,}")
            imported += 1

        await s.commit()
        print(f"\nImported {imported} no-show tenancies.")

    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    asyncio.run(main(parser.parse_args().write))
