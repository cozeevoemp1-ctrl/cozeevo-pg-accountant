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
        r = (await s.execute(text(
            'SELECT id, amount, payment_mode, for_type, period_month, is_void, notes '
            'FROM payments WHERE id=16229'
        ))).fetchone()
        if r:
            print(f'pmt {r[0]}: {r[2]} Rs{int(r[1])} {r[3]} period={r[4]} is_void={r[5]}')
            print(f'notes: {r[6]}')
        else:
            print('pmt 16229 not found')
            # Search by Lenin Das tenancy
            rows = (await s.execute(text("""
                SELECT p.id, p.amount, p.payment_mode, p.for_type, p.is_void
                FROM payments p
                JOIN tenancies t ON t.id = p.tenancy_id
                JOIN tenants tn ON tn.id = t.tenant_id
                WHERE tn.name ILIKE '%lelin%' OR tn.name ILIKE '%lenin%'
                ORDER BY p.id DESC LIMIT 10
            """))).fetchall()
            for row in rows:
                print(f'  pmt {row[0]}: {row[2]} Rs{int(row[1])} {row[3]} is_void={row[4]}')
    await engine.dispose()

asyncio.run(run())
