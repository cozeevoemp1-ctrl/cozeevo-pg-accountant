"""
Backfill verified P&L cash expenses into cash_expenses table.
Sources: pnl_builder.py hardcoded figures (Nov 2025 – Apr 2026).

Only adds entries that don't already exist (safe to re-run).

Usage:
    python scripts/_backfill_cash_expenses.py          # dry run
    python scripts/_backfill_cash_expenses.py --write  # commit
"""
from __future__ import annotations
import asyncio, os, sys, argparse
from datetime import date
from decimal import Decimal
sys.path.insert(0, ".")
from dotenv import load_dotenv; load_dotenv()
from src.database.db_manager import init_db, get_session
from src.database.models import CashExpense
from sqlalchemy import select, text

# P&L months: index 0=placeholder, 1=Nov25, 2=Dec25, 3=Jan26, 4=Feb26, 5=Mar26, 6=Apr26
# Date = last day of each month (approximate payment date)
MONTHS = [
    None,
    date(2025, 11, 30),
    date(2025, 12, 31),
    date(2026, 1, 31),
    date(2026, 2, 28),
    date(2026, 3, 31),
    date(2026, 4, 30),
]

# Cash expenses extracted from pnl_builder.py — amounts per month index
# Format: (description, paid_by, [amounts per month index 0..6])
CASH_EXPENSES = [
    # Property rent paid in cash (Jan rent paid in Feb, Feb in Mar, Mar in Apr)
    ("Property Rent — cash payment",        "Operations",    [0, 0, 0, 0, 1532000, 1290000, 1449100]),
    # Kiran PhonePe/cash for PG ops (equity advance)
    ("Kiran advance — cash ops spend",      "Kiran",         [0, 39001, 51517, 32045, 654, 0, 0]),
    # Chandra personal cash for PG operations
    ("Chandra advance — cash ops spend",    "Chandra",       [0, 0, 0, 0, 0, 32789, 38111]),
    # Water — Manoj cash portion (from Water line, cash component)
    ("Water — Manoj cash payment",          "Operations",    [0, 0, 0, 8000, 0, 0, 84520]),
]


async def run(write: bool):
    db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL") or ""
    await init_db(db_url)
    async with get_session() as s:
        # Load existing entries to avoid duplicates
        existing = set()
        rows = (await s.execute(text(
            "SELECT date::text, description, amount::int FROM cash_expenses WHERE is_void = false"
        ))).all()
        for r in rows:
            existing.add((r.date, r.description, r.amount))

        to_add = []
        for desc, paid_by, amounts in CASH_EXPENSES:
            for idx, amount in enumerate(amounts):
                if idx == 0 or amount == 0:
                    continue
                pmt_date = MONTHS[idx]
                key = (str(pmt_date), desc, int(amount))
                if key in existing:
                    print(f"  SKIP (exists): {pmt_date}  {desc[:40]}  {amount:,}")
                    continue
                print(f"  ADD:           {pmt_date}  {desc[:40]}  {amount:,}")
                to_add.append(CashExpense(
                    date=pmt_date,
                    description=desc,
                    amount=Decimal(str(amount)),
                    paid_by=paid_by,
                    created_by="_backfill_cash_expenses.py",
                ))

        print(f"\nTotal to add: {len(to_add)}")
        if not to_add:
            print("Nothing to add.")
            return

        if write:
            for e in to_add:
                s.add(e)
            await s.commit()
            print("** COMMITTED **")
        else:
            print("** DRY RUN — no changes **")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.write))
