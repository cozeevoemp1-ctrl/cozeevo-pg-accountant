"""
scripts/_import_investment_sbi.py
Import Investment.xlsx (Lakshmi SBI account) into bank_transactions.

These are direct SBI-to-vendor payments that never went through THOR/HULK Yes Bank,
so they are NOT in the existing P&L.

Skip:
  - Capital transfers to Cozeevo (Oct capital injections — already in Capital Contributions)
  - SBI→Cozeevo transfers (Nov ₹82K gym cheque, Dec ₹13K — already captured in THOR CSV)
  - Small test transactions (≤₹100 from test payees)
  - Chandra sekhar→Lakshmi SBI credits (incoming, not our spending)

Run: venv/Scripts/python scripts/_import_investment_sbi.py [--write]
"""
from __future__ import annotations

import asyncio
import hashlib
import sys
from datetime import datetime

import openpyxl
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, ".")
from src.rules.pnl_classify import classify_txn

DB = "postgresql+asyncpg://postgres:Anchorstrong123!@db.oxiqomoilqwfxjauxhzp.supabase.co:5432/postgres"
WRITE = "--write" in sys.argv

# Rows to explicitly skip (To = Cozeevo = capital transfer already counted)
SKIP_TO = {"cozeevo"}
# Payees that are incoming credits (chandra sekhar → lakshmi, rent collection not our spend)
SKIP_FROM_CREDITS = {"chandra sekhar"}

# Small test amounts from non-vendor payees
TEST_PAYEES = {"prabhakaran", "kiran", "9444296681@ptye"}


def make_hash(date_val, amount: float, description: str) -> str:
    raw = f"LAKSHMI_SBI|{date_val}|{amount}|{description}"
    return hashlib.sha256(raw.encode()).hexdigest()


def parse_rows():
    wb = openpyxl.load_workbook("Investment.xlsx", data_only=True)
    ws = wb.active

    expenses = []
    incomes = []

    for row in ws.iter_rows(min_row=3, values_only=True):
        txn_date = row[0]
        from_who = (row[1] or "").strip()
        to_who = (row[2] or "").strip()
        purpose = (row[3] or "").strip()
        txn_id = str(row[4] or "").strip()
        raw_amount = row[5]
        raw_refund = row[6]

        if not isinstance(txn_date, datetime):
            continue

        from_lower = from_who.lower()
        to_lower = to_who.lower()

        # Skip capital transfers to Cozeevo
        if to_lower in SKIP_TO:
            continue

        # Skip Chandra credits and other incoming
        if from_lower in SKIP_FROM_CREDITS:
            continue

        # Handle expense rows
        if isinstance(raw_amount, (int, float)) and raw_amount > 0:
            # Skip small test transactions from known test payees
            if raw_amount <= 100 and from_lower in TEST_PAYEES:
                continue

            description = f"{to_who} — {purpose}" if purpose else to_who
            cat, sub = classify_txn(description, "expense")

            expenses.append({
                "txn_date": txn_date.date(),
                "description": description,
                "amount": float(raw_amount),
                "txn_type": "expense",
                "category": cat,
                "sub_category": sub,
                "upi_reference": txn_id if txn_id else None,
                "account_name": "LAKSHMI_SBI",
                "unique_hash": make_hash(txn_date.date(), raw_amount, description),
            })

        # Handle income/refund rows (numeric refund, no expense amount)
        if isinstance(raw_refund, (int, float)) and raw_refund > 0 and not isinstance(raw_amount, (int, float)):
            description = f"{from_who} — refund ({purpose})" if purpose else f"{from_who} — refund"
            cat, sub = classify_txn(description, "income")

            incomes.append({
                "txn_date": txn_date.date(),
                "description": description,
                "amount": float(raw_refund),
                "txn_type": "income",
                "category": cat,
                "sub_category": sub,
                "upi_reference": str(txn_id) if txn_id else None,
                "account_name": "LAKSHMI_SBI",
                "unique_hash": make_hash(txn_date.date(), raw_refund, description + "_refund"),
            })

    return expenses, incomes


async def run():
    expenses, incomes = parse_rows()
    all_txns = expenses + incomes

    print(f"\n{'DRY RUN' if not WRITE else 'WRITING'} — {len(expenses)} expenses + {len(incomes)} incomes = {len(all_txns)} total\n")

    # Show summary by month + category
    from collections import defaultdict
    by_month: dict = defaultdict(lambda: defaultdict(float))
    for t in all_txns:
        m = t["txn_date"].strftime("%Y-%m")
        by_month[m][t["category"]] += t["amount"] if t["txn_type"] == "expense" else -t["amount"]

    for m in sorted(by_month):
        total = sum(by_month[m].values())
        print(f"  {m}  net={total:>10,.0f}")
        for cat, amt in sorted(by_month[m].items(), key=lambda x: -abs(x[1])):
            print(f"    {cat:<45} {amt:>10,.0f}")

    grand = sum(t["amount"] if t["txn_type"] == "expense" else -t["amount"] for t in all_txns)
    print(f"\n  GRAND NET CAPEX/OPEX: Rs.{grand:,.0f}")

    if not WRITE:
        print("\n  Run with --write to insert into DB.")
        return

    engine = create_async_engine(DB)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as session:
        # Create upload record
        result = await session.execute(
            sa.text("""
                INSERT INTO bank_uploads (phone, file_path, row_count, new_count, from_date, to_date, status, uploaded_at)
                VALUES (:phone, :file_path, :row_count, :new_count, :from_date, :to_date, 'processed', NOW())
                RETURNING id
            """),
            {
                "phone": "system",
                "file_path": "Investment.xlsx",
                "row_count": len(all_txns),
                "new_count": len(all_txns),
                "from_date": min(t["txn_date"] for t in all_txns),
                "to_date": max(t["txn_date"] for t in all_txns),
            }
        )
        upload_id = result.scalar()
        print(f"\n  Created bank_uploads id={upload_id}")

        inserted = 0
        skipped = 0
        for t in all_txns:
            # Dedup check
            existing = await session.scalar(
                sa.text("SELECT id FROM bank_transactions WHERE unique_hash = :h"),
                {"h": t["unique_hash"]}
            )
            if existing:
                skipped += 1
                continue

            await session.execute(
                sa.text("""
                    INSERT INTO bank_transactions
                      (upload_id, txn_date, description, amount, txn_type, category, sub_category,
                       upi_reference, source, unique_hash, account_name)
                    VALUES
                      (:upload_id, :txn_date, :description, :amount, :txn_type, :category, :sub_category,
                       :upi_reference, 'investment_excel', :unique_hash, :account_name)
                """),
                {**t, "upload_id": upload_id}
            )
            inserted += 1

        await session.commit()
        print(f"  Inserted: {inserted}, Skipped (dupes): {skipped}")

    await engine.dispose()


asyncio.run(run())
