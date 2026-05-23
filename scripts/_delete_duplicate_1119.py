"""One-off: delete duplicate Chinchu David tenancy 1119 + its CheckoutRecord.
Confirmed zero payments. Duplicate of tenancy 1112 (same tenant/room/dates).
Run: python scripts/_delete_duplicate_1119.py [--write]
"""
import asyncio
import sys

sys.path.insert(0, ".")

WRITE = "--write" in sys.argv


async def run():
    import os
    from dotenv import load_dotenv
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from sqlalchemy import text

    load_dotenv()
    url = os.environ["DATABASE_URL"]
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(url, echo=False)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with Session() as s:
        # Verify zero payments
        payment_count = (await s.execute(
            text("SELECT COUNT(*) FROM payments WHERE tenancy_id=1119 AND is_void=false")
        )).scalar()
        print(f"Active payments on 1119: {payment_count}")
        if payment_count and payment_count > 0:
            print("ABORT — unexpected active payments on tenancy 1119")
            return

        cr = (await s.execute(
            text("SELECT id FROM checkout_records WHERE tenancy_id=1119")
        )).fetchall()
        print(f"CheckoutRecords to delete: {[r[0] for r in cr]}")

        cs = (await s.execute(
            text("SELECT id FROM checkout_sessions WHERE tenancy_id=1119")
        )).fetchall()
        print(f"CheckoutSessions to delete: {[r[0] for r in cs]}")

        obs = (await s.execute(
            text("SELECT id FROM onboarding_sessions WHERE tenancy_id=1119")
        )).fetchall()
        print(f"OnboardingSessions to null: {[r[0] for r in obs]}")

        ref = (await s.execute(
            text("SELECT id, amount FROM refunds WHERE tenancy_id=1119")
        )).fetchall()
        print(f"Refunds to delete: {[(r[0], r[1]) for r in ref]}")

        if not WRITE:
            print("\nDRY RUN — pass --write to execute")
            return

        await s.execute(text("DELETE FROM checkout_records WHERE tenancy_id=1119"))
        await s.execute(text("DELETE FROM checkout_sessions WHERE tenancy_id=1119"))
        await s.execute(text("UPDATE onboarding_sessions SET tenancy_id=NULL WHERE tenancy_id=1119"))
        await s.execute(text("DELETE FROM payments WHERE tenancy_id=1119"))
        await s.execute(text("DELETE FROM refunds WHERE tenancy_id=1119"))
        await s.execute(text("UPDATE documents SET tenancy_id=NULL WHERE tenancy_id=1119"))
        await s.execute(text("DELETE FROM tenancies WHERE id=1119"))
        await s.commit()
        print("Done — tenancy 1119 and all linked records deleted.")


asyncio.run(run())
