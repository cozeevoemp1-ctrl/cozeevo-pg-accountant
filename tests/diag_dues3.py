"""Verify corrected dues numbers before applying fix."""
import asyncio, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dotenv import load_dotenv
load_dotenv()
os.environ['TEST_MODE'] = '1'
DB_URL = "postgresql+asyncpg://postgres:Anchorstrong123!@db.oxiqomoilqwfxjauxhzp.supabase.co:5432/postgres"

from datetime import date
from src.database.db_manager import init_db, get_db_session
from src.database.models import RentSchedule, Tenancy, TenancyStatus, RentStatus, Tenant, Room
from sqlalchemy import select, func, and_
from src.api.dashboard_router import _paid_subquery

async def diag():
    await init_db(DB_URL)
    async for session in get_db_session():

        months = [
            (11, 2025), (12, 2025), (1, 2026), (2, 2026), (3, 2026),
        ]

        paid_sq = _paid_subquery()
        _outstanding = (
            RentSchedule.rent_due + RentSchedule.maintenance_due + RentSchedule.adjustment
            - func.coalesce(paid_sq.c.paid, 0)
        )

        print(f"\n{'Month':<12} {'Old (cumul,any checkin)':<28} {'NEW (this month, checkin<start)':}")
        print("-" * 72)

        for m, y in months:
            from_date = date(y, m, 1)
            import calendar
            to_date = date(y, m, calendar.monthrange(y, m)[1])

            # OLD: cumulative, checkin <= to_date
            old = (await session.execute(
                select(func.count(Tenant.name.distinct()).label('cnt'),
                       func.sum(_outstanding).label('total'))
                .join(Tenancy, Tenancy.id == RentSchedule.tenancy_id)
                .join(Tenant, Tenant.id == Tenancy.tenant_id)
                .outerjoin(paid_sq, and_(
                    paid_sq.c.tenancy_id == RentSchedule.tenancy_id,
                    paid_sq.c.period_month == RentSchedule.period_month,
                ))
                .where(
                    RentSchedule.status.in_([RentStatus.pending, RentStatus.partial]),
                    RentSchedule.period_month <= to_date,
                    Tenancy.status == TenancyStatus.active,
                    Tenancy.checkin_date <= to_date,
                )
            )).first()

            # NEW: only this month, checkin strictly before month start
            new = (await session.execute(
                select(func.count(Tenant.name.distinct()).label('cnt'),
                       func.sum(_outstanding).label('total'))
                .join(Tenancy, Tenancy.id == RentSchedule.tenancy_id)
                .join(Tenant, Tenant.id == Tenancy.tenant_id)
                .outerjoin(paid_sq, and_(
                    paid_sq.c.tenancy_id == RentSchedule.tenancy_id,
                    paid_sq.c.period_month == RentSchedule.period_month,
                ))
                .where(
                    RentSchedule.status.in_([RentStatus.pending, RentStatus.partial]),
                    RentSchedule.period_month == from_date,
                    Tenancy.status == TenancyStatus.active,
                    Tenancy.checkin_date < from_date,
                )
            )).first()

            o_t = float(old.total or 0)
            n_t = float(new.total or 0)
            print(f"{from_date.strftime('%b %Y'):<12} {old.cnt} tenants  Rs.{o_t:>9,.0f}     {new.cnt} tenants  Rs.{n_t:>9,.0f}")

        break

asyncio.run(diag())
