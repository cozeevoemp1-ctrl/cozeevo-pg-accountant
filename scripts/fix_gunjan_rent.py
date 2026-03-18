"""
One-off: update Gunjan (room 203 THOR) rent from 12800 → 15000
from Feb 2026 onwards (as per spreadsheet column "From 1st FEB").

Run on VPS:
    source venv/bin/activate
    python scripts/fix_gunjan_rent.py
"""
import asyncio
from datetime import date
from decimal import Decimal
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from src.database.config import DATABASE_URL
from src.database.models import Tenant, Tenancy, RentSchedule


NEW_RENT = Decimal("15000")
FEB_2026 = date(2026, 2, 1)


async def main() -> None:
    engine = create_async_engine(DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # Find Gunjan's tenancy
        row = await session.execute(
            select(Tenant.id, Tenant.name, Tenancy.id, Tenancy.agreed_rent, Tenancy.room_id)
            .join(Tenancy, Tenancy.tenant_id == Tenant.id)
            .where(Tenant.name.ilike("%gunjan%"), Tenancy.status == "active")
        )
        result = row.first()
        if not result:
            print("ERROR: Gunjan not found or not active")
            return

        t_id, t_name, tenancy_id, current_rent, room_id = result
        print(f"Found: {t_name}  tenancy_id={tenancy_id}  current agreed_rent={current_rent}")

        # Update agreed_rent on tenancy
        await session.execute(
            update(Tenancy)
            .where(Tenancy.id == tenancy_id)
            .values(agreed_rent=NEW_RENT)
        )
        print(f"  ✓ tenancy.agreed_rent → {NEW_RENT}")

        # Update rent_schedule rows for Feb 2026 onwards
        rs_rows = await session.execute(
            select(RentSchedule)
            .where(
                RentSchedule.tenancy_id == tenancy_id,
                RentSchedule.period_month >= FEB_2026,
            )
        )
        updated = 0
        for rs in rs_rows.scalars().all():
            print(f"  schedule {rs.period_month}: {rs.rent_due} → {NEW_RENT}")
            rs.rent_due = NEW_RENT
            updated += 1

        await session.commit()
        print(f"\nDone. Updated agreed_rent + {updated} rent_schedule row(s).")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
