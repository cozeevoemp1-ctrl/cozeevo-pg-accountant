"""Resolve May room assignments:
1. Mark Lakshmi Pathi (1083) as exited (checkout was May 7, still active)
2. Move Ganesh Magi (869) from room 219 -> 418
3. Add Arka -> room 219 (premium, checkin May 9)
4. Add Nikhil Mistry -> room 121 (double, checkin May 9)
"""
import asyncio, os, sys, math
from datetime import date
from decimal import Decimal
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv; load_dotenv()

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, text
from src.database.models import (
    Tenant, Tenancy, Payment, RentSchedule, AuditLog,
    TenancyStatus, PaymentMode, PaymentFor, RentStatus, StayType, SharingType,
)

MAY = date(2026, 5, 1)
ORG_ID = 1
DRY_RUN = "--dry-run" in sys.argv

engine = create_async_engine(os.environ["DATABASE_URL"])
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

def prorate(rent: int, checkin: date) -> int:
    days_in_month = 31  # May has 31 days
    days_stayed = days_in_month - checkin.day + 1
    return math.floor(rent * days_stayed / days_in_month)


async def main():
    async with AsyncSessionLocal() as db:
        # --- 1. Mark Lakshmi Pathi as exited ---
        lp = await db.get(Tenancy, 1083)
        if lp.status != TenancyStatus.exited:
            print(f"[1] Marking Lakshmi Pathi (1083) exited, checkout=2026-05-07")
            if not DRY_RUN:
                lp.status = TenancyStatus.exited
                lp.checkout_date = date(2026, 5, 7)
                db.add(AuditLog(
                    entity_type="tenancy", entity_id=1083,
                    entity_name="Lakshmi Pathi", field="status",
                    old_value="active", new_value="exited",
                    room_number="219", source="import", changed_by="Kiran",
                    note="Day-stay checkout May 7 — status was stale active",
                    org_id=ORG_ID,
                ))
        else:
            print(f"[1] Lakshmi Pathi already exited — skip")

        # --- 2. Move Ganesh Magi (869) from 219 -> 418 ---
        ganesh = await db.get(Tenancy, 869)
        room_418 = (await db.execute(
            select(__import__('src.database.models', fromlist=['Room']).Room)
            .where(__import__('src.database.models', fromlist=['Room']).Room.room_number == '418')
        )).scalars().first()
        if ganesh.room_id != room_418.id:
            print(f"[2] Moving Ganesh Magi (869) room_id {ganesh.room_id} -> {room_418.id} (418)")
            if not DRY_RUN:
                old_room_id = ganesh.room_id
                ganesh.room_id = room_418.id
                db.add(AuditLog(
                    entity_type="tenancy", entity_id=869,
                    entity_name="Ganesh Magi", field="room_id",
                    old_value=str(old_room_id), new_value=str(room_418.id),
                    room_number="418", source="import", changed_by="Kiran",
                    note="Corrected room assignment: was in 219, should be 418",
                    org_id=ORG_ID,
                ))
        else:
            print(f"[2] Ganesh Magi already in 418 — skip")

        if not DRY_RUN:
            await db.flush()

        # --- 3. Add Arka -> room 219, premium, checkin May 9 ---
        from src.database.models import Room
        room_219 = (await db.execute(select(Room).where(Room.room_number == '219'))).scalars().first()
        # Check if Arka already exists
        existing_arka = (await db.execute(
            select(Tenant).where(Tenant.phone == '+918017415671')
        )).scalars().first()

        if existing_arka:
            print(f"[3] Arka already exists (tenant {existing_arka.id}) — skip")
        else:
            print(f"[3] Adding Arka -> room 219 (premium, May 9)")
            arka_checkin = date(2026, 5, 9)
            arka_rent = 25000
            arka_prorated = prorate(arka_rent, arka_checkin)
            print(f"    Prorated May rent: floor(25000 * 23/31) = {arka_prorated}")
            if not DRY_RUN:
                arka_tenant = Tenant(
                    name="Arka", phone="+918017415671", gender="Male",
                )
                db.add(arka_tenant)
                await db.flush()

                arka_tenancy = Tenancy(
                    tenant_id=arka_tenant.id, room_id=room_219.id,
                    stay_type=StayType.monthly,
                    sharing_type=SharingType.premium,
                    status=TenancyStatus.active,
                    checkin_date=arka_checkin,
                    booking_amount=Decimal("5000"),
                    security_deposit=Decimal("25000"),
                    maintenance_fee=Decimal("5000"),
                    agreed_rent=Decimal(str(arka_rent)),
                    entered_by="Kiran",
                    org_id=ORG_ID,
                )
                db.add(arka_tenancy)
                await db.flush()

                arka_schedule = RentSchedule(
                    tenancy_id=arka_tenancy.id,
                    period_month=MAY,
                    rent_due=Decimal(str(arka_prorated)),
                    adjustment=Decimal("0"),
                    status=RentStatus.pending,
                    org_id=ORG_ID,
                )
                db.add(arka_schedule)

                # Booking payment Rs.5000 (mode unknown — using UPI as default)
                arka_booking = Payment(
                    tenancy_id=arka_tenancy.id,
                    amount=Decimal("5000"),
                    payment_date=date(2026, 5, 9),
                    payment_mode=PaymentMode.upi,
                    for_type=PaymentFor.booking,
                    period_month=None,
                    is_void=False,
                    notes="Booking advance from source sheet",
                    org_id=ORG_ID,
                )
                db.add(arka_booking)
                print(f"    Created tenant {arka_tenant.id}, tenancy {arka_tenancy.id}")

        # --- 4. Add Nikhil Mistry -> room 121, double, checkin May 9 ---
        room_121 = (await db.execute(select(Room).where(Room.room_number == '121'))).scalars().first()
        existing_nikhil = (await db.execute(
            select(Tenant).where(Tenant.phone == '+919313296623')
        )).scalars().first()

        if existing_nikhil:
            print(f"[4] Nikhil Mistry already exists (tenant {existing_nikhil.id}) — skip")
        else:
            print(f"[4] Adding Nikhil Mistry -> room 121 (double, May 9)")
            nm_checkin = date(2026, 5, 9)
            nm_rent = 14000
            nm_prorated = prorate(nm_rent, nm_checkin)
            print(f"    Prorated May rent: floor(14000 * 23/31) = {nm_prorated}")
            if not DRY_RUN:
                nm_tenant = Tenant(
                    name="Nikhil Mistry", phone="+919313296623", gender="Male",
                )
                db.add(nm_tenant)
                await db.flush()

                nm_tenancy = Tenancy(
                    tenant_id=nm_tenant.id, room_id=room_121.id,
                    stay_type=StayType.monthly,
                    sharing_type=SharingType.double,
                    status=TenancyStatus.active,
                    checkin_date=nm_checkin,
                    booking_amount=Decimal("14000"),
                    security_deposit=Decimal("14000"),
                    maintenance_fee=Decimal("5000"),
                    agreed_rent=Decimal(str(nm_rent)),
                    entered_by="Kiran",
                    org_id=ORG_ID,
                )
                db.add(nm_tenancy)
                await db.flush()

                nm_schedule = RentSchedule(
                    tenancy_id=nm_tenancy.id,
                    period_month=MAY,
                    rent_due=Decimal(str(nm_prorated)),
                    adjustment=Decimal("0"),
                    status=RentStatus.pending,
                    org_id=ORG_ID,
                )
                db.add(nm_schedule)

                # Booking payment Rs.14000 cash
                nm_booking = Payment(
                    tenancy_id=nm_tenancy.id,
                    amount=Decimal("14000"),
                    payment_date=date(2026, 5, 9),
                    payment_mode=PaymentMode.cash,
                    for_type=PaymentFor.booking,
                    period_month=None,
                    is_void=False,
                    notes="Booking advance from source sheet",
                    org_id=ORG_ID,
                )
                db.add(nm_booking)
                print(f"    Created tenant {nm_tenant.id}, tenancy {nm_tenancy.id}")

        if DRY_RUN:
            print("\n[DRY RUN] No changes committed.")
        else:
            await db.commit()
            print("\nAll changes committed.")


asyncio.run(main())
