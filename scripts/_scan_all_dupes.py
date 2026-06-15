"""Read-only: broad duplicate sweep across the live data.

1) Same PHONE with >1 live (active/no_show) tenancy — across ANY room.
2) Duplicate TENANT records — same normalized phone, multiple tenant rows, where
   more than one has a live tenancy.
3) Duplicate PAYMENTS — same tenancy + same amount + same for_type on the same day
   (non-void) — likely double-entered.
"""
import asyncio
import os
import re
from collections import defaultdict

from dotenv import load_dotenv
from sqlalchemy import select

load_dotenv()

from src.database.db_manager import init_db, get_session
from src.database.models import Payment, Room, Tenancy, Tenant, TenancyStatus

LIVE = [TenancyStatus.active, TenancyStatus.no_show]


def l10(p):
    d = re.sub(r"\D", "", p or "")
    return d[-10:] if len(d) >= 10 else d


async def main():
    await init_db(os.environ["DATABASE_URL"])
    async with get_session() as s:
        rooms = {r.id: r.room_number for r in (await s.execute(select(Room))).scalars()}
        rows = (await s.execute(
            select(Tenancy, Tenant).join(Tenant, Tenant.id == Tenancy.tenant_id)
            .where(Tenancy.status.in_(LIVE))
        )).all()

        # 1) same phone, >1 live tenancy
        by_phone = defaultdict(list)
        for tc, t in rows:
            by_phone[l10(t.phone)].append((tc.id, tc.status.value, rooms.get(tc.room_id, "?"), t.name, t.id))
        print("1) Same PHONE with >1 live tenancy:")
        n = 0
        for ph, lst in by_phone.items():
            if ph and len(lst) > 1:
                n += 1
                print(f"   phone …{ph[-4:]}: {[(i,st,rm) for i,st,rm,_,_ in lst]}  names={set(x[3] for x in lst)} tenant_ids={set(x[4] for x in lst)}")
        if not n:
            print("   none")

        # 2) duplicate tenant records (same phone, >1 tenant_id with a live tenancy)
        print("\n2) Same phone spread across >1 TENANT record (live):")
        m = 0
        for ph, lst in by_phone.items():
            tids = set(x[4] for x in lst)
            if ph and len(tids) > 1:
                m += 1
                print(f"   phone …{ph[-4:]} tenant_ids={tids} names={set(x[3] for x in lst)}")
        if not m:
            print("   none")

        # 3) duplicate payments (same tenancy+amount+for_type+date, non-void)
        print("\n3) Duplicate non-void payments (same tenancy+amount+type+date):")
        pmts = (await s.execute(select(Payment).where(Payment.is_void == False))).scalars().all()
        seen = defaultdict(list)
        for p in pmts:
            key = (p.tenancy_id, float(p.amount or 0), p.for_type.value if p.for_type else None, str(p.payment_date))
            seen[key].append(p.id)
        k = 0
        for key, ids in seen.items():
            if len(ids) > 1 and key[0] is not None:
                k += 1
                print(f"   tcy={key[0]} amt={key[1]} type={key[2]} date={key[3]} -> pmt ids {ids}")
        if not k:
            print("   none")


if __name__ == "__main__":
    asyncio.run(main())
