"""Read-only: rooms showing a FREE bed that are occupied by a SINGLE active tenant
in a multi-bed room and NOT marked premium. High rent => almost certainly a
whole-room/premium tenant whose sharing_type was never set (like 208, 607).

Lists them sorted by rent so the obvious premiums float to the top. Does NOT
auto-change anything — a genuine single regular tenant in a double IS a real free bed.
"""
import asyncio
import os
from collections import defaultdict

from dotenv import load_dotenv
from sqlalchemy import select

load_dotenv()

from src.database.db_manager import init_db, get_session
from src.database.models import Room, Tenancy, Tenant, TenancyStatus, StayType


async def main():
    await init_db(os.environ["DATABASE_URL"])
    async with get_session() as s:
        rooms = (await s.execute(
            select(Room).where(Room.is_staff_room == False, Room.room_number != "000",
                               Room.max_occupancy > 1)
        )).scalars().all()
        room_by_id = {r.id: r for r in rooms}

        rows = (await s.execute(
            select(Tenancy, Tenant).join(Tenant, Tenant.id == Tenancy.tenant_id)
            .where(Tenancy.status == TenancyStatus.active, Tenancy.room_id.in_(list(room_by_id)))
        )).all()

        occ = defaultdict(list)
        for tc, t in rows:
            occ[tc.room_id].append((tc, t))

        cands = []
        for rid, people in occ.items():
            r = room_by_id[rid]
            # premium-aware bed usage
            used = sum(r.max_occupancy if getattr(p[0].sharing_type, "value", p[0].sharing_type) == "premium" else 1 for p in people)
            if used >= r.max_occupancy:
                continue  # room reads full already
            # single active tenant, not premium -> candidate
            non_premium = [p for p in people if getattr(p[0].sharing_type, "value", p[0].sharing_type) != "premium"]
            if len(people) == 1 and non_premium:
                tc, t = people[0]
                cands.append((float(tc.agreed_rent or 0), r.room_number, r.max_occupancy,
                              t.name, tc.id, tc.stay_type.value,
                              getattr(tc.sharing_type, "value", tc.sharing_type)))

        cands.sort(reverse=True)
        print(f"Single-occupant multi-bed rooms showing a FREE bed (not premium): {len(cands)}")
        print(f"{'rent':>8}  {'room':5} {'max':>3}  {'stay':7} {'sharing':8} tenant (tcy)")
        for rent, rn, mo, name, tid, stay, sh in cands:
            flag = "  <-- likely PREMIUM" if rent >= 18000 else ""
            print(f"{rent:>8.0f}  {rn:5} {mo:>3}  {stay:7} {str(sh):8} {name} ({tid}){flag}")


if __name__ == "__main__":
    asyncio.run(main())
