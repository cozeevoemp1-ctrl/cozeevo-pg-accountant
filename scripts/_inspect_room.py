"""Read-only: dump every onboarding session + tenancy for a given room number.
Usage: python scripts/_inspect_room.py 507
"""
import asyncio
import json
import os
import sys

from dotenv import load_dotenv
from sqlalchemy import select

load_dotenv()

from src.database.db_manager import init_db, get_session
from src.database.models import OnboardingSession, Room, Tenancy, Tenant


async def main(rn: str):
    await init_db(os.environ["DATABASE_URL"])
    async with get_session() as session:
        room = await session.scalar(select(Room).where(Room.room_number == rn))
        if not room:
            print(f"Room {rn} not found")
            return
        print(f"Room {rn}: id={room.id} max_occ={room.max_occupancy} staff={room.is_staff_room}")

        print("\n-- Tenancies --")
        rows = (await session.execute(
            select(Tenancy, Tenant).join(Tenant, Tenant.id == Tenancy.tenant_id)
            .where(Tenancy.room_id == room.id).order_by(Tenancy.id)
        )).all()
        for tc, t in rows:
            print(f"  tcy={tc.id} {t.name!r:22} phone={t.phone} status={tc.status.value} "
                  f"stay={tc.stay_type.value} checkin={tc.checkin_date} checkout={tc.checkout_date}")

        print("\n-- Onboarding sessions --")
        obs_rows = (await session.execute(
            select(OnboardingSession).where(OnboardingSession.room_id == room.id)
            .order_by(OnboardingSession.created_at)
        )).all()
        for (obs,) in obs_rows:
            td = json.loads(obs.tenant_data) if obs.tenant_data else {}
            print(f"  obs status={obs.status:14} tenancy_id={obs.tenancy_id} "
                  f"name={td.get('name','')!r} phone={obs.tenant_phone or td.get('phone','')} "
                  f"checkin={obs.checkin_date} approved_at={obs.approved_at}")
            print(f"      token={obs.token}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "507"))
