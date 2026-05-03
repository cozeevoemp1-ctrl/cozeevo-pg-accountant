"""
scripts/import_thor_to_db.py
-----------------------------
One-time script that:
  1. Backfills NULL account_name → 'THOR' for existing rows
  2. Loads all local bank statement files (Oct 2025 – Apr 2026) into
     bank_transactions DB, skipping duplicates by unique_hash.

Safe to re-run: dedup hash prevents double-inserts.

Run:
  venv/Scripts/python scripts/import_thor_to_db.py
"""
import sys, os, glob as _glob, asyncio, hashlib
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv; load_dotenv()
from datetime import date
import asyncpg

from src.parsers.yes_bank import read_yes_bank_csv, parse_date, parse_amt
from src.rules.pnl_classify import classify_txn

DB_URL = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")

def _make_hash(txn_date: date, amount: float, desc: str) -> str:
    key = f"{txn_date}|{(desc or '').strip().lower()[:80]}|{round(float(amount), 2)}"
    return hashlib.sha256(key.encode()).hexdigest()


async def main():
    conn = await asyncpg.connect(DB_URL)

    # ── Step 1: Backfill NULL account_name → THOR ─────────────────────────────
    updated = await conn.execute("UPDATE bank_transactions SET account_name = 'THOR' WHERE account_name IS NULL")
    print(f"Backfilled NULL account_name: {updated}")

    # ── Step 2: Load local files ───────────────────────────────────────────────
    txns = []
    csv_files = sorted(set(
        _glob.glob("Statement-*.csv") + _glob.glob("*statment*.csv") +
        _glob.glob("*statement*.csv") + _glob.glob("april month.csv") +
        _glob.glob("april*.csv")
    ), reverse=True)
    for f in csv_files:
        rows = read_yes_bank_csv(f)
        print(f"  {len(rows):>4}  {f}")
        txns += rows

    # Excel files
    import openpyxl as _opx
    for f in ["2025 statement.xlsx", "2026 statment.xlsx"]:
        if not os.path.exists(f):
            continue
        wb_s = _opx.load_workbook(f, data_only=True); ws_s = wb_s.active
        rows_s = list(ws_s.iter_rows(values_only=True))
        hrow = next((i for i, r in enumerate(rows_s) if r and any("transaction date" in str(c).lower() for c in r if c)), None)
        if hrow is None:
            continue
        headers = [str(c).lower().strip() if c else "" for c in rows_s[hrow]]
        count = 0
        for row in rows_s[hrow + 1:]:
            if not any(row): continue
            d2 = dict(zip(headers, row))
            dt = parse_date(d2.get("transaction date"))
            if not dt: continue
            wd  = parse_amt(d2.get("withdrawals", ""))
            dep = parse_amt(d2.get("deposits", ""))
            desc2 = str(d2.get("description") or "")
            if wd > 0:  txns.append((dt, desc2, "expense", wd)); count += 1
            if dep > 0: txns.append((dt, desc2, "income",  dep)); count += 1
        print(f"  {count:>4}  {f}")

    # Dedupe locally
    seen: set = set(); deduped = []
    for item in txns:
        dt, desc, typ, amt = item
        key = (dt.strftime("%Y-%m-%d"), round(float(amt), 2), (desc or "").strip().lower())
        if key not in seen:
            seen.add(key); deduped.append(item)
    print(f"\nLocal total after dedupe: {len(deduped)} txns")

    # ── Step 3: Insert new rows ────────────────────────────────────────────────
    # Fetch all existing hashes from DB
    existing_hashes = set(r[0] for r in await conn.fetch("SELECT unique_hash FROM bank_transactions"))
    print(f"Existing DB hashes: {len(existing_hashes)}")

    new_count = 0; dup_count = 0
    for txn_date, desc, txn_type, amount in deduped:
        uhash = _make_hash(txn_date, float(amount), desc)
        if uhash in existing_hashes:
            dup_count += 1
            continue

        cat, sub = classify_txn(desc, txn_type)
        result = await conn.execute("""
            INSERT INTO bank_transactions
              (upload_id, txn_date, description, amount, txn_type,
               category, sub_category, unique_hash, account_name)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (unique_hash) DO NOTHING
        """, None, txn_date, desc, float(amount), txn_type, cat, sub, uhash, "THOR")
        if result == "INSERT 0 1":
            new_count += 1
        else:
            dup_count += 1

    print(f"\nInserted: {new_count} new rows")
    print(f"Skipped:  {dup_count} duplicates")

    # ── Summary by month ───────────────────────────────────────────────────────
    rows = await conn.fetch("""
        SELECT to_char(txn_date,'YYYY-MM') AS m, account_name, COUNT(*)
        FROM bank_transactions
        GROUP BY m, account_name
        ORDER BY m, account_name
    """)
    print("\nFinal DB state:")
    for r in rows:
        print(f"  {r['account_name'] or 'NULL':6}  {r['m']}  {r[2]} rows")

    await conn.close()


asyncio.run(main())
