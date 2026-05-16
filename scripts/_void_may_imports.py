"""
Void all payments imported from May source sheet (Z/AA import).
Run this before re-importing to avoid duplicates.
"""
import asyncio, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv; load_dotenv()
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text


async def main():
    url = os.environ["DATABASE_URL"]
    if not url.startswith("postgresql+asyncpg"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(url, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as session:
        # Preview first
        rows = (await session.execute(text("""
            SELECT id, tenancy_id, amount, payment_mode, for_type, notes
            FROM payments
            WHERE notes LIKE '%May source sheet%' AND is_void = false
            ORDER BY tenancy_id, id
        """))).fetchall()

        if not rows:
            print("No May source sheet payments found — nothing to void.")
            return

        print(f"Found {len(rows)} payments to void:")
        for r in rows:
            print(f"  id={r[0]} tenancy={r[1]} amt={r[2]} {r[3]} {r[4]}")

        confirm = input(f"\nVoid all {len(rows)} payments? (yes/no): ").strip().lower()
        if confirm != "yes":
            print("Aborted.")
            return

        result = await session.execute(text("""
            UPDATE payments
            SET is_void = true, notes = notes || ' [VOIDED - re-import]'
            WHERE notes LIKE '%May source sheet%' AND is_void = false
        """))
        await session.commit()
        print(f"Voided {result.rowcount} payments.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
