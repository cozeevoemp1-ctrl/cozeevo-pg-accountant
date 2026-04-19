"""
scripts/sync_daywise_from_db.py
================================
Regenerate the 'DAY WISE' Google Sheet tab entirely from the DB
(daywise_stays table is source of truth).

Usage:
    python scripts/sync_daywise_from_db.py           # dry run
    python scripts/sync_daywise_from_db.py --write   # write to sheet
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8")
from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from src.database.models import DaywiseStay

DATABASE_URL = os.environ["DATABASE_URL"]
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

TAB_NAME = "DAY WISE"
HEADERS = [
    "Room", "Guest Name", "Phone", "Check-in", "Check-out", "Stay Period",
    "Days", "Daily Rate", "Booking Amt", "Total", "Maintenance",
    "Sharing", "Staff", "Status", "Comments",
]


def fmt_lakh(n):
    n = float(n or 0)
    return f"{n/100000:.2f}L" if abs(n) >= 100000 else f"{int(n):,}"


async def main(args):
    engine = create_async_engine(DATABASE_URL, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as session:
        rows = (await session.execute(
            select(DaywiseStay).order_by(DaywiseStay.checkin_date.desc(), DaywiseStay.id.desc())
        )).scalars().all()

        print(f"DB daywise_stays: {len(rows)} rows")

        data_rows = []
        total_revenue = 0.0
        total_days = 0
        active_guests = 0
        from datetime import date as _date
        today = _date.today()

        for r in rows:
            checkin = r.checkin_date.strftime("%Y-%m-%d") if r.checkin_date else ""
            checkout = r.checkout_date.strftime("%Y-%m-%d") if r.checkout_date else ""
            total = float(r.total_amount or 0)
            total_revenue += total
            total_days += int(r.num_days or 0)

            # Active = currently staying today (between checkin and checkout, not EXIT/CANCELLED)
            status = (r.status or "EXIT").upper()
            if (r.checkin_date and r.checkin_date <= today
                    and (not r.checkout_date or r.checkout_date >= today)
                    and status not in ("EXIT", "CANCELLED")):
                active_guests += 1

            data_rows.append([
                r.room_number or "",
                r.guest_name or "",
                r.phone or "",
                checkin,
                checkout,
                r.stay_period or "",
                r.num_days or "",
                float(r.daily_rate or 0) or "",
                float(r.booking_amount or 0) or "",
                total or "",
                float(r.maintenance or 0) or "",
                r.sharing or "",
                r.assigned_staff or "",
                status,
                r.comments or "",
            ])

        summary_row = [
            "DAY WISE STAYS",
            f"Total: {len(rows)} guests",
            f"Active now: {active_guests}",
            f"Guest-days: {total_days}",
            f"Revenue: {fmt_lakh(total_revenue)}",
            "", "", "", "", "", "", "", "", "", "",
        ]

        print(f"\n=== Summary ===")
        print(f"Total guests: {len(rows)}  Active today: {active_guests}")
        print(f"Guest-days: {total_days}  Revenue: {fmt_lakh(total_revenue)}")

        if not args.write:
            print(f"\n[DRY RUN] Would write {len(data_rows) + 2} rows to '{TAB_NAME}'")
            return

        from src.integrations.gsheets import _get_worksheet_sync
        ws = _get_worksheet_sync(TAB_NAME)
        all_rows = [summary_row, HEADERS] + data_rows
        for i, row in enumerate(all_rows):
            while len(row) < 15:
                all_rows[i] = list(row) + [""]

        ws.clear()
        ws.update(range_name="A1", values=all_rows, value_input_option="USER_ENTERED")

        try:
            ws.format("A1:O1", {"textFormat": {"bold": True, "fontSize": 13},
                                 "backgroundColor": {"red": 0.12, "green": 0.18, "blue": 0.35}})
            ws.format("A1:O1", {"textFormat": {"foregroundColor": {"red": 1, "green": 1, "blue": 1}}})
            ws.format("A2:O2", {"textFormat": {"bold": True},
                                 "backgroundColor": {"red": 0.20, "green": 0.24, "blue": 0.40},
                                 "horizontalAlignment": "CENTER"})
            ws.format("A2:O2", {"textFormat": {"foregroundColor": {"red": 1, "green": 1, "blue": 1}}})
            ws.freeze(rows=2)
        except Exception as e:
            print(f"  [warn] formatting failed: {e}")

        print(f"\n[ok] Wrote {len(all_rows)} rows to '{TAB_NAME}'")

    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sync DAY WISE tab from DB")
    parser.add_argument("--write", action="store_true", help="Actually write to Sheet")
    asyncio.run(main(parser.parse_args()))
