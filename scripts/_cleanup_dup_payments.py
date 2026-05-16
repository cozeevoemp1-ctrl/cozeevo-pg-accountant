"""Delete all Apr+May 2026 payments and rent_schedules via raw SQL (bypasses freeze trigger)."""
import asyncio, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv; load_dotenv()
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

ALLOW = "SET LOCAL app.allow_historical_write = 'true'"

# All payments for Apr/May period months
DEL_PAY_PM = "DELETE FROM payments WHERE period_month IN ('2026-04-01', '2026-05-01')"
DEL_RS     = "DELETE FROM rent_schedule WHERE period_month IN ('2026-04-01', '2026-05-01')"

# Stray deposits with payment_date in Apr/May but period_month=NULL
# These double-count with the sheet reload deposits
DEL_DEP_NULL = """
    DELETE FROM payments
    WHERE period_month IS NULL
      AND for_type = 'deposit'
      AND payment_date >= '2026-04-01'
      AND payment_date < '2026-06-01'
"""

async def main():
    url = os.environ["DATABASE_URL"].replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(url, echo=False)
    async with engine.connect() as conn:
        await conn.execute(text(ALLOW))
        r1 = await conn.execute(text(DEL_PAY_PM))
        r2 = await conn.execute(text(DEL_RS))
        r3 = await conn.execute(text(DEL_DEP_NULL))
        await conn.commit()
        print(f"Deleted {r1.rowcount} period_month payments + {r2.rowcount} rent_schedules + {r3.rowcount} stray deposits")
    await engine.dispose()

asyncio.run(main())
