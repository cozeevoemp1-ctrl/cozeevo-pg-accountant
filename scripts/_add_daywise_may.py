"""Add active day-wise tenants from source sheet Day Wise tab (May 2026).
Also fixes Shashank B V (G18) stale active record → exited.

Usage:
    python scripts/_add_daywise_may.py          # dry run
    python scripts/_add_daywise_may.py --write
"""
import asyncio, argparse, os, sys
from datetime import date
from decimal import Decimal
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv; load_dotenv()

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, text
from src.database.models import (
    Tenant, Tenancy, Payment,
    TenancyStatus, PaymentMode, PaymentFor, StayType,
)

MAY3  = date(2026, 5, 3)
MAY4  = date(2026, 5, 4)
MAY6  = date(2026, 5, 6)
MAY16 = date(2026, 5, 16)  # Rayirth checkout (13 nights = May 3 + 13 = May 16)
MAY25 = date(2026, 5, 25)  # Avirneni checkout

# Room IDs from DB
ROOM_IDS = {
    "G18": 354, "G17": 353,
    "219": 269, "510": 383,
}

# Active day-wise tenants to add (source sheet, not EXIT, not Cancelled, not blacklisted)
DAYWISE_TENANTS = [
    {
        "name": "Rayirth",
        "phone": "+919444171191",
        "gender": "Male",
        "room_id": ROOM_IDS["G18"],
        "checkin_date": MAY3,
        "checkout_date": MAY16,
        "agreed_rent": Decimal("1000"),   # per day
        "booking_amount": Decimal("1000"),
        "status": TenancyStatus.active,
        "notes": "Source sheet Day Wise tab — May 3-15",
        "payment": {"amount": Decimal("1000"), "mode": PaymentMode.cash, "date": MAY3},
    },
    {
        "name": "Lakshmi Pathi",
        "phone": "+919703199955",
        "gender": "Female",
        "room_id": ROOM_IDS["219"],
        "checkin_date": MAY4,
        "checkout_date": date(2026, 5, 7),   # May 4,5,6 = 3 nights
        "agreed_rent": Decimal("1200"),
        "booking_amount": Decimal("1200"),
        "status": TenancyStatus.no_show,
        "notes": "No-show for May 4,5,6. Source sheet Day Wise tab",
        "payment": {"amount": Decimal("1200"), "mode": PaymentMode.cash, "date": MAY4},
    },
    {
        "name": "Chinchu David",
        "phone": "+919019924645",
        "gender": "Male",
        "room_id": ROOM_IDS["G17"],
        "checkin_date": MAY4,
        "checkout_date": date(2026, 5, 7),   # may4,5,6 = 3 nights
        "agreed_rent": Decimal("1200"),
        "booking_amount": Decimal("3100"),   # 3×1200 - 500 discount = 3100
        "status": TenancyStatus.no_show,
        "notes": "No-show for May 4,5,6. 500 discount applied. Source sheet Day Wise tab",
        "payment": {"amount": Decimal("3100"), "mode": PaymentMode.upi, "date": MAY3},
    },
    {
        "name": "Avirneni Karthik",
        "phone": "+919298009215",
        "gender": "Male",
        "room_id": ROOM_IDS["510"],
        "checkin_date": MAY6,
        "checkout_date": MAY25,             # May 6-25 = 20 nights
        "agreed_rent": Decimal("700"),
        "booking_amount": Decimal("2600"),
        "status": TenancyStatus.active,
        "notes": "Checked in May 6. Source sheet Day Wise tab",
        "payment": {"amount": Decimal("2600"), "mode": PaymentMode.upi, "date": MAY6},
    },
]


async def run(write: bool):
    url = os.environ["DATABASE_URL"]
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(url, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as session:
        # Fix Shashank B V stale active G18 record
        shashank = await session.scalar(
            select(Tenancy).where(
                Tenancy.id == (
                    select(Tenancy.id)
                    .join(Tenant, Tenant.id == Tenancy.tenant_id)
                    .where(Tenant.phone == "+919482874334")
                    .scalar_subquery()
                )
            )
        )
        shashank_t = await session.scalar(
            select(Tenant).where(Tenant.phone == "+919482874334")
        )
        if shashank_t:
            shashank_tn = await session.scalar(
                select(Tenancy).where(
                    Tenancy.tenant_id == shashank_t.id,
                    Tenancy.status == TenancyStatus.active,
                )
            )
            if shashank_tn:
                if write:
                    shashank_tn.status = TenancyStatus.exited
                    shashank_tn.checkout_date = date(2026, 4, 28)
                print(f"{'[ok]' if write else '[DRY]'} Shashank B V G18: active -> exited (checkout Apr 28)")
            else:
                print("  Shashank B V: no active tenancy found (already fixed?)")
        else:
            print("  Shashank B V: tenant not found in DB")

        print()

        for rec in DAYWISE_TENANTS:
            print(f"--- {rec['name']} ---")

            # Check existing tenant by phone
            tenant = await session.scalar(
                select(Tenant).where(Tenant.phone == rec["phone"])
            )
            if tenant:
                print(f"  Tenant exists: {tenant.name} id={tenant.id}")
            else:
                if write:
                    tenant = Tenant(name=rec["name"], phone=rec["phone"], gender=rec["gender"])
                    session.add(tenant)
                    await session.flush()
                print(f"  {'[ok] Created' if write else '[DRY] Would create'} tenant {rec['name']}")
                if not write:
                    continue

            # Check existing active/no_show tenancy
            existing_tn = await session.scalar(
                select(Tenancy).where(
                    Tenancy.tenant_id == tenant.id,
                    Tenancy.status.in_([TenancyStatus.active, TenancyStatus.no_show]),
                )
            )
            if existing_tn:
                print(f"  [skip] Tenancy exists id={existing_tn.id} status={existing_tn.status.value}")
                continue

            if write:
                tenancy = Tenancy(
                    tenant_id=tenant.id,
                    room_id=rec["room_id"],
                    stay_type=StayType.daily,
                    status=rec["status"],
                    checkin_date=rec["checkin_date"],
                    checkout_date=rec["checkout_date"],
                    agreed_rent=rec["agreed_rent"],
                    booking_amount=rec["booking_amount"],
                    security_deposit=Decimal("0"),
                    maintenance_fee=Decimal("0"),
                    notes=rec["notes"],
                    org_id=1,
                )
                session.add(tenancy)
                await session.flush()

                p = rec["payment"]
                payment = Payment(
                    tenancy_id=tenancy.id,
                    amount=p["amount"],
                    payment_date=p["date"],
                    payment_mode=p["mode"],
                    for_type=PaymentFor.booking,
                    period_month=None,
                    notes="Day-wise booking — source sheet import",
                    org_id=1,
                )
                session.add(payment)
                print(f"  [ok] Created tenancy id={tenancy.id} ({rec['status'].value}) + payment {p['mode'].value} Rs.{p['amount']}")
            else:
                print(f"  [DRY] Would create {rec['status'].value} tenancy + payment {rec['payment']['mode']} Rs.{rec['payment']['amount']}")

        if write:
            await session.commit()
            print("\n** ALL COMMITTED **")
        else:
            print("\n** DRY RUN — pass --write to commit **")

    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.write))
