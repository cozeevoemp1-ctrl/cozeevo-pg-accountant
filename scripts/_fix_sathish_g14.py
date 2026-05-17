"""
One-off: fix Sathish K (Room G14) post-checkin data.

Problems:
1. RS.rent_due = agreed_rent (4600) instead of prorated for May 17 check-in.
   Correct value = floor(4600 * 15/31) = 2225  (days 17..31 = 15 days)
2. booking_amount (9500 advance) was never recorded as a Payment row.
   deposit_due formula now uses booking_amount directly, but the advance
   still needs to appear in payment history.

Run with:
    python scripts/_fix_sathish_g14.py --write
"""
import asyncio
import math
import sys
from datetime import date
from decimal import Decimal

WRITE = "--write" in sys.argv

async def main():
    from src.database.db_manager import get_session
    from src.database.models import Tenancy, Tenant, Room, RentSchedule, Payment, PaymentFor, PaymentMode
    from sqlalchemy import select, func

    async with get_session() as session:
        # Find Sathish K in G14
        row = (await session.execute(
            select(Tenancy, Tenant, Room)
            .join(Tenant, Tenant.id == Tenancy.tenant_id)
            .join(Room, Room.id == Tenancy.room_id)
            .where(
                func.lower(Room.room_number) == "g14",
                Tenancy.status.in_(["active", "no_show"]),
            )
            .order_by(Tenancy.id.desc())
        )).first()

        if not row:
            print("ERROR: No active tenancy found in room G14")
            return

        tenancy, tenant, room = row
        print(f"Tenant : {tenant.name}  (tenancy {tenancy.id})")
        print(f"Room   : {room.room_number}")
        print(f"Checkin: {tenancy.checkin_date}")
        print(f"Rent   : {tenancy.agreed_rent}  Deposit: {tenancy.security_deposit}  Booking: {tenancy.booking_amount}")

        checkin = tenancy.checkin_date
        period = checkin.replace(day=1)  # 2026-05-01
        import calendar
        days_in_month = calendar.monthrange(checkin.year, checkin.month)[1]
        days_billed = days_in_month - checkin.day + 1
        prorated = math.floor(float(tenancy.agreed_rent) * days_billed / days_in_month)
        deposit = float(tenancy.security_deposit or 0)
        booking = float(tenancy.booking_amount or 0)
        correct_rent_due = max(0, prorated + deposit - booking)

        print(f"\nProration: {days_billed}/{days_in_month} days  → prorated={prorated}")
        print(f"RS.rent_due should be: prorated({prorated}) + deposit({deposit}) - booking({booking}) = {correct_rent_due}")

        # Check existing RS
        rs = await session.scalar(
            select(RentSchedule).where(
                RentSchedule.tenancy_id == tenancy.id,
                RentSchedule.period_month == period,
            )
        )
        if rs:
            print(f"\nExisting RS.rent_due = {rs.rent_due}  (correct={correct_rent_due})")
        else:
            print(f"\nNo RS row for {period}  — will create with rent_due={correct_rent_due}")

        # Check existing booking payment
        existing_booking_pmt = await session.scalar(
            select(Payment).where(
                Payment.tenancy_id == tenancy.id,
                Payment.for_type == PaymentFor.booking,
                Payment.is_void == False,
            )
        )
        if existing_booking_pmt:
            print(f"Booking payment already exists: id={existing_booking_pmt.id} amount={existing_booking_pmt.amount}")
        else:
            print(f"No booking payment — will create Payment(for_type=booking, amount={booking})")

        if not WRITE:
            print("\n[DRY RUN] Add --write to apply changes")
            return

        # Fix RS
        if rs:
            if float(rs.rent_due) != correct_rent_due:
                rs.rent_due = Decimal(str(correct_rent_due))
                print(f"Updated RS.rent_due: {float(rs.rent_due)} → {correct_rent_due}")
            else:
                print("RS.rent_due already correct, no change")
        else:
            from src.database.models import RentStatus
            session.add(RentSchedule(
                tenancy_id=tenancy.id,
                period_month=period,
                rent_due=Decimal(str(correct_rent_due)),
                maintenance_due=0,
                status=RentStatus.pending,
                due_date=period,
            ))
            print(f"Created RS for {period} with rent_due={correct_rent_due}")

        # Add booking payment if missing
        if not existing_booking_pmt and booking > 0:
            advance_mode = "upi"  # default; adjust if needed
            session.add(Payment(
                tenancy_id=tenancy.id,
                amount=Decimal(str(booking)),
                payment_date=checkin,
                payment_mode=PaymentMode.upi if advance_mode == "upi" else PaymentMode.cash,
                for_type=PaymentFor.booking,
                period_month=None,
                notes=f"Advance/booking payment (fix script — recorded at check-in)",
            ))
            print(f"Created booking Payment of {booking}")

        await session.commit()
        print("\nDone — committed.")

if __name__ == "__main__":
    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from dotenv import load_dotenv
    load_dotenv()
    asyncio.run(main())
