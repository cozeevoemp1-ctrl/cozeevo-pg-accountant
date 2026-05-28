"""
Backfill bank_transactions.balance from all CSV files on disk.

Matches each CSV row to its DB row by (txn_date, txn_type, amount, description hash)
and updates the balance column where it's NULL.

Run: python scripts/_backfill_bank_balance.py [--write]
"""
import sys, os, asyncio
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, ".")

WRITE = "--write" in sys.argv

# CSV files and their account names
CSV_FILES = [
    # (path, account_name)
    ("2025_statement_temp.csv",                                   "THOR"),
    ("2026 statment.csv",                                          "THOR"),
    ("april month.csv",                                            "THOR"),
    ("hulk_temp.csv",                                              "HULK"),
    ("data/backups/sort_20260420_173132/DECEMBER_2025.csv",        "THOR"),
    ("data/backups/sort_20260420_173132/JANUARY_2026.csv",         "THOR"),
    ("data/backups/sort_20260420_173132/FEBRUARY_2026.csv",        "THOR"),
    ("data/backups/sort_20260420_173132/MARCH_2026.csv",           "THOR"),
    ("data/backups/sort_20260420_173132/APRIL_2026.csv",           "THOR"),
]


async def run():
    from dotenv import load_dotenv
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from sqlalchemy import text
    from src.parsers.yes_bank import read_yes_bank_csv
    import hashlib as _hl

    def _make_hash(txn_date, amount, desc):
        key = f"{txn_date}|{(desc or '').strip().lower()[:80]}|{round(float(amount), 2)}"
        return _hl.sha256(key.encode()).hexdigest()[:32]

    load_dotenv()
    url = os.environ["DATABASE_URL"]
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(url, echo=False)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    total_updated = 0

    async with Session() as s:
        for csv_path, account in CSV_FILES:
            if not os.path.exists(csv_path):
                print(f"  SKIP (not found): {csv_path}")
                continue

            rows = read_yes_bank_csv(csv_path)
            updates = 0
            for txn_date, desc, txn_type, amount, balance in rows:
                if balance is None:
                    continue
                norm_desc = (desc or "").strip()
                uhash = _make_hash(txn_date, amount, norm_desc)
                result = await s.execute(text("""
                    UPDATE bank_transactions
                    SET balance = :balance
                    WHERE unique_hash = :uhash
                      AND account_name = :account
                      AND balance IS NULL
                """), {"balance": balance, "uhash": uhash, "account": account})
                if result.rowcount:
                    updates += result.rowcount

            print(f"  {csv_path} ({account}): {updates} rows would update" if not WRITE
                  else f"  {csv_path} ({account}): {updates} rows updated")
            total_updated += updates

        if WRITE:
            await s.commit()

    print(f"\nTotal: {total_updated} rows {'updated' if WRITE else 'would update'}")
    if not WRITE:
        print("DRY RUN — pass --write to execute")


asyncio.run(run())
