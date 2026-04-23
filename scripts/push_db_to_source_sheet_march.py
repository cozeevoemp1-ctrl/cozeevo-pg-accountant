"""
scripts/push_db_to_source_sheet_march.py
=========================================
One-off: push DB March rent payments into the SOURCE Google Sheet
(Cozeevo Monthly stay, gid=0/History tab) so source-sheet March Cash /
March UPI columns match DB 1:1.

WHY THIS EXISTS
----------------
2026-04-22 incident: DB had correct March settlements (₹25.61L cash +
₹28.89L UPI, including the 116 settlement rows added by
settle_march_dues.py on 2026-04-21). Source sheet was stale (₹10.94L
cash). A mistaken sheet-reload voided DB correct rows. Kiran decided
DB is truth; source sheet must be updated to match.

RULES
------
- DB is the source of truth. This script is the ONLY sanctioned way to
  write March numbers back into source sheet.
- First-match-only: if a tenant appears on multiple sheet rows (checkin /
  exit / re-checkin), DB totals go into the FIRST row; duplicates zero'd.
- Dry-run by default. Pass --write to actually update the sheet.
- Never touch April / May columns. Only March Cash + March UPI.

Usage:
    venv/Scripts/python scripts/push_db_to_source_sheet_march.py          # dry run
    venv/Scripts/python scripts/push_db_to_source_sheet_march.py --write  # commit
"""
import asyncio
import os
import re
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import dotenv_values
env = dotenv_values(".env")
os.environ.update({k: v for k, v in env.items() if v is not None and k not in os.environ})

import gspread
from google.oauth2.service_account import Credentials
from src.integrations.gsheets import CREDENTIALS_PATH
from src.database.db_manager import init_engine, get_session
from src.database.models import Payment, PaymentMode, PaymentFor, Tenant, Tenancy, Room
from sqlalchemy import select, and_, func

SOURCE_SHEET_ID = "1jOCVBkVurLNaht9HYKR6SFqGCciIoMWeOJkfKF9essk"
PERIOD = date(2026, 3, 1)


def nph(p):
    d = re.sub(r"\D", "", str(p or ""))
    return d[-10:] if len(d) >= 10 else ""


def nname(s):
    return re.sub(r"[^a-z]", "", str(s or "").lower())


async def load_db_totals():
    init_engine(os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL"))
    async with get_session() as s:
        q = (
            select(
                Tenant.phone,
                Tenant.name,
                Room.room_number,
                Payment.payment_mode,
                func.sum(Payment.amount),
            )
            .join(Tenancy, Payment.tenancy_id == Tenancy.id)
            .join(Tenant, Tenancy.tenant_id == Tenant.id)
            .join(Room, Tenancy.room_id == Room.id, isouter=True)
            .where(
                and_(
                    Payment.period_month == PERIOD,
                    Payment.for_type == PaymentFor.rent,
                    Payment.is_void.is_(False),
                )
            )
            .group_by(Tenant.phone, Tenant.name, Room.room_number, Payment.payment_mode)
        )
        db_data = {}
        for ph, nm, rm, mode, amt in (await s.execute(q)).all():
            key = nph(ph) or (nname(nm) + "|" + str(rm or ""))
            rec = db_data.setdefault(
                key, {"name": nm, "room": rm, "phone": ph, "cash": 0.0, "upi": 0.0}
            )
            if mode == PaymentMode.cash:
                rec["cash"] += float(amt)
            else:
                rec["upi"] += float(amt)
    return db_data


def main(write: bool):
    loop = asyncio.get_event_loop()
    db_data = loop.run_until_complete(load_db_totals())
    print(f"DB: {len(db_data)} tenants with March rent")
    db_cash = sum(v["cash"] for v in db_data.values())
    db_upi = sum(v["upi"] for v in db_data.values())
    print(f"DB totals: Cash Rs.{db_cash:,.0f}  UPI Rs.{db_upi:,.0f}")

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=scopes)
    gc = gspread.authorize(creds)
    ss = gc.open_by_key(SOURCE_SHEET_ID)
    hist = ss.worksheet("History")
    rows = hist.get_all_values()
    h = rows[0]
    i_name = h.index("Name")
    i_mob = h.index("Mobile Number")
    i_room = h.index("Room No")
    i_cash = h.index("March Cash")
    i_upi = h.index("March UPI")

    used_keys = set()
    updates = []  # list of (row_idx, cash, upi, status)
    matched = duplicates = no_db = zero_both = 0
    plan_cash = plan_upi = 0.0
    for ri, r in enumerate(rows[1:], start=2):
        if not r or not r[0].strip():
            continue
        ph = nph(r[i_mob])
        key = ph or (nname(r[i_name]) + "|" + r[i_room].strip())
        if key in db_data and key not in used_keys:
            d = db_data[key]
            used_keys.add(key)
            updates.append((ri, d["cash"], d["upi"], "matched"))
            plan_cash += d["cash"]
            plan_upi += d["upi"]
            matched += 1
        elif key in db_data:
            updates.append((ri, 0, 0, "dup-zeroed"))
            duplicates += 1
        else:
            updates.append((ri, 0, 0, "no-db"))
            no_db += 1

    missing_keys = set(db_data) - used_keys
    print(f"Sheet rows processed: {len(updates)}")
    print(f"  matched          : {matched}")
    print(f"  duplicates zeroed: {duplicates}")
    print(f"  no-db (stale)    : {no_db}")
    print(f"  DB keys not in sheet: {len(missing_keys)}")
    print(f"Plan totals to write: Cash Rs.{plan_cash:,.0f}  UPI Rs.{plan_upi:,.0f}")
    print(f"Match vs DB: cash diff {plan_cash - db_cash:+,.0f}  upi diff {plan_upi - db_upi:+,.0f}")
    if missing_keys:
        print(f"\n!! {len(missing_keys)} DB tenants without sheet row:")
        for k in list(missing_keys)[:10]:
            d = db_data[k]
            print(f"   {d['name']:30s} phone={d['phone']} room={d['room']} cash={d['cash']:,.0f} upi={d['upi']:,.0f}")

    if not write:
        print("\nDry-run only. Pass --write to apply.")
        return

    # Batch update: two ranges (March Cash column, March UPI column).
    # gspread batch_update with A1 ranges.
    # Column letters:
    def col_letter(idx_0):
        i = idx_0 + 1
        s = ""
        while i:
            i, r = divmod(i - 1, 26)
            s = chr(65 + r) + s
        return s

    cash_col = col_letter(i_cash)
    upi_col = col_letter(i_upi)

    # Build per-cell updates; gspread can do batch on ranges
    cash_data = [[0] for _ in range(len(rows) - 1)]
    upi_data = [[0] for _ in range(len(rows) - 1)]
    for ri, c, u, _status in updates:
        cash_data[ri - 2] = [int(c) if c else ""]
        upi_data[ri - 2] = [int(u) if u else ""]

    print(f"\nWriting Cash column {cash_col}2:{cash_col}{len(rows)} and UPI {upi_col}2:{upi_col}{len(rows)}...")
    hist.update(f"{cash_col}2:{cash_col}{len(rows)}", cash_data, raw=False)
    hist.update(f"{upi_col}2:{upi_col}{len(rows)}", upi_data, raw=False)
    print("DONE. Source sheet March Cash + March UPI now mirror DB 1:1.")


if __name__ == "__main__":
    write = "--write" in sys.argv
    main(write)
