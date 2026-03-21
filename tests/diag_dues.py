import asyncio, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dotenv import load_dotenv
load_dotenv()
os.environ['TEST_MODE'] = '1'
DB_URL = "postgresql+asyncpg://postgres:Anchorstrong123!@db.oxiqomoilqwfxjauxhzp.supabase.co:5432/postgres"

from datetime import date
from src.database.db_manager import init_db, get_db_session
from src.database.models import RentSchedule, Tenancy, TenancyStatus, RentStatus
from sqlalchemy import select, func

async def diag():
    await init_db(DB_URL)
    async for session in get_db_session():
        # Pending dues per month (active tenants, any period_month)
        rows = (await session.execute(
            select(RentSchedule.period_month, func.count().label('cnt'), func.sum(RentSchedule.rent_due).label('total'))
            .join(Tenancy, Tenancy.id == RentSchedule.tenancy_id)
            .where(
                RentSchedule.status.in_([RentStatus.pending, RentStatus.partial]),
                Tenancy.status == TenancyStatus.active,
            )
            .group_by(RentSchedule.period_month)
            .order_by(RentSchedule.period_month)
        )).all()

        print("\n=== Pending rent_schedule rows BY period_month (active tenants) ===")
        print(f"{'Period':<15} {'Rows':<8} {'rent_due sum':>14}")
        print("-" * 42)
        for r in rows:
            print(f"{r.period_month.strftime('%b %Y'):<15} {r.cnt:<8} {float(r.total):>14,.0f}")

        # Just March 2026 with checkin filter
        m = (await session.execute(
            select(func.count().label('cnt'), func.sum(RentSchedule.rent_due).label('total'))
            .join(Tenancy, Tenancy.id == RentSchedule.tenancy_id)
            .where(
                RentSchedule.status.in_([RentStatus.pending, RentStatus.partial]),
                Tenancy.status == TenancyStatus.active,
                Tenancy.checkin_date <= date(2026, 3, 31),
                RentSchedule.period_month == date(2026, 3, 1),
            )
        )).first()
        print(f"\nMarch 2026 ONLY (checkin <= Mar 31): {m.cnt} tenants  rent_due={float(m.total or 0):,.0f}")

        # Unique tenants with ANY pending dues (cumulative)
        uniq = (await session.execute(
            select(func.count(Tenancy.id.distinct()).label('cnt'))
            .join(RentSchedule, RentSchedule.tenancy_id == Tenancy.id)
            .where(
                RentSchedule.status.in_([RentStatus.pending, RentStatus.partial]),
                Tenancy.status == TenancyStatus.active,
                Tenancy.checkin_date <= date(2026, 3, 31),
                RentSchedule.period_month <= date(2026, 3, 31),
            )
        )).scalar()
        print(f"Unique tenants with ANY pending dues <= Mar 2026: {uniq}")

        break

asyncio.run(diag())
