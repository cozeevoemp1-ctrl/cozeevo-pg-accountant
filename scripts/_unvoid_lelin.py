"""Un-void pmt 16229 — Lenin Das ₹27K cash May rent (was incorrectly voided as booking dup)."""
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
        await s.execute(text("SET LOCAL app.allow_historical_write = 'true'"))
        r = await s.execute(text(
            "UPDATE payments SET is_void=false, notes=replace(notes, ' [VOIDED: dup of booking advance -- Z/AA import bug 2026-05-16]', '') || ' [UN-VOIDED 2026-05-16: confirmed May rent not dup]' WHERE id=16229"
        ))
        await s.commit()
        print(f"Rows updated: {r.rowcount}")

        row = (await s.execute(text(
            "SELECT id, amount, payment_mode, for_type, is_void, notes FROM payments WHERE id=16229"
        ))).fetchone()
        print(f"pmt {row[0]}: {row[2]} ₹{int(row[1])} {row[3]} is_void={row[3]} → {row[4]}")
        print(f"notes: {row[5]}")
    await engine.dispose()

asyncio.run(run())
