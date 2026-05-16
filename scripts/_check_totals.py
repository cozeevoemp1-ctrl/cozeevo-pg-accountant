import asyncio, os, sys
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv; load_dotenv()
from datetime import date
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

async def run():
    url = os.environ['DATABASE_URL'].replace('postgresql://', 'postgresql+asyncpg://', 1)
    engine = create_async_engine(url, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as s:
        for month, label in [(date(2026, 4, 1), 'APRIL'), (date(2026, 5, 1), 'MAY')]:
            r = await s.execute(
                text("SELECT payment_mode, SUM(amount) as total, COUNT(*) as cnt "
                     "FROM payments "
                     "WHERE period_month=:m AND for_type='rent' AND is_void=false "
                     "GROUP BY payment_mode ORDER BY payment_mode"),
                {'m': month}
            )
            rows = r.fetchall()
            print(f'{label} DB (rent, active):')
            grand = 0
            for row in rows:
                print(f'  {row[0]:5}: {int(row[1]):>12,}  ({row[2]} pmts)')
                grand += float(row[1])
            print(f'  TOTAL: {int(grand):,}')
            print()
    await engine.dispose()

asyncio.run(run())
