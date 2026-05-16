"""Delete all Apr+May 2026 payments and rent_schedules via raw SQL (bypasses freeze trigger)."""
import asyncio, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv; load_dotenv()
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

ALLOW = "SET LOCAL app.allow_historical_write = 'true'"
DEL_PAY = "DELETE FROM payments WHERE period_month IN ('2026-04-01', '2026-05-01')"
DEL_RS  = "DELETE FROM rent_schedule WHERE period_month IN ('2026-04-01', '2026-05-01')"

async def main():
    url = os.environ["DATABASE_URL"].replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(url, echo=False)
    async with engine.connect() as conn:
        await conn.execute(text(ALLOW))
        r1 = await conn.execute(text(DEL_PAY))
        r2 = await conn.execute(text(DEL_RS))
        await conn.commit()
        print(f"Deleted {r1.rowcount} payments + {r2.rowcount} rent_schedules")
    await engine.dispose()

asyncio.run(main())
