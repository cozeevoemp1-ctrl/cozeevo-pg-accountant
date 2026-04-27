"""
scripts/fix_march_skipped.py
============================
Insert March 2026 payments for the 9 tenants that reload_pre_april_payments.py
skipped because their room numbers in the ops sheet don't match the DB.

Matches by name only (case-insensitive). Prints amounts for review before inserting.

Usage:
    python scripts/fix_march_skipped.py          # dry run — print what would be inserted
    python scripts/fix_march_skipped.py --write  # commit to DB (uses freeze escape hatch)
"""
import asyncio
import os
import re
import sys
from decimal import Decimal
from datetime import date

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

import gspread
from google.oauth2.service_account import Credentials
from sqlalchemy import select, text

from src.database.db_manager import init_engine, get_session
from src.database.models import Tenant, Tenancy, Room, Payment, PaymentMode, PaymentFor

CREDENTIALS_PATH = "credentials/gsheets_service_account.json"
OPS_SHEET_ID = os.getenv("GSHEETS_SHEET_ID", "1Hp5dTM7TcDEq75jgHEjvwtBjOolruGfQ7CVMzVqjdGw")
MARCH = date(2026, 3, 1)
TAB_NAME = "MARCH 2026"

# These are the 9 tenants whose room numbers in the ops sheet differ from DB.
# Keyed by name (lower). Value = confirmed tenancy_id from DB.
KNOWN_TENANCY_IDS = {
    "mahika yerneni": 554,
    "ashish das":     576,
    "shirin":         602,
    "adharsh unni":   659,
    "taral":          666,
    "neha pramod":    688,
    "thirumurugan":   773,
    "aravind":        796,
    "santhosh":       797,
}


def pn(val) -> float:
    if val is None or str(val).strip() == "":
        return 0.0
    try:
        return float(str(val).replace(",", "").strip())
    except ValueError:
        return 0.0


def _open_sheet():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=scopes)
    gc = gspread.authorize(creds)
    return gc.open_by_key(OPS_SHEET_ID)


async def main(write: bool):
    print(f"Mode: {'WRITE' if write else 'DRY RUN'}")
    init_engine(os.getenv("DATABASE_URL"))

    sh = _open_sheet()
    ws = sh.worksheet(TAB_NAME)
    rows = ws.get_all_values()
    print(f"  {len(rows)} rows in '{TAB_NAME}' tab")

    # Find header row and resolve columns by name
    col_room = col_name = col_cash = col_upi = None
    data_start = 1
    for idx, row in enumerate(rows):
        headers_lower = [str(c).strip().lower() for c in row]
        if headers_lower and headers_lower[0] == "room":
            col_room = headers_lower.index("room")
            col_name = headers_lower.index("name")
            col_cash = headers_lower.index("cash")
            col_upi  = headers_lower.index("upi")
            data_start = idx + 1
            print(f"  Header at row {idx+1}: room={col_room}, name={col_name}, cash={col_cash}, upi={col_upi}")
            break

    if col_cash is None:
        print("ERROR: could not find Cash/UPI columns in tab")
        return

    pending = []  # (tenancy_id, name_from_sheet, cash, upi)
    matched_names = set()

    for ri, row in enumerate(rows[data_start:], start=data_start + 1):
        if len(row) <= col_upi:
            continue
        raw_name = str(row[col_name]).strip()
        if not raw_name:
            continue
        name_lower = raw_name.lower()
        if name_lower not in KNOWN_TENANCY_IDS:
            continue

        cash = pn(row[col_cash])
        upi  = pn(row[col_upi])
        tenancy_id = KNOWN_TENANCY_IDS[name_lower]
        matched_names.add(name_lower)

        raw_room = str(row[col_room]).strip()
        print(f"  Found: '{raw_name}' (sheet room={raw_room}) → tenancy_id={tenancy_id}  cash={cash}  upi={upi}")
        pending.append((tenancy_id, raw_name, cash, upi))

    # Warn about any not found in sheet
    for name_lower in KNOWN_TENANCY_IDS:
        if name_lower not in matched_names:
            print(f"  WARN: '{name_lower}' NOT found in sheet tab — no payment row")

    total_cash = sum(p[2] for p in pending)
    total_upi  = sum(p[3] for p in pending)
    print(f"\n  Summary: {len(pending)} tenants, Cash=₹{total_cash:,.0f}, UPI=₹{total_upi:,.0f}, Total=₹{total_cash+total_upi:,.0f}")
    print(f"  Expected gap to fill: Cash=₹66,000  UPI=₹43,036  Total=₹1,09,036")

    if not write:
        print("\nDRY RUN complete. Run with --write to apply.")
        return

    # Confirm no existing March payments for these tenancy_ids (avoid double-insert)
    async with get_session() as s:
        from sqlalchemy import func
        existing = await s.execute(
            select(Payment.tenancy_id, func.sum(Payment.amount).label("amt"))
            .where(
                Payment.period_month == MARCH,
                Payment.for_type == PaymentFor.rent,
                Payment.is_void == False,
                Payment.tenancy_id.in_(list(KNOWN_TENANCY_IDS.values())),
            )
            .group_by(Payment.tenancy_id)
        )
        existing_rows = existing.all()
        if existing_rows:
            print("\nWARN: Some tenancy_ids already have March payments:")
            for row in existing_rows:
                print(f"  tenancy_id={row.tenancy_id}  existing_amt=₹{int(row.amt):,}")
            print("Aborting — fix manually if needed.")
            return

    async with get_session() as sw:
        await sw.execute(text("SET LOCAL app.allow_historical_write = 'true'"))
        inserted = 0
        for tenancy_id, raw_name, cash, upi in pending:
            if cash > 0:
                sw.add(Payment(
                    tenancy_id=tenancy_id,
                    amount=Decimal(str(cash)),
                    payment_date=MARCH,
                    payment_mode=PaymentMode.cash,
                    for_type=PaymentFor.rent,
                    period_month=MARCH,
                    notes=f"MARCH 2026 cash — name-matched fix (sheet room mismatch)",
                ))
                inserted += 1
            if upi > 0:
                sw.add(Payment(
                    tenancy_id=tenancy_id,
                    amount=Decimal(str(upi)),
                    payment_date=MARCH,
                    payment_mode=PaymentMode.upi,
                    for_type=PaymentFor.rent,
                    period_month=MARCH,
                    notes=f"MARCH 2026 UPI — name-matched fix (sheet room mismatch)",
                ))
                inserted += 1
        await sw.commit()
        print(f"\nInserted {inserted} payments for {len(pending)} tenants.")

    print("\nVerifying final March totals...")
    async with get_session() as s:
        rows_verify = (await s.execute(
            select(Payment.payment_mode, __import__('sqlalchemy').func.sum(Payment.amount).label("total"))
            .where(Payment.period_month == MARCH, Payment.is_void == False, Payment.for_type == PaymentFor.rent)
            .group_by(Payment.payment_mode)
        )).all()
        cash_total = upi_total = 0
        for r in rows_verify:
            mode = r.payment_mode.value if hasattr(r.payment_mode, "value") else str(r.payment_mode)
            amt = int(r.total or 0)
            print(f"  {mode}: ₹{amt:,}")
            if mode == "cash":
                cash_total = amt
            elif mode == "upi":
                upi_total = amt
        print(f"  Total: ₹{cash_total + upi_total:,}  (expected ₹39,83,413)")


if __name__ == "__main__":
    write = "--write" in sys.argv
    asyncio.run(main(write))
