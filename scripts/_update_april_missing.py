"""
Update DB with:
  1. Checkout Arjun Sumanth (tenancy 800, April 30)
  2. Add 12 day-wise stays from April sheet Day wise tab

Usage:
    python scripts/_update_april_missing.py          # dry run
    python scripts/_update_april_missing.py --write  # commit
"""
import asyncio, os, sys, argparse
from datetime import date, timedelta
from decimal import Decimal
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv; load_dotenv()

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from src.database.models import (
    Tenancy, Tenant, TenancyStatus, DaywiseStay, AuditLog
)

MAY = date(2026, 5, 1)

DAYWISE_STAYS = [
    # (room, name, phone, checkin, num_days, stay_period, rate, booking, comments, staff, status, checkout)
    ("407", "CH Deepthi",       "9347380025", date(2026,3,30), 4, "30 march-2 april",        750.0, 3000.0, "without food",         "Prabhakaran", "EXIT",    date(2026,4,2)),
    ("609", "Aashi reye",       "9821181441", date(2026,4,5),  2, "April 5 & 6",             1000.0,2000.0, "",                     "Satyam",      "EXIT",    date(2026,4,6)),
    ("516", "Tanish Jain",      "9834050189", date(2026,4,23), 2, "April 23rd to 25th",      1000.0,1000.0, "",                     "Prabhakaran", "EXIT",    date(2026,4,24)),
    ("209", "Yogesh",           "9158671654", date(2026,4,28), 5, "April 28th to 2nd may",    900.0,2700.0, "",                     "Prabhakaran", "EXIT",    date(2026,5,2)),
    ("209", "Rutika Jadhau",    "8087816925", date(2026,4,28), 5, "April 28th to 2nd may",    900.0,2700.0, "",                     "Prabhakaran", "EXIT",    date(2026,5,2)),
    ("G13", "Rueban",           "6380862037", date(2026,5,1),  2, "1st may to 2nd may",       650.0,1300.0, "1300 UPI Paid",        "Prabhakaran", "EXIT",    date(2026,5,2)),
    ("123", "Prem Prasana",     "7899338477", date(2026,5,4),  1, "4th may one day",          850.0, 850.0, "Paid by UPI",          "Lakshmi",     "EXIT",    date(2026,5,4)),
    ("121", "L Jagan Raj",      "9500747313", date(2026,5,5),  3, "May 5th to 7th",           900.0,2700.0, "Paid by UPI",          "Lakshmi",     "EXIT",    date(2026,5,7)),
    ("519", "Anu",              "",           date(2026,5,6),  1, "May 6",                   1200.0,1200.0, "cash",                 "Lakshmi",     "CHECKIN", date(2026,5,6)),
    ("219", "Ranjith",          "7397344674", date(2026,5,8),  2, "8th may and 9th may",     1200.0,3400.0, "3000 CASH 400 gPAY",  "Prabhakaran", "CHECKIN", date(2026,5,9)),
    ("107", "Sai Prasad",       "",           date(2026,5,7),  1, "7th may",                 1000.0,1000.0, "1000 UPI",            "Chandra",     "EXIT",    date(2026,5,7)),
    ("G03", "Abhiraj Painedy",  "7060733161", date(2026,5,9),  2, "9th morning till 10th evening", 900.0,1800.0,"1800 UPI",        "Prabhakaran", "CHECKIN", date(2026,5,10)),
]


def norm_phone(raw):
    import re
    d = re.sub(r'\D', '', str(raw or ''))
    if d.startswith('91') and len(d) == 12:
        d = d[2:]
    return '+91' + d if len(d) == 10 else ''


async def run(write: bool):
    url = os.environ["DATABASE_URL"]
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(url, echo=False)
    S = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with S() as session:

        # ── 1. Checkout Arjun Sumanth ──────────────────────────────────────
        print("=" * 60)
        print("1. CHECKOUT — Arjun Sumanth (tenancy 800, April 30)")
        print("=" * 60)
        tn = await session.scalar(select(Tenancy).where(Tenancy.id == 800))
        if not tn:
            print("  ERROR: tenancy 800 not found")
        elif tn.status == TenancyStatus.exited:
            print(f"  SKIP: already exited (checkout_date={tn.checkout_date})")
        else:
            print(f"  Current status: {tn.status.value}, checkout_date={tn.checkout_date}")
            print(f"  Setting: status=exited, checkout_date=2026-04-30")
            if write:
                tn.status = TenancyStatus.exited
                tn.checkout_date = date(2026, 4, 30)
                session.add(AuditLog(
                    changed_by="system/_update_april_missing.py",
                    entity_type="tenancy",
                    entity_id=800,
                    entity_name="Arjun Sumanth",
                    field="status",
                    old_value="active",
                    new_value="exited",
                    room_number="523",
                    source="import",
                    note="Checkout April 30 — confirmed from April sheet col16=EXIT + note 'exit on april 30th'",
                ))
                print("  [ok] Updated tenancy 800 → exited, checkout_date=2026-04-30")

        # ── 2. Day-wise stays ──────────────────────────────────────────────
        print()
        print("=" * 60)
        print("2. DAY-WISE STAYS (12 entries)")
        print("=" * 60)

        existing_hashes = {
            ds.unique_hash
            for ds in (await session.execute(select(DaywiseStay))).scalars().all()
            if ds.unique_hash
        }
        existing_phones = {
            ds.phone
            for ds in (await session.execute(select(DaywiseStay))).scalars().all()
            if ds.phone
        }

        added = 0
        skipped = 0
        for room, name, raw_phone, checkin, days, stay, rate, booking, comments, staff, status, checkout in DAYWISE_STAYS:
            phone = norm_phone(raw_phone)
            total = rate * days

            h_key = phone if phone else f"{name.lower()}_{checkin.isoformat()}"
            unique_hash = f"apr2026dw_{h_key}_{checkin.isoformat()}"

            if unique_hash in existing_hashes:
                print(f"  SKIP (hash exists): {name}")
                skipped += 1
                continue
            if phone and phone in existing_phones:
                print(f"  SKIP (phone exists): {name} {phone}")
                skipped += 1
                continue

            print(f"  ADD: {name:<28} room={room:<6} checkin={checkin} days={days} booking=₹{int(booking):,} status={status}")
            added += 1

            if write:
                session.add(DaywiseStay(
                    room_number=room,
                    guest_name=name,
                    phone=phone or None,
                    checkin_date=checkin,
                    checkout_date=checkout,
                    num_days=days,
                    stay_period=stay,
                    sharing=2,
                    occupancy=1,
                    booking_amount=Decimal(str(booking)),
                    daily_rate=Decimal(str(rate)),
                    total_amount=Decimal(str(total)),
                    maintenance=Decimal("0"),
                    payment_date=checkin,
                    assigned_staff=staff,
                    status=status,
                    comments=comments,
                    source_file="April Month Collection Day wise (import 2026-05-09)",
                    unique_hash=unique_hash,
                ))

        print(f"\n  To add: {added}  |  Skipped: {skipped}")

        if write:
            await session.commit()
            print("\n** COMMITTED **")
        else:
            print("\n[DRY RUN] Pass --write to apply.")

    await engine.dispose()
    print("\nDone.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.write))
