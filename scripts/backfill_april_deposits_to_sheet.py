"""
Backfill April 2026 deposit payments that are in DB but were never written
to the Google Sheet because the gsheets write-back crashed on period_month=None.

Booking payments are deliberately EXCLUDED — they are already subtracted from
the sheet's Rent Due column via first_month_rent_due(), so writing them to
Cash/UPI would double-count.

Run once:
    python scripts/backfill_april_deposits_to_sheet.py
    python scripts/backfill_april_deposits_to_sheet.py --dry-run
"""
import argparse
import asyncio
import sys
import os
import time
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import select
from src.database.db_manager import init_db, get_session
from src.database.models import Payment, PaymentFor, Tenancy, Tenant, Room
from src.integrations.gsheets import update_payment as gsheets_update

# IDs already written to sheet in the first partial run (2026-04-28).
# Skipping these prevents double-adding to Cash column.
_ALREADY_WRITTEN = {3496, 3468, 3404, 3510, 2881, 3448, 3503, 3487, 3165, 3194, 3490, 3475}


async def main(dry_run: bool) -> None:
    print(f"{'[DRY RUN] ' if dry_run else ''}Backfilling April 2026 deposit payments to Google Sheet...")

    db_url = os.environ.get("SUPABASE_DB_URL") or os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: SUPABASE_DB_URL or DATABASE_URL not set")
        sys.exit(1)
    await init_db(db_url)

    async with get_session() as session:
        rows = (await session.execute(
            select(Payment, Tenant, Room)
            .join(Tenancy, Tenancy.id == Payment.tenancy_id)
            .join(Tenant, Tenant.id == Tenancy.tenant_id)
            .join(Room, Room.id == Tenancy.room_id)
            .where(
                Payment.for_type == PaymentFor.deposit,
                Payment.payment_date >= date(2026, 4, 1),
                Payment.payment_date <= date(2026, 4, 30),
                Payment.is_void == False,
            )
            .order_by(Payment.payment_date, Room.room_number)
        )).all()

    total = 0
    skipped = 0
    for payment, tenant, room in rows:
        if payment.id in _ALREADY_WRITTEN:
            print(f"  SKIP  {room.room_number:6s} | {tenant.name:30s} | Rs.{int(payment.amount):,} (already written)")
            skipped += 1
            continue

        method = payment.payment_mode.value if hasattr(payment.payment_mode, "value") else str(payment.payment_mode)
        sheet_method = "cash" if method == "cash" else "upi"

        print(
            f"  Room  {room.room_number:6s} | {tenant.name:30s} | "
            f"Rs.{int(payment.amount):,} | {sheet_method} | {payment.payment_date}"
        )
        total += int(payment.amount)

        if not dry_run:
            result = await gsheets_update(
                room_number=room.room_number,
                tenant_name=tenant.name,
                amount=float(payment.amount),
                method=sheet_method,
                month=payment.payment_date.month,
                year=payment.payment_date.year,
                entered_by="backfill_script",
            )
            if result.get("success"):
                print(f"    -> written to sheet (row {result.get('row')}, tab {result.get('tab')})")
            else:
                print(f"    -> FAILED: {result.get('error') or result.get('warning')}")
            # Stay within Google Sheets read-quota (60 req/min per user)
            time.sleep(2)

    print(f"\nPending this run: {len(rows) - skipped} payments, Rs.{total:,}")
    print(f"Skipped (already written): {skipped}")
    if dry_run:
        print("Dry run complete — no sheet writes made.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.dry_run))
