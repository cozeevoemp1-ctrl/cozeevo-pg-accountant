"""Deep dive — why does March show 49 tenants with pending dues?"""
import asyncio, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dotenv import load_dotenv
load_dotenv()
os.environ['TEST_MODE'] = '1'
DB_URL = "postgresql+asyncpg://postgres:Anchorstrong123!@db.oxiqomoilqwfxjauxhzp.supabase.co:5432/postgres"

from datetime import date
from src.database.db_manager import init_db, get_db_session
from src.database.models import RentSchedule, Tenancy, TenancyStatus, RentStatus, Tenant, Room
from sqlalchemy import select, func

async def diag():
    await init_db(DB_URL)
    async for session in get_db_session():

        # March pending: split by check-in month
        rows = (await session.execute(
            select(
                Tenant.name,
                Room.room_number,
                Tenancy.checkin_date,
                RentSchedule.rent_due,
                RentSchedule.status,
            )
            .join(Tenancy, Tenancy.id == RentSchedule.tenancy_id)
            .join(Tenant, Tenant.id == Tenancy.tenant_id)
            .join(Room, Room.id == Tenancy.room_id)
            .where(
                RentSchedule.status.in_([RentStatus.pending, RentStatus.partial]),
                Tenancy.status == TenancyStatus.active,
                Tenancy.checkin_date <= date(2026, 3, 31),
                RentSchedule.period_month == date(2026, 3, 1),
            )
            .order_by(Tenancy.checkin_date.desc())
        )).all()

        print(f"\n=== March 2026 pending — {len(rows)} entries ===")
        by_checkin = {}
        for name, room, checkin, rent, status in rows:
            mo = checkin.strftime('%b %Y') if checkin else 'unknown'
            by_checkin.setdefault(mo, []).append((name, room, float(rent or 0)))

        print("\n--- Grouped by checkin month ---")
        for mo, tenants in sorted(by_checkin.items()):
            total = sum(r for _,_,r in tenants)
            print(f"  Checked in {mo}: {len(tenants)} tenants  Rs.{total:,.0f}")
            for name, room, rent in tenants[:5]:
                print(f"    {name} | {room} | Rs.{rent:,.0f}")
            if len(tenants) > 5:
                print(f"    ... and {len(tenants)-5} more")

        # Also show: how many active tenants have NO March schedule at all?
        active_count = await session.scalar(
            select(func.count(Tenancy.id))
            .where(Tenancy.status == TenancyStatus.active, Tenancy.checkin_date <= date(2026,3,31))
        )
        march_scheduled = await session.scalar(
            select(func.count(Tenancy.id.distinct()))
            .join(RentSchedule, RentSchedule.tenancy_id == Tenancy.id)
            .where(
                Tenancy.status == TenancyStatus.active,
                Tenancy.checkin_date <= date(2026,3,31),
                RentSchedule.period_month == date(2026,3,1),
            )
        )
        march_paid = await session.scalar(
            select(func.count(Tenancy.id.distinct()))
            .join(RentSchedule, RentSchedule.tenancy_id == Tenancy.id)
            .where(
                Tenancy.status == TenancyStatus.active,
                Tenancy.checkin_date <= date(2026,3,31),
                RentSchedule.period_month == date(2026,3,1),
                RentSchedule.status == RentStatus.paid,
            )
        )

        print(f"\n=== March coverage ===")
        print(f"Active tenants checked in by Mar 31: {active_count}")
        print(f"Have a March rent_schedule row:       {march_scheduled}")
        print(f"  - paid:    {march_paid}")
        print(f"  - pending: {len(rows)}")
        print(f"  - no row:  {active_count - (march_scheduled or 0)}")

        break

asyncio.run(diag())
