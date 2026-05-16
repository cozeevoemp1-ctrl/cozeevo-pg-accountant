import asyncio, os, sys
sys.stdout.reconfigure(encoding='utf-8')
from dotenv import load_dotenv; load_dotenv()
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

async def run():
    url = os.environ['DATABASE_URL'].replace('postgresql://', 'postgresql+asyncpg://', 1)
    engine = create_async_engine(url, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as s:
        rows = (await s.execute(text("""
            SELECT p.id, p.amount, p.payment_mode, p.for_type, p.period_month, p.is_void
            FROM payments p
            JOIN tenancies t ON t.id = p.tenancy_id
            JOIN tenants tn ON tn.id = t.tenant_id
            WHERE tn.name ILIKE '%akshat%'
            ORDER BY p.id DESC
        """))).fetchall()
        print(f"Akshat payments ({len(rows)}):")
        for r in rows:
            print(f"  pmt {r[0]}: {r[2]} Rs{int(r[1])} {r[3]} period={r[4]} is_void={r[5]}")

        # Also check May totals
        r2 = (await s.execute(text("""
            SELECT payment_mode, SUM(amount), COUNT(*) FROM payments
            WHERE period_month='2026-05-01' AND for_type='rent' AND is_void=false
            GROUP BY payment_mode
        """))).fetchall()
        print("\nMay DB totals (rent, active):")
        total = 0
        for r in r2:
            print(f"  {r[0]}: Rs{int(r[1])} ({r[2]} pmts)")
            total += int(r[1])
        print(f"  TOTAL: Rs{total:,}")
    await engine.dispose()

asyncio.run(run())
