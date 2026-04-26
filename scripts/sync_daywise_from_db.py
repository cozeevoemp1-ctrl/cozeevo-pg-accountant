"""
scripts/sync_daywise_from_db.py
================================
Regenerate the 'DAY WISE' Google Sheet tab from Tenancy(stay_type=daily).

Usage:
    python scripts/sync_daywise_from_db.py           # dry run
    python scripts/sync_daywise_from_db.py --write   # write to sheet
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8")
from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, selectinload

from src.database.models import Tenancy, StayType, TenancyStatus, PaymentMode, Room

DATABASE_URL = os.environ["DATABASE_URL"]
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

TAB_NAME = "DAY WISE"

# Columns mirror every field from the day-wise onboarding form + DB
# STANDARD: never reference columns by numeric index — always use C["Column Name"]
HEADERS = [
    # Identity
    "Room", "Name", "Phone", "Building", "Sharing",
    # Financial (receptionist-set)
    "Rent/Day", "Days", "Booking Amt", "Security Dep", "Maintenance",
    "Rent Due", "Cash", "UPI", "Total Paid", "Balance",
    # Status & dates
    "Status", "Check-in", "Checkout",
    # KYC (tenant-filled)
    "Gender", "Food Pref", "ID Type", "ID Number",
    "Emergency Contact", "Emergency Phone", "Email",
    # Admin
    "Notes", "Entered By",
]

# Semantic column lookup: C["Balance"] == 14, C["Status"] == 15, etc.
# Use this everywhere instead of magic numbers — immune to column reorder.
C = {h: i for i, h in enumerate(HEADERS)}


def col_letter(n: int) -> str:
    """Convert 1-based column number to sheet letter notation (A, Z, AA, AB…)."""
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


LAST_COL = col_letter(len(HEADERS))  # "AA" for 27 columns


async def main(args) -> None:
    engine = create_async_engine(DATABASE_URL, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as session:
        rows = (await session.execute(
            select(Tenancy)
            .options(
                selectinload(Tenancy.tenant),
                selectinload(Tenancy.room).selectinload(Room.property),
                selectinload(Tenancy.payments),
            )
            .where(Tenancy.stay_type == StayType.daily)
            .order_by(Tenancy.checkin_date.desc())
        )).scalars().all()

        print(f"DB daily tenancies: {len(rows)} rows")

        today = date.today()
        data_rows = []
        total_revenue = 0.0
        active_count = 0

        for t in rows:
            tenant = t.tenant
            room = t.room
            checkin  = t.checkin_date.strftime("%d/%m/%Y")  if t.checkin_date  else ""
            checkout = t.checkout_date.strftime("%d/%m/%Y") if t.checkout_date else ""

            # Inclusive day count: Apr 10 → Apr 30 = 21 days (both days count)
            if t.checkout_date and t.checkin_date:
                num_days = (t.checkout_date - t.checkin_date).days + 1
            else:
                num_days = 0

            daily_rate      = float(t.agreed_rent or 0)
            maintenance     = float(t.maintenance_fee or 0)
            booking_amount  = float(t.booking_amount or 0)
            security_dep    = float(t.security_deposit or 0)
            rent_due        = round(daily_rate * num_days + maintenance, 2)

            non_void  = [p for p in t.payments if not p.is_void]
            cash_paid = sum(float(p.amount or 0) for p in non_void if p.payment_mode == PaymentMode.cash)
            upi_paid  = sum(float(p.amount or 0) for p in non_void if p.payment_mode != PaymentMode.cash)
            total_paid = round(cash_paid + upi_paid, 2)
            balance    = round(rent_due - total_paid, 2)

            display_status = str(t.status.value if hasattr(t.status, "value") else t.status).upper()
            is_still_active = t.status == TenancyStatus.active and not (t.checkout_date and t.checkout_date < today)
            if not is_still_active and t.status == TenancyStatus.active:
                display_status = "EXIT"
            if is_still_active:
                active_count += 1
            total_revenue += total_paid

            phone     = tenant.phone if tenant else ""
            prop_name = (room.property.name if room and room.property else "") or ""
            building  = prop_name.replace("Cozeevo ", "").strip()
            sharing   = str(t.sharing_type.value if t.sharing_type else "Day-Stay")

            # Build row as dict keyed by column name — order is set by HEADERS at write time.
            # Adding a new column = add to HEADERS + add key here. No index arithmetic needed.
            row_dict = {
                "Room":              room.room_number if room else "",
                "Name":              tenant.name if tenant else "",
                "Phone":             f"'{phone}" if phone else "",
                "Building":          building,
                "Sharing":           sharing,
                "Rent/Day":          daily_rate,
                "Days":              num_days,
                "Booking Amt":       booking_amount,
                "Security Dep":      security_dep,
                "Maintenance":       maintenance,
                "Rent Due":          rent_due,
                "Cash":              round(cash_paid, 2),
                "UPI":               round(upi_paid, 2),
                "Total Paid":        total_paid,
                "Balance":           balance,
                "Status":            display_status,
                "Check-in":          checkin,
                "Checkout":          checkout,
                "Gender":            tenant.gender if tenant else "",
                "Food Pref":         tenant.food_preference if tenant else "",
                "ID Type":           tenant.id_proof_type if tenant else "",
                "ID Number":         tenant.id_proof_number if tenant else "",
                "Emergency Contact": tenant.emergency_contact_name if tenant else "",
                "Emergency Phone":   tenant.emergency_contact_phone if tenant else "",
                "Email":             tenant.email if tenant else "",
                "Notes":             t.notes or "",
                "Entered By":        t.entered_by or "",
            }
            # Convert to ordered list following HEADERS — this is the only place positional order matters
            data_rows.append([row_dict[h] for h in HEADERS])

        # Use C["ColumnName"] for all summary lookups — never magic numbers
        exited_count          = sum(1 for r in data_rows if r[C["Status"]] in ("EXIT", "EXITED"))
        total_pending_balance = sum(
            float(r[C["Balance"]] or 0) for r in data_rows if float(r[C["Balance"]] or 0) > 0
        )

        print(f"  Active today: {active_count} | Total revenue: Rs.{int(total_revenue):,} | Exits: {exited_count}")

        ncols = len(HEADERS)
        def pad(cells):
            return cells + [""] * (ncols - len(cells))

        summary_row = pad([
            "DAY WISE STAYS",
            f"Total: {len(rows)} guests",
            f"Active now: {active_count}",
            f"Exits: {exited_count}",
            f"Revenue: Rs.{int(total_revenue):,}",
            f"Pending balance: Rs.{int(total_pending_balance):,}",
        ])

        if not args.write:
            print("[DRY RUN] Not writing to sheet.")
            if data_rows:
                r = data_rows[0]
                print(f"  Sample row: {r[:6]}")
            return

        from src.integrations.gsheets import _get_worksheet_sync, _get_spreadsheet_sync
        import gspread

        try:
            ws = _get_worksheet_sync(TAB_NAME)
        except gspread.exceptions.WorksheetNotFound:
            ss = _get_spreadsheet_sync()
            ws = ss.add_worksheet(title=TAB_NAME, rows=500, cols=ncols)

        all_rows = [summary_row, HEADERS] + data_rows
        ws.clear()
        if all_rows:
            ws.update(values=all_rows, range_name="A1", value_input_option="USER_ENTERED")

        try:
            ws.format(f"A1:{LAST_COL}1", {
                "textFormat": {"bold": True, "fontSize": 12,
                               "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
                "backgroundColor": {"red": 0.12, "green": 0.18, "blue": 0.35},
            })
            ws.format(f"A2:{LAST_COL}2", {
                "textFormat": {"bold": True,
                               "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
                "backgroundColor": {"red": 0.20, "green": 0.24, "blue": 0.40},
                "horizontalAlignment": "CENTER",
            })
            ws.freeze(rows=2)
        except Exception as e:
            print(f"  [warn] formatting failed: {e}")

        print(f"Written {len(data_rows)} rows to '{TAB_NAME}' tab (+ 1 dashboard row).")

    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    asyncio.run(main(parser.parse_args()))
