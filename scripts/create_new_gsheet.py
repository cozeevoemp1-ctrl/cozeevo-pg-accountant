"""
scripts/create_new_gsheet.py
=============================
Creates the redesigned 5-sheet Google Sheet and populates from Supabase DB.

Sheets:
  1. ROOMS        — L0 master data (from rooms table)
  2. TENANTS      — one row per tenant (from tenants + tenancies)
  3. PAYMENTS     — append-only ledger (from payments table)
  4. CHANGES LOG  — rent changes, room transfers, sharing changes
  5. DASHBOARD    — formulas only, zero manual entry

Usage:
  python scripts/create_new_gsheet.py                # dry run (print only)
  python scripts/create_new_gsheet.py --write         # create sheet + populate
  python scripts/create_new_gsheet.py --write --id SHEET_ID  # write to existing sheet
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import date, datetime
from decimal import Decimal

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

import gspread
from google.oauth2.service_account import Credentials
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from src.database.models import (
    Tenant, Tenancy, TenancyStatus, SharingType, StayType,
    Room, Payment, PaymentFor, PaymentMode, RentSchedule, RentStatus,
)

# ── Config ──────────────────────────────────────────────────────────────────────

DB_URL = os.getenv("DATABASE_URL", "")
CREDENTIALS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "credentials", "gsheets_service_account.json",
)
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


# ── Data loading ────────────────────────────────────────────────────────────────

async def load_rooms(session: AsyncSession) -> list[list]:
    """Load rooms for ROOMS sheet."""
    from sqlalchemy import text as sa_text
    rows = (await session.execute(sa_text(
        "SELECT room_number, property_id, floor, room_type, max_occupancy, is_staff_room, has_ac "
        "FROM rooms WHERE active = true ORDER BY property_id, floor, room_number"
    ))).all()

    data = []
    for r in rows:
        building = "THOR" if r.property_id == 1 else "HULK"
        data.append([
            r.room_number,
            building,
            r.floor or 0,
            str(r.room_type or ""),
            r.max_occupancy or 1,
            "Yes" if r.is_staff_room else "No",
            "Yes" if r.has_ac else "No",
        ])
    return data


async def load_tenants(session: AsyncSession) -> list[list]:
    """Load tenants for TENANTS sheet."""
    rows = (await session.execute(
        select(
            Tenant.name, Tenant.phone, Tenant.gender,
            Room.room_number, Room.property_id,
            Tenancy.agreed_rent, Tenancy.security_deposit,
            Tenancy.sharing_type, Tenancy.stay_type,
            Tenancy.checkin_date, Tenancy.status,
            Tenancy.checkout_date, Tenancy.notice_date,
            Tenancy.notes,
        )
        .join(Tenancy, Tenancy.tenant_id == Tenant.id)
        .join(Room, Room.id == Tenancy.room_id)
        .order_by(Room.property_id, Room.room_number, Tenant.name)
    )).all()

    data = []
    for r in rows:
        building = "THOR" if r.property_id == 1 else "HULK"
        sharing = r.sharing_type.value if r.sharing_type else ""
        stay = r.stay_type.value if r.stay_type else "monthly"
        data.append([
            r.name or "",
            r.phone or "",
            r.room_number or "",
            building,
            float(r.agreed_rent or 0),
            float(r.security_deposit or 0),
            sharing,
            stay,
            str(r.checkin_date) if r.checkin_date else "",
            r.status.value if r.status else "",
            str(r.checkout_date) if r.checkout_date else "",
            str(r.notice_date) if r.notice_date else "",
            r.gender or "",
            r.notes or "",
        ])
    return data


async def load_payments(session: AsyncSession) -> list[list]:
    """Load payments for PAYMENTS sheet."""
    rows = (await session.execute(
        select(
            Payment.payment_date, Tenant.name, Room.room_number,
            Payment.amount, Payment.payment_mode, Payment.period_month,
            Payment.for_type, Payment.notes,
        )
        .join(Tenancy, Tenancy.id == Payment.tenancy_id)
        .join(Tenant, Tenant.id == Tenancy.tenant_id)
        .join(Room, Room.id == Tenancy.room_id)
        .where(Payment.is_void == False)
        .order_by(Payment.payment_date.desc(), Tenant.name)
    )).all()

    data = []
    for r in rows:
        month_str = r.period_month.strftime("%b %Y") if r.period_month else ""
        mode = r.payment_mode.value if r.payment_mode else ""
        for_type = r.for_type.value if r.for_type else "rent"
        data.append([
            str(r.payment_date) if r.payment_date else "",
            r.name or "",
            r.room_number or "",
            float(r.amount or 0),
            mode.upper(),
            month_str,
            for_type.capitalize(),
            "",  # Received By (not in DB currently)
            r.notes or "",
        ])
    return data


async def load_all():
    """Load all data from DB."""
    engine = create_async_engine(DB_URL)
    S = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with S() as session:
        rooms = await load_rooms(session)
        tenants = await load_tenants(session)
        payments = await load_payments(session)
    await engine.dispose()
    return rooms, tenants, payments


# ── Sheet creation ──────────────────────────────────────────────────────────────

ROOMS_HEADERS = ["Room", "Building", "Floor", "Type", "Max Beds", "Staff Room", "AC"]
TENANTS_HEADERS = [
    "Name", "Phone", "Room", "Building", "Rent", "Deposit",
    "Sharing", "Stay Type", "Check-in", "Status", "Checkout Date",
    "Notice Date", "Gender", "Notes",
]
PAYMENTS_HEADERS = [
    "Date", "Tenant", "Room", "Amount", "Mode", "For Month",
    "Type", "Received By", "Notes",
]
CHANGES_HEADERS = [
    "Date", "Tenant", "Room", "Change", "Old Value", "New Value", "Notes",
]


def create_sheet(gc: gspread.Client, rooms, tenants, payments, sheet_id=None):
    """Create or update the redesigned Google Sheet."""

    if sheet_id:
        spreadsheet = gc.open_by_key(sheet_id)
        print(f"Opened existing sheet: {spreadsheet.title}")
    else:
        spreadsheet = gc.create("Cozeevo Operations — Redesigned")
        spreadsheet.share(None, perm_type="anyone", role="writer")
        print(f"Created new sheet: {spreadsheet.url}")

    # ── 1. ROOMS sheet ──────────────────────────────────────────────────────
    try:
        ws_rooms = spreadsheet.worksheet("ROOMS")
        ws_rooms.clear()
    except gspread.WorksheetNotFound:
        ws_rooms = spreadsheet.add_worksheet("ROOMS", rows=200, cols=10)

    ws_rooms.update(values=[ROOMS_HEADERS] + rooms, range_name="A1")
    ws_rooms.format("A1:G1", {"textFormat": {"bold": True}, "backgroundColor": {"red": 0.9, "green": 0.95, "blue": 1.0}})
    ws_rooms.freeze(rows=1)
    print(f"  ROOMS: {len(rooms)} rows")

    # ── 2. TENANTS sheet ────────────────────────────────────────────────────
    try:
        ws_tenants = spreadsheet.worksheet("TENANTS")
        ws_tenants.clear()
    except gspread.WorksheetNotFound:
        ws_tenants = spreadsheet.add_worksheet("TENANTS", rows=400, cols=20)

    ws_tenants.update(values=[TENANTS_HEADERS] + tenants, range_name="A1")
    ws_tenants.format("A1:N1", {"textFormat": {"bold": True}, "backgroundColor": {"red": 0.95, "green": 1.0, "blue": 0.9}})
    ws_tenants.freeze(rows=1)
    # Conditional formatting: green for active, red for exited, orange for no_show
    print(f"  TENANTS: {len(tenants)} rows")

    # ── 3. PAYMENTS sheet ───────────────────────────────────────────────────
    try:
        ws_payments = spreadsheet.worksheet("PAYMENTS")
        ws_payments.clear()
    except gspread.WorksheetNotFound:
        ws_payments = spreadsheet.add_worksheet("PAYMENTS", rows=1000, cols=12)

    ws_payments.update(values=[PAYMENTS_HEADERS] + payments, range_name="A1")
    ws_payments.format("A1:I1", {"textFormat": {"bold": True}, "backgroundColor": {"red": 1.0, "green": 0.95, "blue": 0.9}})
    ws_payments.freeze(rows=1)
    print(f"  PAYMENTS: {len(payments)} rows")

    # ── 4. CHANGES LOG sheet ────────────────────────────────────────────────
    try:
        ws_changes = spreadsheet.worksheet("CHANGES LOG")
        ws_changes.clear()
    except gspread.WorksheetNotFound:
        ws_changes = spreadsheet.add_worksheet("CHANGES LOG", rows=200, cols=10)

    ws_changes.update(values=[CHANGES_HEADERS], range_name="A1")
    ws_changes.format("A1:G1", {"textFormat": {"bold": True}, "backgroundColor": {"red": 1.0, "green": 0.9, "blue": 0.95}})
    ws_changes.freeze(rows=1)
    print(f"  CHANGES LOG: empty (ready for use)")

    # ── 5. DASHBOARD sheet ──────────────────────────────────────────────────
    # Force refresh worksheet list to avoid stale cache
    spreadsheet.fetch_sheet_metadata()
    ws_dash = None
    for ws in spreadsheet.worksheets():
        if ws.title == "DASHBOARD":
            ws_dash = ws
            ws_dash.clear()
            break
    if ws_dash is None:
        ws_dash = spreadsheet.add_worksheet("DASHBOARD", rows=50, cols=10)

    # Build dashboard with formulas
    dashboard_data = [
        ["COZEEVO OPERATIONS DASHBOARD", "", "", ""],
        ["", "", "", ""],
        ["Pick Month (YYYY-MM-DD):", "2026-03-01", "", ""],
        ["", "", "", ""],
        # ── Occupancy Section ──
        ["OCCUPANCY", "", "Count", ""],
        ["Total Revenue Beds", "", "=SUMPRODUCT((ROOMS!F2:F200=\"No\")*(ROOMS!E2:E200))", ""],
        ["Active Tenants", "", "=COUNTIFS(TENANTS!J2:J400,\"active\")", ""],
        ["Premium Tenants", "", "=COUNTIFS(TENANTS!J2:J400,\"active\",TENANTS!G2:G400,\"premium\")", ""],
        ["Beds Occupied", "", "=C7-C8+C8*2", "(regular + premium x2)"],
        ["No-show (booked)", "", "=COUNTIFS(TENANTS!J2:J400,\"no_show\")", ""],
        ["Vacant Beds", "", "=C6-C9-C10", ""],
        ["Occupancy %", "", "=IF(C6>0,ROUND(C9/C6*100,1),0)", ""],
        ["", "", "", ""],
        ["New Check-ins This Month", "", "=COUNTIFS(TENANTS!I2:I400,\">=\"&B3,TENANTS!I2:I400,\"<\"&EDATE(B3,1))", ""],
        ["Exits This Month", "", "=COUNTIFS(TENANTS!K2:K400,\">=\"&B3,TENANTS!K2:K400,\"<\"&EDATE(B3,1))", ""],
        ["", "", "", ""],
        # ── Collections Section ──
        ["COLLECTIONS", "", "Amount", ""],
        ["Total Collected (month)", "", "=SUMPRODUCT((PAYMENTS!F2:F1000=TEXT(B3,\"MMM YYYY\"))*(PAYMENTS!G2:G1000=\"Rent\")*(PAYMENTS!D2:D1000))", ""],
        ["Cash", "", "=SUMPRODUCT((PAYMENTS!F2:F1000=TEXT(B3,\"MMM YYYY\"))*(PAYMENTS!G2:G1000=\"Rent\")*(PAYMENTS!E2:E1000=\"CASH\")*(PAYMENTS!D2:D1000))", ""],
        ["UPI", "", "=SUMPRODUCT((PAYMENTS!F2:F1000=TEXT(B3,\"MMM YYYY\"))*(PAYMENTS!G2:G1000=\"Rent\")*(PAYMENTS!E2:E1000=\"UPI\")*(PAYMENTS!D2:D1000))", ""],
        ["", "", "", ""],
        # ── Who Hasn't Paid Section ──
        ["WHO HASN'T PAID?", "", "", ""],
        ["(Check TENANTS sheet: active tenants with no payment row for this month in PAYMENTS)", "", "", ""],
        ["", "", "", ""],
        # ── Quick Stats ──
        ["QUICK STATS", "", "", ""],
        ["Total Tenants (all time)", "", "=COUNTA(TENANTS!A2:A400)", ""],
        ["Total Payments Logged", "", "=COUNTA(PAYMENTS!A2:A1000)", ""],
        ["Total Rent Collected (all)", "", "=SUMPRODUCT((PAYMENTS!G2:G1000=\"Rent\")*(PAYMENTS!D2:D1000))", ""],
    ]

    ws_dash.update(values=dashboard_data, range_name="A1", value_input_option="USER_ENTERED")
    ws_dash.format("A1:D1", {"textFormat": {"bold": True, "fontSize": 14}})
    ws_dash.format("A5:D5", {"textFormat": {"bold": True}, "backgroundColor": {"red": 0.85, "green": 0.92, "blue": 1.0}})
    ws_dash.format("A17:D17", {"textFormat": {"bold": True}, "backgroundColor": {"red": 0.85, "green": 1.0, "blue": 0.85}})
    ws_dash.format("A25:D25", {"textFormat": {"bold": True}, "backgroundColor": {"red": 1.0, "green": 0.95, "blue": 0.85}})
    ws_dash.freeze(rows=0)
    print(f"  DASHBOARD: formulas set")

    # ── Remove default Sheet1 if exists ─────────────────────────────────────
    try:
        default = spreadsheet.worksheet("Sheet1")
        spreadsheet.del_worksheet(default)
    except gspread.WorksheetNotFound:
        pass

    return spreadsheet.url


# ── Main ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Create redesigned Cozeevo Google Sheet")
    parser.add_argument("--write", action="store_true", help="Actually create/update the sheet")
    parser.add_argument("--id", type=str, default=None, help="Existing sheet ID to update")
    args = parser.parse_args()

    print("Loading data from Supabase...")
    rooms, tenants, payments = asyncio.run(load_all())
    print(f"  Rooms: {len(rooms)}")
    print(f"  Tenants: {len(tenants)}")
    print(f"  Payments: {len(payments)}")

    if not args.write:
        print("\nDry run. Use --write to create the sheet.")
        print("\nSample TENANTS (first 5):")
        for row in tenants[:5]:
            print(f"  {row[0]:25s} {row[2]:6s} {row[3]:5s} Rs.{row[4]:,.0f} {row[6]:8s} {row[8]:12s} {row[9]}")
        print("\nSample PAYMENTS (first 5):")
        for row in payments[:5]:
            print(f"  {row[0]:12s} {row[1]:25s} {row[2]:6s} Rs.{row[3]:,.0f} {row[4]:5s} {row[5]}")
        return

    print("\nAuthenticating with Google...")
    creds = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=SCOPES)
    gc = gspread.authorize(creds)

    print("Creating sheet...")
    url = create_sheet(gc, rooms, tenants, payments, sheet_id=args.id)
    print(f"\nDone! Sheet URL: {url}")


if __name__ == "__main__":
    main()
