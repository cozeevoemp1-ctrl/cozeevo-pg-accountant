"""
Drop all investment_expenses and reload from Whitefield PG Expense Tracker.xlsx.
Run: python scripts/_import_whitefield_tracker.py [--write]
"""
import sys, os, asyncio, hashlib
sys.stdout.reconfigure(encoding="utf-8")
from pathlib import Path
from datetime import datetime, date

sys.path.insert(0, ".")
WRITE = "--write" in sys.argv

XLSX = Path(__file__).parent.parent / "Whitefield PG Expense Tracker.xlsx"
PROPERTY = "Whitefield"

# Classify purpose as lease deposit (refundable asset) vs fixed asset
LEASE_DEPOSIT_KEYWORDS = ["advance to raghu", "advance for raghu"]


def _is_lease_deposit(purpose: str) -> bool:
    return any(k in (purpose or "").lower() for k in LEASE_DEPOSIT_KEYWORDS)


def _parse_date(val) -> date | None:
    if val is None:
        return None
    if isinstance(val, (datetime,)):
        return val.date()
    if isinstance(val, date):
        return val
    s = str(val).strip().replace(" ", "")
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            pass
    return None


def _parse_amount(val) -> float | None:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).replace("₹", "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _hash(sno, purpose, amount, paid_by) -> str:
    raw = f"{sno}|{purpose}|{amount}|{paid_by}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _read_rows():
    import openpyxl
    wb = openpyxl.load_workbook(str(XLSX), read_only=True, data_only=True)
    ws = wb["White Field PG Expenses"]
    rows = []
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 0:
            continue  # header
        sno_raw, purpose_raw, amt_raw, paid_by_raw, date_raw, txn_id_raw, paid_to_raw = (
            row[0], row[1], row[2], row[3], row[4], row[5], row[6]
        )
        if sno_raw is None and purpose_raw is None:
            continue
        amount = _parse_amount(amt_raw)
        if amount is None or amount <= 0:
            continue  # skip rows with no valid amount
        purpose = str(purpose_raw).strip() if purpose_raw else ""
        paid_by = str(paid_by_raw).strip() if paid_by_raw else ""
        txn_date = _parse_date(date_raw)
        txn_id = str(txn_id_raw).strip() if txn_id_raw else None
        paid_to = str(paid_to_raw).strip() if paid_to_raw else None
        sno = int(sno_raw) if sno_raw else 0
        notes = "lease_deposit" if _is_lease_deposit(purpose) else "fixed_asset"
        rows.append({
            "sno": sno,
            "purpose": purpose[:500],
            "amount": amount,
            "paid_by": paid_by[:200],
            "transaction_date": txn_date,
            "transaction_id": (txn_id or "")[:200] if txn_id else None,
            "paid_to": (paid_to or "")[:500] if paid_to else None,
            "property": PROPERTY,
            "unique_hash": _hash(sno, purpose, amount, paid_by),
            "is_void": False,
            "notes": notes,
        })
    return rows


async def run():
    from dotenv import load_dotenv
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from sqlalchemy import text

    load_dotenv()
    url = os.environ["DATABASE_URL"]
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(url, echo=False)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    rows = _read_rows()
    total = sum(r["amount"] for r in rows)
    lease = sum(r["amount"] for r in rows if r["notes"] == "lease_deposit")
    fixed = sum(r["amount"] for r in rows if r["notes"] == "fixed_asset")

    print(f"Rows parsed: {len(rows)}")
    print(f"  Lease deposits : ₹{lease:,.0f}")
    print(f"  Fixed assets   : ₹{fixed:,.0f}")
    print(f"  Total          : ₹{total:,.0f}")

    if not WRITE:
        print("\nDRY RUN — pass --write to execute")
        return

    async with Session() as s:
        deleted = (await s.execute(text("DELETE FROM investment_expenses"))).rowcount
        print(f"\nDeleted {deleted} existing rows")

        for r in rows:
            await s.execute(text("""
                INSERT INTO investment_expenses
                    (sno, purpose, amount, paid_by, transaction_date,
                     transaction_id, paid_to, property, unique_hash, is_void, notes)
                VALUES
                    (:sno, :purpose, :amount, :paid_by, :transaction_date,
                     :transaction_id, :paid_to, :property, :unique_hash, :is_void, :notes)
            """), r)

        await s.commit()
        print(f"Inserted {len(rows)} rows. Done.")


asyncio.run(run())
