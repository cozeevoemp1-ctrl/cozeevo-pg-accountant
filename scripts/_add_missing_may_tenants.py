"""Add 4 missing May tenants to DB (Chandraprakash, Mathew Koshy, Rama Krishnan, Akshitha Jawahar)."""
import asyncio, os, sys
from datetime import date
from decimal import Decimal
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv; load_dotenv()

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, text
from src.database.models import (
    Tenant, Tenancy, Payment, RentSchedule,
    TenancyStatus, PaymentMode, PaymentFor, RentStatus, StayType,
)

MAY = date(2026, 5, 1)

TENANTS_TO_ADD = [
    {
        "name": "Chandraprakash",
        "phone": "+919506064442",
        "gender": "Male",
        "room_id": 389,   # G20
        "checkin_date": date(2026, 5, 2),
        "agreed_rent": Decimal("22000"),
        "booking_amount": Decimal("5000"),
        "security_deposit": Decimal("22000"),
        "maintenance_fee": Decimal("5000"),
        "sharing_type": "single",
        "status": TenancyStatus.active,
        "notes": "Added from May source sheet import",
        "fix_staff_room": True,
        "payments": [
            {"amount": Decimal("28000"), "mode": PaymentMode.cash, "for_type": PaymentFor.rent,    "period": MAY,  "note": "May cash — source sheet"},
            {"amount": Decimal("5000"),  "mode": PaymentMode.upi,  "for_type": PaymentFor.booking, "period": None, "note": "Booking — source sheet"},
        ],
    },
    {
        "name": "Mathew Koshy",
        "phone": "+919446655101",
        "gender": "Male",
        "room_id": 279,   # 304
        "checkin_date": date(2026, 5, 3),
        "agreed_rent": Decimal("28000"),
        "booking_amount": Decimal("2000"),
        "security_deposit": Decimal("28000"),
        "maintenance_fee": Decimal("5000"),
        "sharing_type": "double",
        "status": TenancyStatus.active,
        "notes": "Added from May source sheet import",
        "payments": [
            {"amount": Decimal("44000"), "mode": PaymentMode.upi,  "for_type": PaymentFor.rent,    "period": MAY,  "note": "May UPI — source sheet"},
            {"amount": Decimal("2000"),  "mode": PaymentMode.cash, "for_type": PaymentFor.booking, "period": None, "note": "Booking — source sheet"},
        ],
    },
    {
        "name": "Rama Krishnan",
        "phone": "+919842378754",
        "gender": "Male",
        "room_id": 345,   # G09
        "checkin_date": date(2026, 6, 1),
        "agreed_rent": Decimal("9000"),
        "booking_amount": Decimal("2000"),
        "security_deposit": Decimal("9000"),
        "maintenance_fee": Decimal("5000"),
        "sharing_type": "triple",
        "status": TenancyStatus.no_show,
        "notes": "Check-in June 1. Added from May source sheet import",
        "payments": [
            {"amount": Decimal("2000"), "mode": PaymentMode.upi, "for_type": PaymentFor.booking, "period": None, "note": "Booking — source sheet"},
        ],
    },
    {
        "name": "Akshitha Jawahar",
        "phone": "+919500006551",
        "gender": "Female",
        "room_id": 264,   # 214
        "checkin_date": date(2026, 5, 3),
        "agreed_rent": Decimal("15000"),
        "booking_amount": Decimal("2000"),
        "security_deposit": Decimal("8000"),
        "maintenance_fee": Decimal("1500"),
        "sharing_type": "double",
        "status": TenancyStatus.active,
        "notes": "Added from May source sheet import",
        "payments": [
            {"amount": Decimal("2000"), "mode": PaymentMode.upi, "for_type": PaymentFor.booking, "period": None, "note": "Booking — source sheet"},
        ],
    },
]


async def main():
    url = os.environ["DATABASE_URL"]
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(url, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as session:
        for rec in TENANTS_TO_ADD:
            print(f"\n--- Adding {rec['name']} ---")

            if rec.get("fix_staff_room"):
                await session.execute(text("UPDATE rooms SET is_staff_room=false WHERE id=389"))
                print("  [ok] G20 is_staff_room -> false")

            existing_tenant = await session.scalar(
                select(Tenant).where(Tenant.phone == rec["phone"])
            )
            if existing_tenant:
                print(f"  [skip] Tenant exists: {existing_tenant.name} id={existing_tenant.id}")
                tenant = existing_tenant
            else:
                tenant = Tenant(
                    name=rec["name"],
                    phone=rec["phone"],
                    gender=rec["gender"],
                )
                session.add(tenant)
                await session.flush()
                print(f"  [ok] Created tenant id={tenant.id}")

            existing_tn = await session.scalar(
                select(Tenancy).where(
                    Tenancy.tenant_id == tenant.id,
                    Tenancy.status.in_([TenancyStatus.active, TenancyStatus.no_show]),
                )
            )
            if existing_tn:
                print(f"  [skip] Tenancy exists id={existing_tn.id}")
                tenancy = existing_tn
            else:
                tenancy = Tenancy(
                    tenant_id=tenant.id,
                    room_id=rec["room_id"],
                    stay_type=StayType.monthly,
                    status=rec["status"],
                    checkin_date=rec["checkin_date"],
                    agreed_rent=rec["agreed_rent"],
                    booking_amount=rec["booking_amount"],
                    security_deposit=rec["security_deposit"],
                    maintenance_fee=rec["maintenance_fee"],
                    sharing_type=rec["sharing_type"],
                    notes=rec["notes"],
                    org_id=1,
                )
                session.add(tenancy)
                await session.flush()
                print(f"  [ok] Created tenancy id={tenancy.id} status={rec['status'].value}")

            if rec["status"] == TenancyStatus.active:
                existing_rs = await session.scalar(
                    select(RentSchedule).where(
                        RentSchedule.tenancy_id == tenancy.id,
                        RentSchedule.period_month == MAY,
                    )
                )
                if not existing_rs:
                    rs = RentSchedule(
                        tenancy_id=tenancy.id,
                        period_month=MAY,
                        rent_due=rec["agreed_rent"],
                        maintenance_due=rec["maintenance_fee"],
                        status=RentStatus.pending,
                        due_date=MAY,
                        notes="Auto-created by _add_missing_may_tenants.py",
                        org_id=1,
                    )
                    session.add(rs)
                    print("  [ok] Created May rent_schedule")

            for pmt in rec["payments"]:
                existing_p = await session.scalar(
                    select(Payment).where(
                        Payment.tenancy_id == tenancy.id,
                        Payment.amount == pmt["amount"],
                        Payment.payment_mode == pmt["mode"],
                        Payment.for_type == pmt["for_type"],
                        Payment.is_void == False,
                    )
                )
                if existing_p:
                    print(f"  [skip] Payment exists: {pmt['mode']} {pmt['amount']}")
                    continue
                p = Payment(
                    tenancy_id=tenancy.id,
                    amount=pmt["amount"],
                    payment_date=pmt["period"] or date(2026, 5, 1),
                    payment_mode=pmt["mode"],
                    for_type=pmt["for_type"],
                    period_month=pmt["period"],
                    notes=pmt["note"],
                    org_id=1,
                )
                session.add(p)
                print(f"  [ok] Payment: {pmt['mode'].value} Rs.{pmt['amount']} ({pmt['for_type'].value})")

        await session.commit()
        print("\n\n** ALL COMMITTED **")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
