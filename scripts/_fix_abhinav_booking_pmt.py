"""Fix Abhinav (tenancy 1122) booking advance: update payment_mode to UPI.
The activity feed now reads directly from the payments table, so no audit entry needed.
"""
import asyncio, os
from dotenv import load_dotenv
load_dotenv()

async def main():
    from src.database.db_manager import init_db, get_session
    from src.database.models import Payment, PaymentMode, PaymentFor
    from sqlalchemy import select

    await init_db(os.environ["DATABASE_URL"])
    async with get_session() as session:
        pmt = await session.scalar(
            select(Payment).where(
                Payment.tenancy_id == 1122,
                Payment.for_type == PaymentFor.booking,
                Payment.is_void == False,
            )
        )
        if not pmt:
            print("No booking payment found for tenancy 1122")
            return
        print(f"Found payment id={pmt.id} amount={pmt.amount} mode={pmt.payment_mode}")
        pmt.payment_mode = PaymentMode.upi
        pmt.notes = "Advance collected at pre-booking (upi)"
        await session.commit()
        print(f"Updated payment {pmt.id} to UPI")

asyncio.run(main())
