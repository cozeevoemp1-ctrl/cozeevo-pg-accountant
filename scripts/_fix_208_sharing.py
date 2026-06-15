"""One-off: inspect / fix room 208 day-stay sharing_type.

Anish Singhal in 208 is a whole-room (premium) day-stay but stored without
sharing_type='premium', so the vacant panel counts it as 1 bed -> shows 1 free.

Read-only by default. Pass --write to set sharing_type='premium'.
"""
import asyncio
import os
import sys

from dotenv import load_dotenv
from sqlalchemy import select

load_dotenv()

from src.database.db_manager import init_db, get_session
from src.database.models import Room, Tenancy, Tenant, SharingType


async def main(write: bool):
    await init_db(os.environ["DATABASE_URL"])
    async with get_session() as session:
        room = await session.scalar(select(Room).where(Room.room_number == "208"))
        if not room:
            print("Room 208 not found")
            return
        print(f"Room 208: id={room.id} max_occupancy={room.max_occupancy} "
              f"is_staff_room={room.is_staff_room}")

        rows = (await session.execute(
            select(Tenancy, Tenant)
            .join(Tenant, Tenant.id == Tenancy.tenant_id)
            .where(Tenancy.room_id == room.id)
            .order_by(Tenancy.id)
        )).all()

        print(f"\n{len(rows)} tenancy row(s) in 208:")
        for tc, t in rows:
            st = getattr(tc.sharing_type, "value", tc.sharing_type)
            print(f"  tenancy={tc.id} {t.name!r:22} status={tc.status.value:8} "
                  f"stay={tc.stay_type.value:7} sharing_type={st} "
                  f"agreed_rent={tc.agreed_rent} booking={tc.booking_amount} "
                  f"checkin={tc.checkin_date} checkout={tc.checkout_date}")

        if not write:
            print("\n(read-only — pass --write to set sharing_type='premium' on active day-stays)")
            return

        changed = []
        for tc, t in rows:
            if tc.stay_type.value == "daily" and tc.status.value == "active":
                if getattr(tc.sharing_type, "value", tc.sharing_type) != "premium":
                    tc.sharing_type = SharingType.premium
                    changed.append((tc.id, t.name))
        if changed:
            print(f"\nSet sharing_type='premium' on: {changed}")
        else:
            print("\nNo active day-stay rows needed changing.")


if __name__ == "__main__":
    asyncio.run(main(write="--write" in sys.argv))
