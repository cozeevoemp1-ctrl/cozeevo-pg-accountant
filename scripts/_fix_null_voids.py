import asyncio, os
from dotenv import load_dotenv; load_dotenv()
import asyncpg

async def main():
    conn = await asyncpg.connect(os.getenv('DATABASE_URL').replace('postgresql+asyncpg','postgresql'))

    # Find all April payments with is_void=NULL
    rows = await conn.fetch(
        "SELECT p.id, t.name, p.payment_mode, p.amount "
        "FROM payments p "
        "JOIN tenancies te ON p.tenancy_id=te.id "
        "JOIN tenants t ON te.tenant_id=t.id "
        "WHERE p.period_month='2026-04-01' AND p.for_type='rent' AND p.is_void IS NULL")
    print(f'NULL is_void records: {len(rows)}')
    for r in rows:
        print(f'  id={r["id"]}  {r["name"][:22]:22s}  {r["payment_mode"]:5s}  {int(r["amount"]):,}')

    if rows:
        async with conn.transaction():
            await conn.execute("SET LOCAL app.allow_historical_write = 'true'")
            result = await conn.execute(
                "UPDATE payments SET is_void=false "
                "WHERE period_month='2026-04-01' AND for_type='rent' AND is_void IS NULL")
            print(f'Fixed: {result}')

    # Final totals
    totals = await conn.fetch(
        "SELECT payment_mode, SUM(amount) as total FROM payments "
        "WHERE period_month='2026-04-01' AND for_type='rent' AND is_void=false "
        "GROUP BY payment_mode")
    cash = next((int(r['total']) for r in totals if r['payment_mode']=='cash'), 0)
    upi  = next((int(r['total']) for r in totals if r['payment_mode']=='upi'),  0)
    print(f'\nDB April now: Cash {cash:>12,}  UPI {upi:>12,}  Total {cash+upi:>12,}')
    print(f'Sheet target: Cash {1343783:>12,}  UPI {3195365:>12,}  Total {1343783+3195365:>12,}')
    print(f'Diff:         Cash {cash-1343783:>+12,}  UPI {upi-3195365:>+12,}  Total {(cash+upi)-(1343783+3195365):>+12,}')

    await conn.close()

asyncio.run(main())
