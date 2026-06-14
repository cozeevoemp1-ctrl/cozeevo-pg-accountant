"""Root-cause fix for payments with is_void IS NULL.

Raw-SQL insert paths that omit is_void leave it NULL, and every
`WHERE is_void = false` filter (history, dues, P&L, sheet sync) silently
drops those rows. This:
  1. Backfills all is_void NULL -> false (freeze-trigger bypass for frozen months)
  2. Hardens the column: SET DEFAULT false + SET NOT NULL so it can never recur
"""
import asyncio, os, sys
sys.stdout.reconfigure(encoding='utf-8')
from dotenv import load_dotenv; load_dotenv()
import asyncpg


async def main():
    conn = await asyncpg.connect(os.getenv('DATABASE_URL').replace('postgresql+asyncpg', 'postgresql'))

    rows = await conn.fetch(
        "SELECT p.id, t.name, r.room_number, p.payment_mode, p.for_type, p.amount, p.payment_date "
        "FROM payments p "
        "JOIN tenancies te ON p.tenancy_id=te.id "
        "JOIN tenants t ON te.tenant_id=t.id "
        "LEFT JOIN rooms r ON r.id=te.room_id "
        "WHERE p.is_void IS NULL ORDER BY p.id")
    print(f'NULL is_void records: {len(rows)}')
    for r in rows:
        print(f'  id={r["id"]}  {r["name"][:22]:22s}  rm {str(r["room_number"]):4s}  '
              f'{r["payment_mode"] or "—":5s}  {r["for_type"]:8s}  {int(r["amount"]):>7,}  {r["payment_date"]}')

    if rows:
        async with conn.transaction():
            await conn.execute("SET LOCAL app.allow_historical_write = 'true'")
            result = await conn.execute("UPDATE payments SET is_void=false WHERE is_void IS NULL")
            print(f'\nBackfill: {result}')

    # Harden column so raw inserts can never leave NULL again
    async with conn.transaction():
        await conn.execute("ALTER TABLE payments ALTER COLUMN is_void SET DEFAULT false")
        await conn.execute("ALTER TABLE payments ALTER COLUMN is_void SET NOT NULL")
    print('Column hardened: is_void SET DEFAULT false, SET NOT NULL')

    remaining = await conn.fetchval("SELECT count(*) FROM payments WHERE is_void IS NULL")
    print(f'Remaining NULL is_void: {remaining}')

    await conn.close()


asyncio.run(main())
