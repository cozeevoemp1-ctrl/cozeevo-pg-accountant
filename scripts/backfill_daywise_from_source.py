"""Backfill DaywiseStay.checkout_date + num_days from the SOURCE 'Day wise'
tab on the Cozeevo Day wise sheet.

Source authoritative columns:
  col3 'Checkin date' (DD/MM/YYYY)
  col5 'stay'         (free text)
  col6 'No.Of.days'   (integer)

Match: by guest_name (case-insensitive, fuzzy) + checkin_date.
Derive: checkout = checkin + num_days  (1-day stay -> next day)

Also revisits all DaywiseStay rows where num_days/checkout look wrong
(num_days=1 default but source has > 1) so reminders fire on the right
day. Run --write to apply.
"""
import argparse
import asyncio
import os
import re
import sys
from datetime import date, datetime, timedelta

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

import gspread
from google.oauth2.service_account import Credentials
from sqlalchemy import select
from src.database.db_manager import init_engine, get_session
from src.database.models import DaywiseStay


SOURCE_SHEET_ID = "1Vr_fSIOuuKBK4MWF-FVqgAIUPbqun3POszaXYfj-Ea0"
TAB = "Day wise"


def parse_date(s):
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def norm(name):
    return re.sub(r"[^a-z]", "", (name or "").lower())


async def main(write: bool):
    creds = Credentials.from_service_account_file(
        "credentials/gsheets_service_account.json",
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SOURCE_SHEET_ID)
    rows = sh.worksheet(TAB).get_all_values()[1:]

    src = []
    for r in rows:
        if len(r) < 7:
            continue
        nm = (r[1] or "").strip()
        chk = parse_date(r[3])
        try:
            days = int(re.sub(r"[^\d]", "", r[6])) if r[6] else 0
        except ValueError:
            days = 0
        if not nm or not chk:
            continue
        src.append({"name": nm, "name_n": norm(nm), "checkin": chk, "days": days, "stay": r[5] or ""})
    print(f"Source rows: {len(src)}")

    init_engine(os.environ["DATABASE_URL"])
    async with get_session() as s:
        db_rows = (await s.execute(select(DaywiseStay))).scalars().all()
        print(f"DB rows: {len(db_rows)}\n")

        updated = matched = unmatched = 0
        for r in db_rows:
            n = norm(r.guest_name)
            # find source row by name + checkin (exact); then by name only
            cand = [x for x in src if x["name_n"] == n and x["checkin"] == r.checkin_date]
            if not cand:
                cand = [x for x in src if x["name_n"] == n and abs((x["checkin"] - r.checkin_date).days) <= 2]
            if not cand or cand[0]["days"] <= 0:
                unmatched += 1
                continue
            matched += 1
            sdays = cand[0]["days"]
            new_out = r.checkin_date + timedelta(days=sdays)
            cur_out = r.checkout_date
            cur_days = r.num_days or 0
            changed = (new_out != cur_out) or (sdays != cur_days)
            if changed:
                tag = "FIX" if cur_out else "FILL"
                print(f"  [{tag}] [{r.id}] {r.guest_name:<24} chk={r.checkin_date}  days {cur_days}->{sdays}  out {cur_out}->{new_out}  src_stay={cand[0]['stay']!r}")
                if write:
                    r.num_days = sdays
                    r.checkout_date = new_out
                updated += 1

        if write:
            await s.commit()
        print(f"\nMatched: {matched}  Unmatched: {unmatched}  Updated: {updated}")
        if not write:
            print("[DRY RUN]")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    asyncio.run(main(ap.parse_args().write))
