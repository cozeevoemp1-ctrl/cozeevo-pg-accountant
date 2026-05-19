"""
One-off: add missing booking payment for Pratham (Room 420).
Reason: checked in during 4a61d4b window when auto-payment was removed.
Idempotent — skips if booking payment already exists.
"""
import asyncio, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv; load_dotenv()

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from src.database.models import Payment, PaymentFor, PaymentMode, Tenancy, TenancyStatus, Tenant, Room


async def main():
    url = os.environ["DATABASE_URL"]
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(url, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as session:
        result = await session.execute(
            select(Tenancy, Tenant, Room)
            .join(Tenant, Tenant.id == Tenancy.tenant_id)
            .join(Room, Room.id == Tenancy.room_id)
            .where(
                Tenant.name.ilike("%Pratham%"),
                Room.room_number == "420",
                Tenancy.status == TenancyStatus.active,
            )
        )
        row = result.first()
        if not row:
            print("ERROR: No active tenancy found for Pratham in Room 420")
            return

        tenancy, tenant, room = row
        print(f"Found: {tenant.name} | tenancy_id={tenancy.id} | booking_amount={tenancy.booking_amount} | checkin={tenancy.checkin_date}")

        if not tenancy.booking_amount or float(tenancy.booking_amount) == 0:
            print("booking_amount is 0 — nothing to do")
            return

        existing = await session.scalar(
            select(Payment).where(
                Payment.tenancy_id == tenancy.id,
                Payment.for_type == PaymentFor.booking,
                Payment.is_void == False,
            )
        )
        if existing:
            print(f"Booking payment already exists: id={existing.id} amount={existing.amount} — skipping")
            return

        payment = Payment(
            tenancy_id=tenancy.id,
            amount=tenancy.booking_amount,
            payment_date=tenancy.checkin_date,
            payment_mode=PaymentMode.upi,
            for_type=PaymentFor.booking,
            period_month=None,
            notes="Advance/booking payment recorded at check-in (upi) [backfill]",
        )
        session.add(payment)
        await session.commit()
        await session.refresh(payment)
        print(f"OK: Payment inserted id={payment.id} amount={payment.amount} date={payment.payment_date}")


asyncio.run(main())
