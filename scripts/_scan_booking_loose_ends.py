"""Read-only: full sweep of booking/check-in loose ends across the DB.

A) Pending onboarding sessions whose tenant is ALREADY checked in (active tenancy)
   -> should be 'approved', stuck in Bookings.
B) Cancelled tenancies that still carry a NON-VOID booking/deposit/advance payment
   -> stranded money on a dead tenancy.
C) Same tenant with >1 non-exited tenancy in the same room (true duplicate live rows).
"""
import asyncio
import os
import re
from collections import defaultdict

from dotenv import load_dotenv
from sqlalchemy import select

load_dotenv()

from src.database.db_manager import init_db, get_session
from src.database.models import (
    OnboardingSession, Payment, PaymentFor, Room, Tenancy, Tenant, TenancyStatus,
)


def last10(p):
    d = re.sub(r"\D", "", p or "")
    return d[-10:] if len(d) >= 10 else d


async def main():
    await init_db(os.environ["DATABASE_URL"])
    async with get_session() as s:
        rooms = {r.id: r for r in (await s.execute(select(Room))).scalars()}

        # ---- A) pending sessions, tenant already active ----
        active = (await s.execute(
            select(Tenancy, Tenant).join(Tenant, Tenant.id == Tenancy.tenant_id)
            .where(Tenancy.status == TenancyStatus.active)
        )).all()
        active_ids = {tc.id for tc, _ in active}
        active_by_phone = defaultdict(list)
        for tc, t in active:
            active_by_phone[last10(t.phone)].append(tc.id)

        sessions = (await s.execute(
            select(OnboardingSession).where(
                OnboardingSession.status.in_(["pending_tenant", "pending_review"])
            )
        )).scalars().all()
        A = []
        for obs in sessions:
            rn = rooms[obs.room_id].room_number if obs.room_id in rooms else "?"
            if obs.tenancy_id and obs.tenancy_id in active_ids:
                A.append((rn, obs.status, obs.tenancy_id, obs.token))
        print(f"A) Pending sessions w/ ACTIVE linked tenancy (stuck in Bookings): {len(A)}")
        for rn, st, tid, tok in sorted(A):
            print(f"   room {rn:5} status={st:14} tenancy={tid} token={tok[:8]}")

        # ---- B) cancelled tenancies w/ non-void booking/deposit payment ----
        cancelled = (await s.execute(
            select(Tenancy, Tenant).join(Tenant, Tenant.id == Tenancy.tenant_id)
            .where(Tenancy.status == TenancyStatus.cancelled)
        )).all()
        B = []
        for tc, t in cancelled:
            pmts = (await s.execute(
                select(Payment).where(Payment.tenancy_id == tc.id, Payment.is_void == False)
            )).scalars().all()
            if pmts:
                rn = rooms[tc.room_id].room_number if tc.room_id in rooms else "?"
                # is there a live sibling (active/no_show) for same tenant+room?
                sib = (await s.execute(
                    select(Tenancy.id, Tenancy.status).where(
                        Tenancy.tenant_id == tc.tenant_id,
                        Tenancy.room_id == tc.room_id,
                        Tenancy.status.in_([TenancyStatus.active, TenancyStatus.no_show]),
                    )
                )).all()
                B.append((rn, tc.id, t.name, pmts, sib))
        print(f"\nB) CANCELLED tenancies carrying non-void payments (stranded money): {len(B)}")
        for rn, tid, name, pmts, sib in sorted(B, key=lambda x: x[0]):
            sibtxt = ", ".join(f"{i}({st.value})" for i, st in sib) or "NONE"
            print(f"   room {rn:5} cancelled-tcy={tid} {name!r:22} live-sibling=[{sibtxt}]")
            for p in pmts:
                print(f"       pmt {p.id} amt={p.amount} for={p.for_type.value if p.for_type else None} mode={p.payment_mode}")

        # ---- C) duplicate live tenancies (same tenant+room, >1 non-exited) ----
        live = (await s.execute(
            select(Tenancy, Tenant).join(Tenant, Tenant.id == Tenancy.tenant_id)
            .where(Tenancy.status.in_([TenancyStatus.active, TenancyStatus.no_show]))
        )).all()
        by_key = defaultdict(list)
        for tc, t in live:
            by_key[(tc.tenant_id, tc.room_id)].append((tc.id, tc.status.value, t.name))
        C = {k: v for k, v in by_key.items() if len(v) > 1}
        print(f"\nC) Same tenant+room with >1 LIVE tenancy (true duplicates): {len(C)}")
        for (tid, rid), rows in C.items():
            rn = rooms[rid].room_number if rid in rooms else "?"
            print(f"   room {rn:5} {rows[0][2]!r}: {[(i,st) for i,st,_ in rows]}")


if __name__ == "__main__":
    asyncio.run(main())
