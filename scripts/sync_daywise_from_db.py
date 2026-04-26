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

from src.database.models import Tenancy, StayType, TenancyStatus, PaymentMode

DATABASE_URL = os.environ["DATABASE_URL"]
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

TAB_NAME = "DAY WISE"
MONTHLY_HEADERS = [
    "Room", "Name", "Phone", "Building", "Sharing",
    "Rent", "Deposit", "Rent Due", "Cash", "UPI",
    "Total Paid", "Balance", "Status", "Check-in",
    "Notice Date", "Event", "Notes", "Prev Due", "Entered By",
]


async def main(args) -> None:
    engine = create_async_engine(DATABASE_URL, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as session:
        rows = (await session.execute(
            select(Tenancy)
            .options(
                selectinload(Tenancy.tenant),
                selectinload(Tenancy.room),
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
            checkin = t.checkin_date.strftime("%d/%m/%Y") if t.checkin_date else ""
            checkout = t.checkout_date.strftime("%d/%m/%Y") if t.checkout_date else ""
            num_days = max(1, (t.checkout_date - t.checkin_date).days) if (t.checkout_date and t.checkin_date) else 0
            daily_rate = float(t.agreed_rent or 0)
            maintenance = float(t.maintenance_fee or 0)
            booking_amount = float(t.booking_amount or 0)
            rent_due = round(daily_rate * num_days + maintenance, 2)

            non_void = [p for p in t.payments if not p.is_void]
            cash_paid = sum(float(p.amount or 0) for p in non_void if p.payment_mode == PaymentMode.cash)
            upi_paid = sum(float(p.amount or 0) for p in non_void if p.payment_mode != PaymentMode.cash)
            total_paid = round(cash_paid + upi_paid, 2)
            balance = round(rent_due - total_paid, 2)

            display_status = str(t.status.value if hasattr(t.status, "value") else t.status).upper()
            if t.status == TenancyStatus.active and t.checkout_date and t.checkout_date < today:
                display_status = "EXIT"
            if t.status == TenancyStatus.active:
                active_count += 1
            total_revenue += total_paid

            phone = tenant.phone if tenant else ""
            data_rows.append([
                room.room_number if room else "",
                tenant.name if tenant else "",
                f"'{phone}" if phone else "",
                "",                                     # Building (Room has no building field)
                str(t.sharing_type.value if t.sharing_type else ""),
                daily_rate,
                booking_amount,
                rent_due,
                round(cash_paid, 2),
                round(upi_paid, 2),
                total_paid,
                balance,
                display_status,
                checkin,
                "",
                f"checkout: {checkout}" if checkout else "",
                t.notes or "",
                "",
                t.entered_by or "",
            ])

        exited_count = sum(1 for r in data_rows if r[12] in ("EXIT", "EXITED"))
        total_pending_balance = sum(float(r[11] or 0) for r in data_rows if float(r[11] or 0) > 0)

        print(f"  Active today: {active_count} | Total revenue: Rs.{int(total_revenue):,} | Exits: {exited_count}")

        ncols = len(MONTHLY_HEADERS)
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
                print(f"  Sample row: {r[:4]}")
            return

        from src.integrations.gsheets import _get_worksheet_sync, _get_spreadsheet_sync
        import gspread

        try:
            ws = _get_worksheet_sync(TAB_NAME)
        except gspread.exceptions.WorksheetNotFound:
            ss = _get_spreadsheet_sync()
            ws = ss.add_worksheet(title=TAB_NAME, rows=500, cols=ncols)

        all_rows = [summary_row, MONTHLY_HEADERS] + data_rows
        ws.clear()
        if all_rows:
            ws.update(values=all_rows, range_name="A1", value_input_option="USER_ENTERED")

        try:
            ws.format(f"A1:S1", {
                "textFormat": {"bold": True, "fontSize": 12,
                               "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
                "backgroundColor": {"red": 0.12, "green": 0.18, "blue": 0.35},
            })
            ws.format(f"A2:S2", {
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
