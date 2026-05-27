"""
One-off: set payment_mode = NULL for all Excel-imported deposits and booking advances
in frozen months (Nov'25–Apr'26).

These were defaulted to 'cash' during import, which is wrong — we don't know the actual
mode for historical data. Only PWA-entered payments have a meaningful cash/UPI split.

Safe to run multiple times (idempotent).
Run with --write to apply; dry-run by default.
"""
import asyncio, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dotenv import load_dotenv
load_dotenv()

DRY_RUN = "--write" not in sys.argv


async def main():
    from src.database.db_manager import init_db, get_session
    from sqlalchemy import text

    db_url = os.environ.get("SUPABASE_DB_URL") or os.environ.get("DATABASE_URL")
    await init_db(db_url)

    async with get_session() as session:
        # Preview
        r = await session.execute(text("""
            SELECT for_type, payment_mode, COUNT(*) as cnt, SUM(amount) as total
            FROM payments
            WHERE notes ILIKE :note
              AND for_type IN ('deposit', 'booking')
              AND payment_date < '2026-05-01'
            GROUP BY for_type, payment_mode
            ORDER BY for_type, payment_mode
        """), {"note": "%Imported from Excel%"})
        rows = r.fetchall()
        print("Rows to nullify:")
        for row in rows:
            print(f"  for_type={row[0]:10s}  payment_mode={row[1]}  count={row[2]}  total=Rs{int(row[3]):,}")

        if DRY_RUN:
            print("\nDry run — pass --write to apply.")
            return

        result = await session.execute(text("""
            UPDATE payments
            SET payment_mode = NULL
            WHERE notes ILIKE :note
              AND for_type IN ('deposit', 'booking')
              AND payment_date < '2026-05-01'
        """), {"note": "%Imported from Excel%"})
        await session.commit()
        print(f"\nUpdated {result.rowcount} rows — payment_mode set to NULL.")

        # Verify
        r2 = await session.execute(text("""
            SELECT for_type, payment_mode, COUNT(*) as cnt, SUM(amount) as total
            FROM payments
            WHERE notes ILIKE :note
              AND for_type IN ('deposit', 'booking')
              AND payment_date < '2026-05-01'
            GROUP BY for_type, payment_mode
            ORDER BY for_type, payment_mode
        """), {"note": "%Imported from Excel%"})
        print("\nAfter update:")
        for row in r2.fetchall():
            print(f"  for_type={row[0]:10s}  payment_mode={row[1]}  count={row[2]}  total=Rs{int(row[3]):,}")


asyncio.run(main())
