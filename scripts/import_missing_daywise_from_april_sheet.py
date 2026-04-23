"""
scripts/import_missing_daywise_from_april_sheet.py
===================================================
Read April Month Collection → Day wise tab. For each row, check DB
daywise_stays for a matching phone; if missing, insert it.

Usage:
    venv/Scripts/python scripts/import_missing_daywise_from_april_sheet.py           # dry
    venv/Scripts/python scripts/import_missing_daywise_from_april_sheet.py --write   # commit
"""
import asyncio
import os
import re
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import dotenv_values
env = dotenv_values(".env")
os.environ.update({k: v for k, v in env.items() if v is not None and k not in os.environ})

import gspread
from google.oauth2.service_account import Credentials
from sqlalchemy import select

from src.database.db_manager import init_engine, get_session
from src.database.models import DaywiseStay
from src.integrations.gsheets import CREDENTIALS_PATH

APRIL_SHEET = "1Vr_fSIOuuKBK4MWF-FVqgAIUPbqun3POszaXYfj-Ea0"

COL = {
    "room": 0, "name": 1, "phone": 2, "checkin": 3, "booking": 4,
    "stay": 5, "days": 6, "action": 7, "rate": 8, "sharing": 9,
    "occupancy": 10, "paid_date": 11, "comments": 12, "staff": 13, "status": 14,
}


def ph10(s):
    d = re.sub(r"\D", "", str(s or ""))
    return d[-10:] if len(d) >= 10 else d


def parse_date(s):
    s = (s or "").strip()
    if not s:
        return None
    # Try dd/mm/yyyy
    m = re.match(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})", s)
    if m:
        d, mo, y = int(m[1]), int(m[2]), int(m[3])
        try:
            return date(y, mo, d)
        except ValueError:
            return None
    # Try yyyy-mm-dd
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        y, mo, d = int(m[1]), int(m[2]), int(m[3])
        try:
            return date(y, mo, d)
        except ValueError:
            return None
    return None


def pn(s):
    try:
        return float(str(s).replace(",", "").strip() or 0)
    except Exception:
        return 0.0


def main(write: bool):
    scopes = ["https://www.googleapis.com/auth/spreadsheets",
              "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=scopes)
    gc = gspread.authorize(creds)
    ss = gc.open_by_key(APRIL_SHEET)
    ws = ss.worksheet("Day wise")
    rows = ws.get_all_values()
    print(f"April Month Collection Day wise rows: {len(rows)-1}")

    async def collect():
        init_engine(os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL"))
        async with get_session() as s:
            existing = (await s.execute(select(DaywiseStay))).scalars().all()
            existing_phones = {ph10(r.phone) for r in existing if r.phone}
            return existing_phones

    existing_phones = asyncio.run(collect())
    print(f"DB daywise phones: {len(existing_phones)}")

    to_insert = []
    skipped = 0
    for ri, r in enumerate(rows[1:], start=2):
        if not r or not (r[COL["name"]] or "").strip():
            continue
        name = r[COL["name"]].strip()
        phone = ph10(r[COL["phone"]] if len(r) > COL["phone"] else "")
        checkin = parse_date(r[COL["checkin"]] if len(r) > COL["checkin"] else "")
        days = int(pn(r[COL["days"]] if len(r) > COL["days"] else 0) or 0)
        rate = pn(r[COL["rate"]] if len(r) > COL["rate"] else 0)
        booking = pn(r[COL["booking"]] if len(r) > COL["booking"] else 0)
        sharing_raw = (r[COL["sharing"]] if len(r) > COL["sharing"] else "").strip()
        occupancy_raw = (r[COL["occupancy"]] if len(r) > COL["occupancy"] else "").strip()
        try: sharing = int(sharing_raw) if sharing_raw else None
        except ValueError: sharing = None
        try: occupancy = int(occupancy_raw) if occupancy_raw else None
        except ValueError: occupancy = None
        comments = r[COL["comments"]] if len(r) > COL["comments"] else ""
        staff = r[COL["staff"]] if len(r) > COL["staff"] else ""
        room = (r[COL["room"]] if len(r) > COL["room"] else "").strip()
        stay_txt = (r[COL["stay"]] if len(r) > COL["stay"] else "").strip()
        status_raw = (r[COL["status"]] if len(r) > COL["status"] else "").strip().upper()
        if phone and phone in existing_phones:
            skipped += 1
            continue
        if not phone or not checkin:
            print(f"  SKIP row {ri}: {name} phone={phone} ci={checkin} (insufficient data)")
            continue

        checkout = (checkin + timedelta(days=max(days - 1, 0))) if days > 0 else None
        status = "ACTIVE" if "CHECKIN" in status_raw else "EXIT"
        total = rate * days if rate and days else booking

        to_insert.append({
            "room_number": room,
            "guest_name": name,
            "phone": phone,
            "checkin_date": checkin,
            "checkout_date": checkout,
            "num_days": days or None,
            "stay_period": stay_txt,
            "sharing": sharing,
            "occupancy": occupancy,
            "booking_amount": booking,
            "daily_rate": rate,
            "total_amount": total,
            "maintenance": 0,
            "payment_date": parse_date(r[COL["paid_date"]] if len(r) > COL["paid_date"] else ""),
            "assigned_staff": staff,
            "status": status,
            "comments": comments,
            "source_file": "April Month Collection Day wise (import 2026-04-23)",
            "unique_hash": f"aprapr_{phone}_{checkin.isoformat()}",
        })

    print(f"\nAlready in DB: {skipped}")
    print(f"To insert:     {len(to_insert)}")
    for x in to_insert:
        print(f"  {x['guest_name']:25s} phone={x['phone']:12s} room={x['room_number']:5s} ci={x['checkin_date']} co={x['checkout_date']} days={x['num_days']} status={x['status']} rate={x['daily_rate']}")

    if not write:
        print("\n[DRY RUN] Pass --write to apply.")
        return

    async def do_insert():
        init_engine(os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL"))
        async with get_session() as s:
            for payload in to_insert:
                s.add(DaywiseStay(**payload))
            await s.commit()

    asyncio.run(do_insert())
    print(f"\n[ok] Inserted {len(to_insert)} daywise_stays.")
    print("Next: python scripts/sync_daywise_from_db.py --write")


if __name__ == "__main__":
    main("--write" in sys.argv)
