"""
scripts/reload_march_from_source.py
====================================
Wipe all DB March 2026 rent payments and rebuild them 1:1 from the Cozeevo
Monthly stay source sheet (March Cash + March UPI columns).

WHY
---
March is a frozen month. Source sheet is the authoritative record, not DB.
Previous scripts (settle_march_dues.py etc.) inserted phantom cash that made
DB drift from source. This script resets DB to match source exactly, then
the Ops v2 MARCH 2026 tab can be rebuilt from DB via sync_sheet_from_db.py.

Usage:
    venv/Scripts/python scripts/reload_march_from_source.py          # dry
    venv/Scripts/python scripts/reload_march_from_source.py --write  # commit
"""
import asyncio
import os
import re
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import dotenv_values
env = dotenv_values(".env")
os.environ.update({k: v for k, v in env.items() if v is not None and k not in os.environ})

import gspread
from google.oauth2.service_account import Credentials
from sqlalchemy import select, update, and_
from sqlalchemy.orm import selectinload

from src.database.db_manager import init_engine, get_session
from src.database.models import (
    Tenant, Tenancy, Room, Payment, PaymentMode, PaymentFor,
)
from src.integrations.gsheets import CREDENTIALS_PATH

SOURCE_SHEET_ID = "1jOCVBkVurLNaht9HYKR6SFqGCciIoMWeOJkfKF9essk"
PERIOD = date(2026, 3, 1)

IC = 32   # March Cash
IU = 33   # March UPI
IP = 3    # Phone
IN = 1    # Name
IR = 0    # Room


def pn(s):
    if s is None or s == "":
        return 0.0
    try:
        return float(str(s).replace(",", "").strip())
    except Exception:
        return 0.0


def ph10(s):
    d = re.sub(r"\D", "", str(s or ""))
    return d[-10:] if len(d) >= 10 else d


def nname(s):
    return re.sub(r"[^a-z]", "", str(s or "").lower())


def read_source():
    scopes = ["https://www.googleapis.com/auth/spreadsheets",
              "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=scopes)
    gc = gspread.authorize(creds)
    ss = gc.open_by_key(SOURCE_SHEET_ID)
    ws = ss.worksheet("History")
    rows = ws.get_all_values()
    out = []  # list of dicts
    for r in rows[1:]:
        if not r or not (r[IN] if len(r) > IN else "").strip():
            continue
        cash = pn(r[IC] if len(r) > IC else 0)
        upi = pn(r[IU] if len(r) > IU else 0)
        if cash == 0 and upi == 0:
            continue
        out.append({
            "room": (r[IR] if len(r) > IR else "").strip(),
            "name": (r[IN] if len(r) > IN else "").strip(),
            "phone": ph10(r[IP] if len(r) > IP else ""),
            "cash": cash,
            "upi": upi,
        })
    return out


async def match_db_tenancies(src_rows):
    """Map each source row to a DB tenancy_id. First pass phone, then name+room."""
    init_engine(os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL"))
    async with get_session() as s:
        # Pull all tenancies whose tenant created before April
        q = (
            select(Tenancy)
            .options(
                selectinload(Tenancy.tenant),
                selectinload(Tenancy.room),
            )
        )
        all_ten = (await s.execute(q)).scalars().all()

    by_phone = {}
    by_name_room = {}
    for t in all_ten:
        ph = ph10(t.tenant.phone if t.tenant else "")
        rm = str(t.room.room_number if t.room else "")
        nm = nname(t.tenant.name if t.tenant else "")
        if ph:
            by_phone.setdefault(ph, []).append(t)
        by_name_room.setdefault(nm + "|" + rm, []).append(t)

    matched, missing = [], []
    for r in src_rows:
        cand = by_phone.get(r["phone"], []) or by_name_room.get(nname(r["name"]) + "|" + r["room"], [])
        # Prefer tenancies whose checkin <= March 31
        mar_end = date(2026, 3, 31)
        cand = [c for c in cand if (not c.checkin_date) or c.checkin_date <= mar_end]
        if cand:
            # if multiple candidates, pick the one with earliest checkin
            cand.sort(key=lambda x: (x.checkin_date or date(2099, 1, 1)))
            matched.append((r, cand[0].id))
        else:
            missing.append(r)
    return matched, missing


async def main(write: bool):
    src = read_source()
    total_cash = sum(r["cash"] for r in src)
    total_upi = sum(r["upi"] for r in src)
    print(f"Source sheet March rows with data: {len(src)}")
    print(f"Source Cash: Rs.{total_cash:,.0f}  UPI: Rs.{total_upi:,.0f}  Total: Rs.{total_cash+total_upi:,.0f}")

    matched, missing = await match_db_tenancies(src)
    m_cash = sum(r["cash"] for r, _ in matched)
    m_upi = sum(r["upi"] for r, _ in matched)
    miss_cash = sum(r["cash"] for r in missing)
    miss_upi = sum(r["upi"] for r in missing)
    print(f"\nMatched to DB: {len(matched)}  (Cash Rs.{m_cash:,.0f}  UPI Rs.{m_upi:,.0f})")
    print(f"Unmatched:     {len(missing)} (Cash Rs.{miss_cash:,.0f}  UPI Rs.{miss_upi:,.0f})")
    if missing:
        for r in missing[:20]:
            print(f"  {r['name']:28s}  phone={r['phone']}  room={r['room']}  cash={r['cash']:,.0f}  upi={r['upi']:,.0f}")

    if not write:
        print("\n[DRY RUN] Would:")
        print(f"  1) Void all existing DB March rent payments (is_void=True)")
        print(f"  2) Insert {sum(1 for r,_ in matched if r['cash']>0)} cash + {sum(1 for r,_ in matched if r['upi']>0)} UPI fresh payments")
        print("Pass --write to apply.")
        return

    async with get_session() as s:
        # Void existing March rent payments
        existing = (await s.execute(
            select(Payment).where(and_(
                Payment.period_month == PERIOD,
                Payment.for_type == PaymentFor.rent,
                Payment.is_void.is_(False),
            ))
        )).scalars().all()
        print(f"\nVoiding {len(existing)} existing March rent payments...")
        for p in existing:
            p.is_void = True
            p.notes = (p.notes or "") + " | voided 2026-04-23 match-source"
        await s.commit()

        # Insert fresh payments
        inserted = 0
        for r, tid in matched:
            if r["cash"] > 0:
                s.add(Payment(
                    tenancy_id=tid,
                    amount=r["cash"],
                    payment_date=date(2026, 3, 31),
                    payment_mode=PaymentMode.cash,
                    for_type=PaymentFor.rent,
                    period_month=PERIOD,
                    is_void=False,
                    notes="reloaded from Cozeevo Monthly stay source sheet 2026-04-23",
                ))
                inserted += 1
            if r["upi"] > 0:
                s.add(Payment(
                    tenancy_id=tid,
                    amount=r["upi"],
                    payment_date=date(2026, 3, 31),
                    payment_mode=PaymentMode.upi,
                    for_type=PaymentFor.rent,
                    period_month=PERIOD,
                    is_void=False,
                    notes="reloaded from Cozeevo Monthly stay source sheet 2026-04-23",
                ))
                inserted += 1
        await s.commit()
        print(f"Inserted {inserted} fresh March rent payments.")

    print("\nDone. Next: python scripts/sync_sheet_from_db.py --month 3 --year 2026 --write")


if __name__ == "__main__":
    asyncio.run(main("--write" in sys.argv))
