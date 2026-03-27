"""Rebuild all Google Sheets with flat data + COLLECT RENT with VLOOKUP."""
import asyncio
import os
import sys
from datetime import date, datetime
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

import gspread
from google.oauth2.service_account import Credentials
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from src.database.models import (
    Tenant, Tenancy, TenancyStatus, SharingType,
    Room, Payment, PaymentFor, PaymentMode, RentSchedule,
)

DB_URL = os.getenv("DATABASE_URL", "")
CREDS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "credentials", "gsheets_service_account.json")
SHEET_ID = "1Hp5dTM7TcDEq75jgHEjvwtBjOolruGfQ7CVMzVqjdGw"


async def build_monthly(session, month_date):
    """Per-tenant rent view for a month."""
    tenants = (await session.execute(
        select(
            Tenant.name, Room.room_number, Room.property_id,
            Tenancy.agreed_rent, Tenancy.sharing_type, Tenancy.checkin_date,
            Tenancy.id.label("tenancy_id"),
        )
        .join(Tenancy, Tenancy.tenant_id == Tenant.id)
        .join(Room, Room.id == Tenancy.room_id)
        .where(Tenancy.status == TenancyStatus.active)
        .order_by(Room.property_id, Room.room_number, Tenant.name)
    )).all()

    rows = []
    for t in tenants:
        bld = "THOR" if t.property_id == 1 else "HULK"
        rent = float(t.agreed_rent or 0)
        sharing = t.sharing_type.value if t.sharing_type else ""

        cash = float(await session.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0))
            .where(Payment.tenancy_id == t.tenancy_id,
                   Payment.period_month == month_date,
                   Payment.for_type == PaymentFor.rent,
                   Payment.is_void == False,
                   Payment.payment_mode == PaymentMode.cash)
        ) or 0)

        upi = float(await session.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0))
            .where(Payment.tenancy_id == t.tenancy_id,
                   Payment.period_month == month_date,
                   Payment.for_type == PaymentFor.rent,
                   Payment.is_void == False,
                   Payment.payment_mode == PaymentMode.upi)
        ) or 0)

        total = cash + upi
        balance = rent - total
        status = "PAID" if balance <= 0 else ("PARTIAL" if total > 0 else "UNPAID")
        rows.append([t.name, t.room_number, bld, sharing, rent, cash, upi, total, balance, status])
    return rows


async def build_lookup(session):
    """Active tenant lookup: room -> name, building, sharing, rent."""
    rows = (await session.execute(
        select(Room.room_number, Tenant.name, Room.property_id,
               Tenancy.sharing_type, Tenancy.agreed_rent)
        .join(Tenancy, Tenancy.tenant_id == Tenant.id)
        .join(Room, Room.id == Tenancy.room_id)
        .where(Tenancy.status == TenancyStatus.active)
        .order_by(Room.room_number, Tenant.name)
    )).all()
    return [[r.room_number, r.name, "THOR" if r.property_id == 1 else "HULK",
             r.sharing_type.value if r.sharing_type else "", float(r.agreed_rent or 0)]
            for r in rows]


async def count_noshow(session):
    return await session.scalar(
        select(func.count()).where(Tenancy.status == TenancyStatus.no_show)
    ) or 0


def get_or_create(sp, name, rows=300, cols=12):
    try:
        ws = sp.worksheet(name)
        ws.clear()
    except gspread.WorksheetNotFound:
        ws = sp.add_worksheet(name, rows=rows, cols=cols)
    return ws


def write_monthly_sheet(sp, name, month_label, data):
    ws = get_or_create(sp, name)
    tr = sum(r[4] for r in data)
    tc = sum(r[7] for r in data)
    cash_total = sum(r[5] for r in data)
    upi_total = sum(r[6] for r in data)

    header = [
        [f"MONTHLY RENT TRACKER \u2014 {month_label}", "", "", "", "", "", "", "", "", ""],
        ["", "", "", "", "Rent Expected", "Cash", "UPI", "Total Collected", "Outstanding", ""],
        ["", "", "", "", tr, cash_total, upi_total, tc, tr - tc, ""],
        ["Name", "Room", "Building", "Sharing", "Rent Due", "Cash Paid", "UPI Paid", "Total Paid", "Balance", "Status"],
    ]
    ws.update(values=header + data, range_name="A1", value_input_option="USER_ENTERED")
    ws.format("A1:J1", {"textFormat": {"bold": True, "fontSize": 13}})
    ws.format("A2:J3", {"textFormat": {"bold": True}, "numberFormat": {"type": "NUMBER", "pattern": "#,##0"}})
    ws.format("A4:J4", {"textFormat": {"bold": True}, "backgroundColor": {"red": 0.85, "green": 0.9, "blue": 1.0}})
    ws.freeze(rows=4)
    try:
        ws.set_basic_filter(f"A4:J{4 + len(data)}")
    except Exception:
        pass
    print(f"  {name}: {len(data)} rows")
    return tr, tc


def write_collect_rent(sp, lookup):
    ws = get_or_create(sp, "COLLECT RENT")
    today = datetime.now().strftime("%Y-%m-%d")

    header = [
        ["COLLECT RENT \u2014 Enter room, rest auto-fills", "", "", "", "", "", "", "", "", ""],
        ["Instructions: Type room number in col B. Name + rent auto-fill. Enter amount + mode.", "", "", "", "", "", "", "", "", ""],
        ["Date", "Room", "Tenant Name", "Building", "Rent Due", "Amount Paid", "Mode (CASH/UPI)", "For Month", "Received By", "Notes"],
    ]

    # 50 rows with VLOOKUP formulas
    formula_rows = []
    for i in range(4, 54):
        formula_rows.append([
            today,
            "",  # Room (manual)
            f"=IF(B{i}=\"\",\"\",IFERROR(VLOOKUP(B{i},'_LOOKUP'!A:B,2,FALSE),\"not found\"))",
            f"=IF(B{i}=\"\",\"\",IFERROR(VLOOKUP(B{i},'_LOOKUP'!A:C,3,FALSE),\"\"))",
            f"=IF(B{i}=\"\",\"\",IFERROR(VLOOKUP(B{i},'_LOOKUP'!A:E,5,FALSE),\"\"))",
            "",  # Amount (manual)
            "",  # Mode (manual)
            "Mar 2026",
            "",  # Received By (manual)
            "",  # Notes (manual)
        ])

    ws.update(values=header + formula_rows, range_name="A1", value_input_option="USER_ENTERED")
    ws.format("A1:J1", {"textFormat": {"bold": True, "fontSize": 13}})
    ws.format("A2:J2", {"textFormat": {"italic": True, "fontSize": 9},
                         "backgroundColor": {"red": 1.0, "green": 1.0, "blue": 0.85}})
    ws.format("A3:J3", {"textFormat": {"bold": True},
                         "backgroundColor": {"red": 1.0, "green": 0.92, "blue": 0.85}})
    ws.freeze(rows=3)

    print("  COLLECT RENT: 50 rows with VLOOKUP (enter room -> auto-fill)")


def write_dashboard(sp, mar_data, noshow):
    ws = get_or_create(sp, "DASHBOARD", rows=30, cols=5)
    tr = sum(r[4] for r in mar_data)
    tc = sum(r[7] for r in mar_data)
    cash_t = sum(r[5] for r in mar_data)
    upi_t = sum(r[6] for r in mar_data)
    premium = sum(1 for r in mar_data if r[3] == "premium")
    regular = len(mar_data) - premium
    beds = regular + premium * 2
    vacant = 291 - beds - noshow
    occ_pct = round(beds / 291 * 100, 1) if 291 > 0 else 0
    coll_pct = round(tc / tr * 100, 1) if tr > 0 else 0

    data = [
        ["COZEEVO OPERATIONS DASHBOARD", "", ""],
        ["March 2026", "", ""],
        ["", "", ""],
        ["OCCUPANCY", "", ""],
        ["Total Revenue Beds", 291, ""],
        ["Checked-in Beds", beds, f"({regular} regular + {premium} premium)"],
        ["No-show", noshow, ""],
        ["Vacant", vacant, ""],
        ["Occupancy %", f"{occ_pct}%", ""],
        ["", "", ""],
        ["COLLECTIONS", "", ""],
        ["Rent Expected", tr, ""],
        ["Total Collected", tc, ""],
        ["  Cash", cash_t, ""],
        ["  UPI", upi_t, ""],
        ["Outstanding", tr - tc, ""],
        ["Collection %", f"{coll_pct}%", ""],
        ["", "", ""],
        ["PAYMENT STATUS", "", ""],
        ["Fully Paid", sum(1 for r in mar_data if r[9] == "PAID"), ""],
        ["Partial", sum(1 for r in mar_data if r[9] == "PARTIAL"), ""],
        ["Unpaid", sum(1 for r in mar_data if r[9] == "UNPAID"), ""],
        ["", "", ""],
        ["OTHER MONTHS", "", ""],
        ["See tabs: MONTHLY JAN 2026, MONTHLY FEB 2026", "", ""],
        ["COLLECT RENT tab: log new payments", "", ""],
    ]

    ws.update(values=data, range_name="A1", value_input_option="USER_ENTERED")
    ws.format("A1:C1", {"textFormat": {"bold": True, "fontSize": 14}})
    ws.format("A2:C2", {"textFormat": {"bold": True, "fontSize": 12},
                         "backgroundColor": {"red": 1.0, "green": 0.98, "blue": 0.8}})
    ws.format("A4:C4", {"textFormat": {"bold": True},
                         "backgroundColor": {"red": 0.85, "green": 0.92, "blue": 1.0}})
    ws.format("A11:C11", {"textFormat": {"bold": True},
                           "backgroundColor": {"red": 0.85, "green": 1.0, "blue": 0.85}})
    ws.format("A19:C19", {"textFormat": {"bold": True},
                           "backgroundColor": {"red": 1.0, "green": 0.95, "blue": 0.85}})
    ws.format("B5:B9", {"numberFormat": {"type": "NUMBER", "pattern": "#,##0"}})
    ws.format("B12:B16", {"numberFormat": {"type": "NUMBER", "pattern": "#,##0"}})
    print("  DASHBOARD: rebuilt (no formulas, no errors)")


async def main():
    print("Loading data from DB...")
    engine = create_async_engine(DB_URL)
    S = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with S() as session:
        monthly = {}
        for m in [1, 2, 3]:
            md = date(2026, m, 1)
            label = md.strftime("%b %Y")
            monthly[label] = await build_monthly(session, md)
            print(f"  {label}: {len(monthly[label])} tenants")

        lookup = await build_lookup(session)
        print(f"  Lookup: {len(lookup)} active tenants")

        noshow = await count_noshow(session)
        print(f"  No-show: {noshow}")

    await engine.dispose()

    print("\nWriting to Google Sheets...")
    creds = Credentials.from_service_account_file(CREDS,
        scopes=["https://www.googleapis.com/auth/spreadsheets"])
    gc = gspread.authorize(creds)
    sp = gc.open_by_key(SHEET_ID)

    # Monthly views
    write_monthly_sheet(sp, "MONTHLY VIEW", "Mar 2026", monthly["Mar 2026"])
    write_monthly_sheet(sp, "MONTHLY JAN 2026", "Jan 2026", monthly["Jan 2026"])
    write_monthly_sheet(sp, "MONTHLY FEB 2026", "Feb 2026", monthly["Feb 2026"])

    # Lookup (helper for COLLECT RENT)
    ws_lookup = get_or_create(sp, "_LOOKUP")
    ws_lookup.update(values=[["Room", "Tenant", "Building", "Sharing", "Rent"]] + lookup,
                     range_name="A1", value_input_option="USER_ENTERED")
    print(f"  _LOOKUP: {len(lookup)} rows")

    # Collect Rent
    write_collect_rent(sp, lookup)

    # Dashboard
    write_dashboard(sp, monthly["Mar 2026"], noshow)

    print("\nDone! Open your sheet and check all tabs.")


if __name__ == "__main__":
    asyncio.run(main())
