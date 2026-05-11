"""
One-shot: Add Akshay Kothari (522, June booking) + P.N.Charan (510, active May 5)
+ create missing checkout_record for Lakshmi Pathi (tenancy 1083).
"""
import asyncio, os, sys
from datetime import date
from decimal import Decimal
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv; load_dotenv(dotenv_path='.env')

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import (
    Tenant, Tenancy, Payment, RentSchedule, CheckoutRecord,
    TenancyStatus, PaymentMode, PaymentFor, RentStatus,
)

MAY  = date(2026, 5, 1)
JUN  = date(2026, 6, 1)

async def run(write: bool):
    url = os.environ["DATABASE_URL"].replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(url, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as session:
        # ── 1. Lakshmi Pathi checkout_record ─────────────────────────────────
        existing_cr = await session.scalar(
            select(CheckoutRecord).where(CheckoutRecord.tenancy_id == 1083)
        )
        if existing_cr:
            print("SKIP: Lakshmi Pathi checkout_record already exists")
        else:
            print("ADD: checkout_record for Lakshmi Pathi (tenancy 1083, exit May 7, no refund)")
            if write:
                session.add(CheckoutRecord(
                    tenancy_id=1083,
                    actual_exit_date=date(2026, 5, 7),
                    deposit_refunded_amount=Decimal('0'),
                    cupboard_key_returned=True,
                    main_key_returned=True,
                    room_condition_ok=True,
                    recorded_by="import",
                    damage_notes="Day-wise guest, no deposit taken",
                ))

        # ── 2. Akshay Kothari — room 522, June 1 booking ─────────────────────
        existing_ak = await session.scalar(
            select(Tenant).where(Tenant.phone == '+917795387088')
        )
        if existing_ak:
            print("SKIP: Akshay Kothari already in DB (phone +917795387088)")
        else:
            print("ADD: Akshay Kothari — room 522, check-in Jun 1, no_show, rent ₹14,000")
            if write:
                tenant_ak = Tenant(
                    name="Akshay Kothari",
                    phone="+917795387088",
                    gender="male",
                )
                session.add(tenant_ak)
                await session.flush()

                tenancy_ak = Tenancy(
                    tenant_id=tenant_ak.id,
                    room_id=408,  # room 522
                    checkin_date=JUN,
                    agreed_rent=Decimal('14000'),
                    security_deposit=Decimal('14000'),
                    maintenance_fee=Decimal('5000'),
                    booking_amount=Decimal('2000'),
                    status=TenancyStatus.no_show,
                    stay_type='monthly',
                )
                session.add(tenancy_ak)
                await session.flush()

                # ₹2,000 booking advance (May UPI)
                session.add(Payment(
                    tenancy_id=tenancy_ak.id,
                    amount=Decimal('2000'),
                    payment_date=MAY,
                    payment_mode=PaymentMode.upi,
                    for_type=PaymentFor.booking,
                    notes="Booking advance — source sheet May UPI col",
                ))

                # RentSchedule for June
                session.add(RentSchedule(
                    tenancy_id=tenancy_ak.id,
                    period_month=JUN,
                    rent_due=Decimal('14000'),
                    maintenance_due=Decimal('0'),
                    status=RentStatus.pending,
                    due_date=JUN,
                ))

        # ── 3. P.N.Charan — room 510, active May 5 ───────────────────────────
        existing_pn = await session.scalar(
            select(Tenant).where(Tenant.phone == '+919980896296')
        )
        if existing_pn:
            print("SKIP: P.N.Charan already in DB (phone +919980896296)")
        else:
            print("ADD: P.N.Charan — room 510, check-in May 5, active, rent ₹12,500")
            if write:
                tenant_pn = Tenant(
                    name="P.N.Charan",
                    phone="+919980896296",
                    gender="male",
                )
                session.add(tenant_pn)
                await session.flush()

                tenancy_pn = Tenancy(
                    tenant_id=tenant_pn.id,
                    room_id=383,  # room 510
                    checkin_date=date(2026, 5, 5),
                    agreed_rent=Decimal('12500'),
                    security_deposit=Decimal('0'),
                    maintenance_fee=Decimal('1500'),
                    booking_amount=Decimal('2000'),
                    status=TenancyStatus.active,
                    stay_type='monthly',
                )
                session.add(tenancy_pn)
                await session.flush()

                # ₹5,000 UPI + ₹2,000 cash for May
                session.add(Payment(
                    tenancy_id=tenancy_pn.id,
                    amount=Decimal('5000'),
                    payment_date=MAY,
                    payment_mode=PaymentMode.upi,
                    for_type=PaymentFor.rent,
                    period_month=MAY,
                    notes="May source sheet [Z/AA import]",
                ))
                session.add(Payment(
                    tenancy_id=tenancy_pn.id,
                    amount=Decimal('2000'),
                    payment_date=MAY,
                    payment_mode=PaymentMode.cash,
                    for_type=PaymentFor.rent,
                    period_month=MAY,
                    notes="May source sheet [Z/AA import]",
                ))

                # RentSchedule for May (prorated — joined May 5, 27 days)
                session.add(RentSchedule(
                    tenancy_id=tenancy_pn.id,
                    period_month=MAY,
                    rent_due=Decimal('12500'),
                    maintenance_due=Decimal('0'),
                    status=RentStatus.pending,
                    due_date=MAY,
                    notes="Check-in May 5 — consider prorating 27/31 days if needed",
                ))

        if write:
            await session.commit()
            print("\n** COMMITTED **")
        else:
            print("\n** DRY RUN **")

    await engine.dispose()


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--write", action="store_true")
    args = p.parse_args()
    asyncio.run(run(args.write))
