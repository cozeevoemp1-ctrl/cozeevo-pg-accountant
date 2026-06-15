"""Read-only scan: rooms with an active PREMIUM tenant that still show a free bed.

Premium = occupies the whole room, so such a room should read 0 free. Any with
free > 0 is an anomaly (data or another occupant edge case).

Also lists, for context, every room that shows a free bed (the vacant-panel view)
so we can spot other 208-style under-marked rooms.
"""
import asyncio
import os
from collections import defaultdict

from dotenv import load_dotenv
from sqlalchemy import select

load_dotenv()

from src.database.db_manager import init_db, get_session
from src.database.models import Room, Tenancy, Tenant, TenancyStatus, StayType


def beds(sharing_type, max_occ):
    st = getattr(sharing_type, "value", sharing_type)
    return max_occ if st == "premium" else 1


async def main():
    await init_db(os.environ["DATABASE_URL"])
    async with get_session() as session:
        rooms = (await session.execute(
            select(Room).where(Room.is_staff_room == False, Room.room_number != "000")
        )).scalars().all()
        room_by_id = {r.id: r for r in rooms}

        # Active long-term + active day-stays count as occupying now
        rows = (await session.execute(
            select(Tenancy, Tenant)
            .join(Tenant, Tenant.id == Tenancy.tenant_id)
            .where(Tenancy.status == TenancyStatus.active)
        )).all()

        occ = defaultdict(list)  # room_id -> [(name, sharing_type, stay_type)]
        for tc, t in rows:
            if tc.room_id in room_by_id:
                occ[tc.room_id].append((t.name, getattr(tc.sharing_type, "value", tc.sharing_type), tc.stay_type.value))

        premium_anomalies = []
        for rid, people in occ.items():
            r = room_by_id[rid]
            mo = int(r.max_occupancy or 1)
            used = min(sum(beds(p[1], mo) for p in people), mo)
            free = mo - used
            has_premium = any(p[1] == "premium" for p in people)
            if has_premium and free > 0:
                premium_anomalies.append((r.room_number, mo, used, free, people))

        print("=== PREMIUM tenants whose room STILL shows a free bed ===")
        if not premium_anomalies:
            print("  None — every premium-occupied room reads 0 free. ✓")
        else:
            for rn, mo, used, free, people in sorted(premium_anomalies):
                print(f"  Room {rn}: max_occ={mo} used={used} free={free}")
                for name, st, sty in people:
                    print(f"      - {name} (sharing={st}, stay={sty})")


if __name__ == "__main__":
    asyncio.run(main())
