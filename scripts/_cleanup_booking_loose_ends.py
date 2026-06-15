"""Cleanup the SAFE, current-period booking loose ends (audited).

  1. 5 pending sessions whose tenant is already ACTIVE -> status='approved'
     (208,309,503,607,617). They leave the Bookings list; reality unchanged.
  2. Room 507 Santosh: void old ₹1000 advance pmt 21360 on cancelled tcy 1199
     (re-booking with a fresh ₹1000 on live tcy 1207 supersedes it).
  3. Room 618 SHASHANK: cancel leftover no_show tcy 1216 (1217 is the live active one),
     and mark its rent_schedule rows na.

Does NOT touch the 14 historical/frozen cancelled tenancies or G15 Muthu (2 active) —
those need individual review. Read-only by default; pass --write to apply.
"""
import asyncio
import os
import sys
from datetime import datetime

from dotenv import load_dotenv
from sqlalchemy import select

load_dotenv()

from src.database.db_manager import init_db, get_session
from src.database.models import (
    AuditLog, OnboardingSession, Payment, RentSchedule, RentStatus,
    Room, Tenancy, Tenant, TenancyStatus,
)

STUCK_TENANCY_IDS = [1196, 1186, 1144, 1182, 1154]   # group A (active, session stuck)
ACTOR = "system-cleanup-2026-06-15"


async def main(write: bool):
    await init_db(os.environ["DATABASE_URL"])
    async with get_session() as s:
        # 1. Approve the 5 stuck sessions
        print("== 1. Stuck sessions -> approved ==")
        sess = (await s.execute(
            select(OnboardingSession).where(
                OnboardingSession.tenancy_id.in_(STUCK_TENANCY_IDS),
                OnboardingSession.status.in_(["pending_tenant", "pending_review"]),
            )
        )).scalars().all()
        for obs in sess:
            print(f"   session tcy={obs.tenancy_id} {obs.status} -> approved")
            if write:
                obs.status = "approved"
                if not obs.approved_at:
                    obs.approved_at = datetime.utcnow()
                obs.approved_by_phone = obs.approved_by_phone or "cleanup-0615"
                s.add(AuditLog(
                    changed_by=ACTOR, entity_type="tenancy", entity_id=obs.tenancy_id,
                    field="onboarding_session", old_value=obs.status, new_value="approved",
                    source="system", note="Closed stale booking session — tenant already checked in (active tenancy).",
                ))

        # 2. Void Santosh's old advance on cancelled tcy 1199
        print("\n== 2. Void Santosh old ₹1000 (pmt 21360) ==")
        p = await s.get(Payment, 21360)
        if p and not p.is_void:
            print(f"   pmt 21360 amt={p.amount} for={p.for_type} -> is_void=True")
            if write:
                p.is_void = True
                s.add(AuditLog(
                    changed_by=ACTOR, entity_type="payment", entity_id=21360,
                    entity_name="Santosh Chauhan", room_number="507",
                    field="is_void", old_value="False", new_value="True", source="system",
                    note="Re-booking on 15 Jun (new ₹1000 advance pmt 21402 on tcy 1207) supersedes the 13 Jun advance on cancelled tcy 1199.",
                ))
        else:
            print("   pmt 21360 already void or missing — skip")

        # 3. Cancel leftover no_show 1216 (SHASHANK), 1217 is live
        print("\n== 3. Cancel leftover no_show tcy 1216 (SHASHANK 618) ==")
        t1216 = await s.get(Tenancy, 1216)
        if t1216 and t1216.status == TenancyStatus.no_show:
            pmts = (await s.execute(select(Payment).where(Payment.tenancy_id == 1216, Payment.is_void == False))).scalars().all()
            print(f"   tcy 1216 status={t1216.status.value} non-void payments={len(pmts)}")
            if pmts:
                print("   !! has payments — NOT auto-cancelling; needs review")
            else:
                if write:
                    rs_rows = (await s.execute(select(RentSchedule).where(RentSchedule.tenancy_id == 1216))).scalars().all()
                    for rs in rs_rows:
                        rs.status = RentStatus.na
                    t1216.status = TenancyStatus.cancelled
                    s.add(AuditLog(
                        changed_by=ACTOR, entity_type="tenancy", entity_id=1216,
                        entity_name="SHASHANK B V", room_number="618",
                        field="status", old_value="no_show", new_value="cancelled", source="system",
                        note="Duplicate booking — tenant checked in on live tcy 1217; leftover no_show cancelled.",
                    ))
                print("   -> cancelled + RS rows set na")
        else:
            print("   tcy 1216 not no_show — skip")

        if not write:
            print("\n(read-only — pass --write to apply)")


if __name__ == "__main__":
    asyncio.run(main(write="--write" in sys.argv))
