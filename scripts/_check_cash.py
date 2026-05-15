"""One-off: check cash data per month to compare with PWA Cash tab."""
import asyncio, os, sys
sys.path.insert(0, ".")
from dotenv import load_dotenv; load_dotenv()
from src.database.db_manager import init_db, get_session
from sqlalchemy import text

async def run():
    db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
    await init_db(db_url)
    async with get_session() as s:
        print("=== PAYMENTS BY MONTH + MODE ===")
        rows = (await s.execute(text(
            "SELECT DATE_TRUNC('month', payment_date)::date AS month, "
            "payment_mode::text AS mode, SUM(amount) AS amt "
            "FROM payments WHERE is_void = false "
            "GROUP BY 1,2 ORDER BY 1,2"
        ))).all()
        month_cash = {}
        for r in rows:
            print(f"  {r.month}  {str(r.mode):<8}  {int(r.amt):>10,}")
            if str(r.mode).lower() == "cash":
                month_cash[str(r.month)] = int(r.amt)

        print("\n=== CASH EXPENSES BY MONTH ===")
        rows2 = (await s.execute(text(
            "SELECT DATE_TRUNC('month', date)::date AS month, "
            "SUM(amount) AS expenses, COUNT(*) AS cnt "
            "FROM cash_expenses WHERE is_void = false GROUP BY 1 ORDER BY 1"
        ))).all()
        month_exp = {}
        for r in rows2:
            print(f"  {r.month}  expenses={int(r.expenses):,}  n={r.cnt}")
            month_exp[str(r.month)] = int(r.expenses)

        print("\n=== CASH BALANCE BY MONTH (collected - expenses) ===")
        all_months = sorted(set(list(month_cash.keys()) + list(month_exp.keys())))
        running = 0
        for m in all_months:
            c = month_cash.get(m, 0)
            e = month_exp.get(m, 0)
            running += c - e
            print(f"  {m}  collected={c:>8,}  expenses={e:>8,}  net={c-e:>8,}  running={running:>10,}")

asyncio.run(run())
