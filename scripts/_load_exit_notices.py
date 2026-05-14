"""
Load exit notices for May/June 2026 tenants.
Sets notice_given=today and expected_checkout=date on matching active tenancies.

Usage:
    python scripts/_load_exit_notices.py          # dry run
    python scripts/_load_exit_notices.py --write  # commit
"""
from __future__ import annotations
import asyncio, os, sys, argparse
from datetime import date
from dateutil.relativedelta import relativedelta
sys.path.insert(0, ".")
from dotenv import load_dotenv; load_dotenv()
from src.database.db_manager import init_db, get_session
from sqlalchemy import text

TODAY = date(2026, 5, 4)

# (room, name_fragment, checkout_date or None for calc, months_to_add)
# name_fragment: lowercase substring to match against DB name
# If months_to_add > 0: checkout = checkin_date + N months
NOTICES = [
    ("522",  "adithya",         date(2026, 5, 31), 0),
    ("G15",  "ulaganadhan",     date(2026, 5, 31), 0),
    ("621",  "ashit",           date(2026, 5, 15), 0),
    ("617",  "gaurav",          date(2026, 5, 31), 0),
    ("517",  "pratik",          date(2026, 5, 31), 0),
    ("G10",  "rajdeep",         date(2026, 5, 31), 0),
    ("G03",  "revant",          date(2026, 6, 15), 0),   # "june mid" -> June 15
    ("420",  "prithviraj",      date(2026, 5, 31), 0),
    ("314",  "bhanu",           date(2026, 5, 31), 0),   # V. Bhanu Prakash
    ("510",  "bijayananda",     date(2026, 5, 31), 0),
    ("418",  "gnanesh",         date(2026, 5, 31), 0),
    ("216",  "arun",            date(2026, 5, 21), 0),   # Arun Vasavan
    ("510",  "charan",          date(2026, 6, 5),  0),   # P.N.Charan
    ("214",  "akshitha",        date(2026, 5, 31), 0),
    ("209",  "shubham",         date(2026, 6, 2),  0),
    ("209",  "joshua",          date(2026, 6, 2),  0),
    ("511",  "suraj",           date(2026, 6, 7),  0),
    ("521",  "vadi",            date(2026, 5, 31), 0),   # Vadi Raj Nandlal
    ("621",  "sajith",          date(2026, 6, 14), 0),
    ("116",  "manya",           date(2026, 6, 7),  0),
    ("116",  "roshni",          date(2026, 6, 7),  0),
    ("118",  "tejas",           date(2026, 6, 7),  0),
    ("618",  "priyanshi",       date(2026, 6, 7),  0),
    ("624",  "anugun",          date(2026, 6, 7),  0),
    ("411",  "sparsh gupta",    date(2026, 6, 7),  0),
    ("307",  "diya",            date(2026, 6, 7),  0),
    ("507",  "jay mahajan",     date(2026, 6, 7),  0),
    ("103",  "harshitha",       date(2026, 6, 7),  0),
    ("307",  "sonali",          date(2026, 6, 7),  0),
    ("409",  "preesha",         date(2026, 6, 7),  0),
    ("507",  "ivish",           date(2026, 6, 7),  0),
    ("409",  "amisha",          date(2026, 6, 7),  0),
    ("208",  "rakshit",         date(2026, 6, 7),  0),
    ("514",  "anmol",           date(2026, 6, 7),  0),
    ("514",  "gayatri",         date(2026, 6, 7),  0),
    ("607",  "arpit",           date(2026, 6, 7),  0),
    ("213",  "tanishka",        date(2026, 6, 7),  0),
    ("615",  "anshika",         None,              3),   # 3-month stay
    ("610",  "akshayarathna",   date(2026, 6, 4),  0),
    ("224",  "surajit",         date(2026, 5, 31), 0),
    ("611",  "omkar vijaykumar",None,              2),   # 2-month stay
    ("414",  "prajwal",         None,              1),   # 1-month stay
    ("413",  "sparsh rawat",    date(2026, 5, 23), 0),
    ("314",  "sathya priya",    date(2026, 5, 31), 0),
    ("214",  "jahnavi",         None,              2),   # 2-month stay
    ("207",  "anand",           date(2026, 5, 15), 0),
]


async def run(write: bool):
    db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL") or ""
    await init_db(db_url)
    async with get_session() as s:
        rows = (await s.execute(text("""
            SELECT r.room_number, lower(t2.name) as lname, t2.name, t1.checkin_date,
                   t1.id as tenancy_id, t1.notice_date, t1.expected_checkout
            FROM tenancies t1
            JOIN tenants t2 ON t2.id = t1.tenant_id
            JOIN rooms r ON r.id = t1.room_id
            WHERE t1.status = 'active'
            ORDER BY r.room_number, t2.name
        """))).all()

        # Index by room -> list of tenants
        by_room: dict[str, list] = {}
        for r in rows:
            by_room.setdefault(r.room_number.upper(), []).append(r)

        found, not_found, skipped = [], [], []

        for room, name_frag, checkout_date, months in NOTICES:
            candidates = by_room.get(room.upper(), [])
            match = None
            for c in candidates:
                if name_frag.lower() in c.lname:
                    match = c
                    break

            if not match:
                not_found.append(f"  NOT FOUND: room {room}  '{name_frag}'  (candidates: {[c.name for c in candidates]})")
                continue

            # Resolve date
            if months > 0:
                checkout = match.checkin_date + relativedelta(months=months)
            else:
                checkout = checkout_date

            # Already set?
            if match.notice_date and match.expected_checkout == checkout:
                skipped.append(f"  SKIP (already set): room {room}  {match.name}  -> {checkout}")
                continue

            action = "SET" if not match.notice_date else "UPDATE"
            found.append((match.tenancy_id, match.name, room, checkout, action))
            print(f"  {action}: room {room:<5} {match.name:<28} -> {checkout}  (checkin={match.checkin_date})")

        print(f"\nFound: {len(found)}  |  Not found: {len(not_found)}  |  Already set: {len(skipped)}")

        if not_found:
            print("\nNot found:")
            for s_ in not_found:
                print(s_)

        if skipped:
            print("\nAlready set:")
            for s_ in skipped:
                print(s_)

        if not found:
            print("Nothing to update.")
            return

        if write:
            for tenancy_id, _, _, checkout, _ in found:
                await s.execute(text("""
                    UPDATE tenancies
                    SET notice_date = :today, expected_checkout = :checkout
                    WHERE id = :tid
                """), {"today": TODAY, "checkout": checkout, "tid": tenancy_id})
            await s.commit()
            print(f"\n** COMMITTED — {len(found)} notices set **")
        else:
            print("\n** DRY RUN — no changes **")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.write))
