import asyncio, os, datetime
from dotenv import load_dotenv
load_dotenv()
import asyncpg

async def main():
    url = os.getenv('DATABASE_URL').replace('postgresql+asyncpg', 'postgresql')
    conn = await asyncpg.connect(url)

    async with conn.transaction():
        await conn.execute("SET LOCAL app.allow_historical_write = 'true'")

        # Void March 12:xx batch (8 entries = 124,500 extra above approved 3,983,413)
        r1 = await conn.execute(
            "UPDATE payments SET is_void=true "
            "WHERE period_month='2026-03-01' AND for_type='rent' AND is_void=false "
            "AND DATE_TRUNC('hour', created_at) = '2026-04-27 12:00:00'")
        print('Mar voided:', r1)

        # Void December 12,800 entry
        r2 = await conn.execute(
            "UPDATE payments SET is_void=true "
            "WHERE period_month='2025-12-01' AND for_type='rent' AND is_void=false")
        print('Dec voided:', r2)

    # Verify
    months = ['2025-11-01','2025-12-01','2026-01-01','2026-02-01','2026-03-01']
    for m in months:
        rows = await conn.fetch(
            "SELECT payment_mode, SUM(amount) as total FROM payments "
            "WHERE period_month=$1 AND for_type='rent' AND is_void=false "
            "GROUP BY payment_mode",
            datetime.date.fromisoformat(m))
        cash = next((int(r['total']) for r in rows if r['payment_mode'] == 'cash'), 0)
        upi  = next((int(r['total']) for r in rows if r['payment_mode'] == 'upi'),  0)
        print(f'{m[:7]}  Cash:{cash:>10,}  UPI:{upi:>10,}  Total:{cash+upi:>10,}')

    await conn.close()

asyncio.run(main())
