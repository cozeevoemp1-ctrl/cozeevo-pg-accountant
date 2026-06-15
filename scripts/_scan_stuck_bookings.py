"""Read-only scan: onboarding sessions still in the Bookings list whose tenant is
ALREADY checked in (active tenancy) — i.e. checked in by Lokesh but the session was
never flipped to 'approved', so it lingers in Bookings.

Also the reverse: active tenancies in a room that has NO closed session (info only).
Matches by normalized phone (last 10 digits) and by obs.tenancy_id.
"""
import asyncio
import json
import os
import re

from dotenv import load_dotenv
from sqlalchemy import select

load_dotenv()

from src.database.db_manager import init_db, get_session
from src.database.models import OnboardingSession, Room, Tenancy, Tenant, TenancyStatus


def last10(p):
    d = re.sub(r"\D", "", p or "")
    return d[-10:] if len(d) >= 10 else d


async def main():
    await init_db(os.environ["DATABASE_URL"])
    async with get_session() as session:
        # All pending sessions shown in Bookings
        sessions = (await session.execute(
            select(OnboardingSession).where(
                OnboardingSession.status.in_(["pending_tenant", "pending_review"])
            )
        )).scalars().all()

        # All active tenancies (phone + room)
        active = (await session.execute(
            select(Tenancy, Tenant, Room)
            .join(Tenant, Tenant.id == Tenancy.tenant_id)
            .join(Room, Room.id == Tenancy.room_id)
            .where(Tenancy.status == TenancyStatus.active)
        )).all()
        active_by_phone = {}
        active_ids = set()
        for tc, t, r in active:
            active_ids.add(tc.id)
            ph = last10(t.phone)
            if ph:
                active_by_phone.setdefault(ph, []).append((tc.id, t.name, r.room_number))

        stuck = []
        for obs in sessions:
            td = json.loads(obs.tenant_data) if obs.tenant_data else {}
            name = td.get("name", "")
            phone = obs.tenant_phone or td.get("phone", "")
            room = await session.get(Room, obs.room_id) if obs.room_id else None
            rn = room.room_number if room else "?"
            reason = None
            if obs.tenancy_id and obs.tenancy_id in active_ids:
                reason = f"linked tenancy {obs.tenancy_id} is ACTIVE"
            else:
                m = active_by_phone.get(last10(phone))
                if m:
                    reason = "phone matches active " + ", ".join(f"{n}(rm {r}, tcy {i})" for i, n, r in m)
            if reason:
                stuck.append((rn, name, phone, obs.status, obs.token, reason))

        print(f"=== Pending sessions still in Bookings but tenant ALREADY checked in ({len(stuck)}) ===")
        for rn, name, phone, st, token, reason in sorted(stuck, key=lambda x: x[0]):
            print(f"  Room {rn:5} {name!r:24} status={st:14} -> {reason}")
            print(f"        token={token}")


if __name__ == "__main__":
    asyncio.run(main())
