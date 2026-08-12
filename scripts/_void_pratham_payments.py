import asyncio, asyncpg, os
from dotenv import load_dotenv
load_dotenv()

async def main():
    conn = await asyncpg.connect(
        os.environ["DATABASE_URL"].replace("+asyncpg", "")
    )
    ids = [15964, 15965, 15966, 15967]
    async with conn.transaction():
        await conn.execute("SET LOCAL app.allow_historical_write = 'true'")
        await conn.execute("""
            UPDATE payments
            SET is_void = true,
                notes = notes || ' [VOIDED: test check-in 2026-05-15 — reference-only, not actually collected]'
            WHERE id = ANY($1) AND is_void = false
        """, ids)
    rows = await conn.fetch("SELECT id, amount, for_type, is_void, notes FROM payments WHERE id = ANY($1)", ids)
    for r in rows:
        print(dict(r))
    await conn.close()

asyncio.run(main())
