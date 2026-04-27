"""
scripts/reload_pre_april_payments.py
=====================================
Drop all Dec 2025 – Mar 2026 rent payments from DB and reload from the
Cozeevo Operations v2 Google Sheet (the operational sheet, not Excel).

Usage:
    python scripts/reload_pre_april_payments.py          # dry run
    python scripts/reload_pre_april_payments.py --write  # commit to DB

SAFETY:
- Never touches April 2026 or later
- Never touches NULL period_month rows (deposits, bookings)
- Backup table payments_backup_20260427 must exist before running
"""
import asyncio
import os
import sys
from datetime import date
from decimal import Decimal

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

import gspread
from google.oauth2.service_account import Credentials
from sqlalchemy import select, delete, func

from src.database.db_manager import init_engine, get_session
from src.database.models import (
    Tenant, Tenancy, Room, Payment,
    PaymentMode, PaymentFor, TenancyStatus,
)

CREDENTIALS_PATH = "credentials/gsheets_service_account.json"
OPS_SHEET_ID = os.getenv("GSHEETS_SHEET_ID", "1Hp5dTM7TcDEq75jgHEjvwtBjOolruGfQ7CVMzVqjdGw")

APRIL = date(2026, 4, 1)

# Months to reload: (tab_name, period_month_date)
MONTHS = [
    ("DECEMBER 2025",  date(2025, 12, 1)),
    ("JANUARY 2026",   date(2026,  1, 1)),
    ("FEBRUARY 2026",  date(2026,  2, 1)),
    ("MARCH 2026",     date(2026,  3, 1)),
]

# Column names to look up in the header row (case-insensitive)
HEADER_ROOM = "room"
HEADER_NAME = "name"
HEADER_CASH = "cash"
HEADER_UPI  = "upi"


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
    print(f"Source: Cozeevo Operations v2 ({OPS_SHEET_ID})")
    print()

    # Safety: verify backup exists
    if write:
        init_engine(os.getenv("DATABASE_URL"))
        async with get_session() as s:
            from sqlalchemy import text
            backup_count = await s.scalar(
                text("SELECT COUNT(*) FROM payments_backup_20260427")
            )
            if not backup_count:
                print("ERROR: payments_backup_20260427 is empty or missing. Aborting.")
                return
            print(f"Backup confirmed: {backup_count} rows in payments_backup_20260427")
    else:
        init_engine(os.getenv("DATABASE_URL"))

    sh = _open_sheet()

    # Build room and tenancy indexes
    async with get_session() as s:
        room_rows = (await s.execute(select(Room))).scalars().all()
        by_room = {r.room_number.strip().upper(): r for r in room_rows}

        tenancy_rows = (await s.execute(
            select(Tenancy, Tenant, Room)
            .join(Tenant, Tenant.id == Tenancy.tenant_id)
            .join(Room, Room.id == Tenancy.room_id)
        )).all()

        # Index: (room_number_upper, name_lower) → tenancy_id
        tenancy_by_room_name: dict[tuple, int] = {}
        # Fallback: room_upper → [tenancy_ids] (for rooms with one tenant)
        tenancy_by_room: dict[str, list[int]] = {}

        for tenancy, tenant, room in tenancy_rows:
            key = (room.room_number.strip().upper(), tenant.name.strip().lower())
            tenancy_by_room_name[key] = tenancy.id
            tenancy_by_room.setdefault(room.room_number.strip().upper(), []).append(tenancy.id)

        grand_total = {"cash_rows": 0, "upi_rows": 0, "cash_amt": 0.0, "upi_amt": 0.0,
                       "skipped_no_match": 0, "deleted": 0}

        for tab_name, period in MONTHS:
            print(f"\n── {tab_name} ──")
            try:
                ws = sh.worksheet(tab_name)
            except Exception as e:
                print(f"  WARN: tab not found ({e}), skipping")
                continue

            rows = ws.get_all_values()
            print(f"  {len(rows)} rows in tab (including header)")

            month_cash = 0.0
            month_upi  = 0.0
            month_rows = 0
            skipped    = 0
            pending_payments = []

            # Find the header row (first row where col 0 == "room") and
            # resolve column indices by name — no hardcoding
            data_start = 1
            col_room = col_name = col_cash = col_upi = None
            for idx, row in enumerate(rows):
                headers_lower = [str(c).strip().lower() for c in row]
                if headers_lower[0] == HEADER_ROOM:
                    col_room = headers_lower.index(HEADER_ROOM)
                    col_name = headers_lower.index(HEADER_NAME)
                    col_cash = headers_lower.index(HEADER_CASH)
                    col_upi  = headers_lower.index(HEADER_UPI)
                    data_start = idx + 1
                    break

            if col_cash is None or col_upi is None:
                print(f"  ERROR: could not find Cash/UPI columns in tab — skipping")
                continue

            for ri, row in enumerate(rows[data_start:], start=data_start + 1):
                if len(row) <= col_upi:
                    continue
                raw_room = str(row[col_room]).strip()
                raw_name = str(row[col_name]).strip()
                if not raw_room or not raw_name:
                    continue

                cash = pn(row[col_cash])
                upi  = pn(row[col_upi])
                if cash == 0 and upi == 0:
                    continue

                # Normalize room number (strip .0, leading zeros)
                import re
                norm_room = re.sub(r'\.0+$', '', raw_room).strip().upper()

                # Match tenancy
                tenancy_id = tenancy_by_room_name.get((norm_room, raw_name.lower()))
                if not tenancy_id:
                    # Try fallback: room with single tenancy
                    candidates = tenancy_by_room.get(norm_room, [])
                    if len(candidates) == 1:
                        tenancy_id = candidates[0]
                    else:
                        print(f"  SKIP row {ri}: '{raw_name}' in '{raw_room}' — no tenancy match (cash={cash}, upi={upi})")
                        skipped += 1
                        continue

                if cash > 0:
                    pending_payments.append(Payment(
                        tenancy_id=tenancy_id,
                        amount=Decimal(str(cash)),
                        payment_date=period,
                        payment_mode=PaymentMode.cash,
                        for_type=PaymentFor.rent,
                        period_month=period,
                        notes=f"{tab_name} cash — reloaded from ops sheet",
                    ))
                    month_cash += cash
                if upi > 0:
                    pending_payments.append(Payment(
                        tenancy_id=tenancy_id,
                        amount=Decimal(str(upi)),
                        payment_date=period,
                        payment_mode=PaymentMode.upi,
                        for_type=PaymentFor.rent,
                        period_month=period,
                        notes=f"{tab_name} UPI — reloaded from ops sheet",
                    ))
                    month_upi += upi
                month_rows += 1

            cash_rows = sum(1 for p in pending_payments if p.payment_mode == PaymentMode.cash)
            upi_rows  = sum(1 for p in pending_payments if p.payment_mode == PaymentMode.upi)
            print(f"  Parsed: {month_rows} tenant rows, cash=₹{month_cash:,.0f} ({cash_rows} rows), upi=₹{month_upi:,.0f} ({upi_rows} rows), skipped={skipped}")

            if write:
                async with get_session() as sw:
                    # SAFETY CHECK: never touch April or later
                    if period >= APRIL:
                        raise RuntimeError(f"REFUSING: period {period} is April or later")

                    # Delete existing payments for this month (rent only, has period_month)
                    result = await sw.execute(
                        delete(Payment).where(
                            Payment.period_month == period,
                        ).returning(Payment.id)
                    )
                    deleted = len(result.fetchall())
                    print(f"  Deleted {deleted} existing payments for {tab_name}")
                    grand_total["deleted"] += deleted

                    for p in pending_payments:
                        sw.add(p)
                    await sw.commit()
                    print(f"  Inserted {len(pending_payments)} payments for {tab_name}")

            grand_total["cash_rows"]  += cash_rows
            grand_total["upi_rows"]   += upi_rows
            grand_total["cash_amt"]   += month_cash
            grand_total["upi_amt"]    += month_upi
            grand_total["skipped_no_match"] += skipped

    print("\n=== GRAND TOTAL ===")
    print(f"  Cash:    ₹{grand_total['cash_amt']:>12,.0f}  ({grand_total['cash_rows']} rows)")
    print(f"  UPI:     ₹{grand_total['upi_amt']:>12,.0f}  ({grand_total['upi_rows']} rows)")
    print(f"  Total:   ₹{grand_total['cash_amt'] + grand_total['upi_amt']:>12,.0f}")
    if write:
        print(f"  Deleted: {grand_total['deleted']} old payments")
        print(f"  Inserted: {grand_total['cash_rows'] + grand_total['upi_rows']} new payments")
    print(f"  Skipped (no match): {grand_total['skipped_no_match']}")
    if not write:
        print("\nDRY RUN complete. Run with --write to apply.")


if __name__ == "__main__":
    write = "--write" in sys.argv
    asyncio.run(main(write))
