"""
Occupancy snapshot — transactional data (tenancies), NOT MDG.
Shows beds/rooms currently occupied and booked-but-not-checked-in.

Also marks G05 and G06 (THOR) as is_charged=False (free rooms from building owner).

Run: PYTHONPATH=. PYTHONUTF8=1 venv/Scripts/python scripts/occupancy_today.py
"""
import asyncio, os, sys
from datetime import date
from dotenv import load_dotenv
load_dotenv()

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, update, func
from src.database.models import Room, Property, Tenancy, Tenant, TenancyStatus, RoomType

DATABASE_URL = os.environ["DATABASE_URL"]

BEDS = {"single": 1, "double": 2, "triple": 3, "premium": 2}
TODAY = date.today()


async def main():
    engine = create_async_engine(DATABASE_URL, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as s:
        # ── Step 1: Mark G05 and G06 (THOR) as is_charged=False ──────────────
        thor = (await s.execute(select(Property).where(Property.name.ilike("%THOR%")))).scalars().first()
        if thor:
            result = await s.execute(
                update(Room)
                .where(Room.property_id == thor.id, Room.room_number.in_(["G05", "G06"]))
                .values(is_charged=False)
                .returning(Room.room_number)
            )
            freed = [r[0] for r in result.fetchall()]
            if freed:
                print(f"  [UPDATED] Marked as is_charged=False: {freed} (THOR free rooms)")
            else:
                print(f"  [OK] THOR G05, G06 already is_charged=False (or not found)")
            await s.commit()

        # ── Step 2: Load all canonical rooms (MDG) ───────────────────────────
        rooms_q = await s.execute(
            select(Room, Property.name.label("prop"))
            .join(Property, Room.property_id == Property.id)
            .where(Room.active == True)
        )
        rooms_all = rooms_q.all()

        room_by_id    = {r.id: r       for r, _ in rooms_all}
        room_prop     = {r.id: prop    for r, prop in rooms_all}
        charged_rooms = {r.id for r, _ in rooms_all if r.is_charged and not r.is_staff_room}
        all_room_ids  = {r.id for r, _ in rooms_all}

        # ── Step 3: Active tenancies ──────────────────────────────────────────
        tenancies_q = await s.execute(
            select(Tenancy, Tenant.name.label("tname"))
            .join(Tenant, Tenancy.tenant_id == Tenant.id)
            .where(Tenancy.status == TenancyStatus.active)
        )
        active_tenancies = tenancies_q.all()

    await engine.dispose()

    # ── Categorise ────────────────────────────────────────────────────────────
    checked_in     = []   # checkin_date <= today
    future_booking = []   # checkin_date > today

    for t, tname in active_tenancies:
        if t.checkin_date <= TODAY:
            checked_in.append((t, tname))
        else:
            future_booking.append((t, tname))

    def bed_count(t):
        """1 bed per tenant, except premium = 2 beds (1 person occupies full double)."""
        room = room_by_id.get(t.room_id)
        if not room:
            return 1
        return 2 if room.room_type.value == "premium" else 1

    # Beds occupied (checked in today)
    beds_in    = sum(bed_count(t) for t, _ in checked_in)
    beds_future = sum(bed_count(t) for t, _ in future_booking)

    # Rooms occupied (unique room IDs)
    rooms_in    = len({t.room_id for t, _ in checked_in})
    rooms_future = len({t.room_id for t, _ in future_booking})

    # Total charged beds available (exclude staff rooms + free rooms)
    charged_beds = sum(
        BEDS.get(room_by_id[rid].room_type.value, 1)
        for rid in charged_rooms
        if rid in room_by_id
    )
    charged_rooms_count = len(charged_rooms)

    # ── Print ─────────────────────────────────────────────────────────────────
    W = 62
    print()
    print("=" * W)
    print(f"  OCCUPANCY SNAPSHOT  —  as of {TODAY}")
    print("=" * W)
    print(f"  {'Metric':<38} {'Value':>10}")
    print(f"  {'-'*50}")
    print(f"  {'Charged rooms (excl. staff + free):':<38} {charged_rooms_count:>10}")
    print(f"  {'Charged beds  (excl. staff + free):':<38} {charged_beds:>10}")
    print()
    print(f"  {'[CHECKED IN]  Tenants in today:':<38} {len(checked_in):>10}")
    print(f"  {'[CHECKED IN]  Beds occupied:':<38} {beds_in:>10}")
    print(f"  {'[CHECKED IN]  Rooms occupied:':<38} {rooms_in:>10}")
    print(f"  {'[CHECKED IN]  Beds EMPTY (charged):':<38} {charged_beds - beds_in:>10}")
    print()
    print(f"  {'[FUTURE]  Booked, not checked in yet:':<38} {len(future_booking):>10}")
    print(f"  {'[FUTURE]  Beds reserved (not arrived):':<38} {beds_future:>10}")
    print(f"  {'[FUTURE]  Rooms reserved:':<38} {rooms_future:>10}")

    # Occupancy %
    if charged_beds > 0:
        pct = beds_in * 100 / charged_beds
        print()
        print(f"  {'Occupancy %  (checked-in / charged):':<38} {pct:>9.1f}%")

    # ── Breakdown by property ─────────────────────────────────────────────────
    print()
    print("=" * W)
    print("  BREAKDOWN BY PROPERTY")
    print("=" * W)
    for prop_name in ["Cozeevo THOR", "Cozeevo HULK"]:
        prop_rooms_charged = {
            rid for rid in charged_rooms
            if room_prop.get(rid) == prop_name
        }
        prop_beds = sum(BEDS.get(room_by_id[rid].room_type.value, 1) for rid in prop_rooms_charged if rid in room_by_id)
        prop_in = [(t, n) for t, n in checked_in if room_prop.get(t.room_id) == prop_name]
        prop_fut = [(t, n) for t, n in future_booking if room_prop.get(t.room_id) == prop_name]
        prop_beds_in  = sum(bed_count(t) for t, _ in prop_in)
        prop_rooms_in = len({t.room_id for t, _ in prop_in})
        pct2 = prop_beds_in * 100 / prop_beds if prop_beds else 0
        print(f"  {prop_name}")
        print(f"    Charged beds:   {prop_beds}")
        print(f"    Checked-in:     {len(prop_in)} tenants / {prop_beds_in} beds / {prop_rooms_in} rooms")
        print(f"    Future booking: {len(prop_fut)} tenants")
        print(f"    Occupancy:      {pct2:.1f}%")
        print()

    # ── Future bookings detail ────────────────────────────────────────────────
    if future_booking:
        print("=" * W)
        print("  BOOKED — NOT YET CHECKED IN")
        print("=" * W)
        print(f"  {'#':<4} {'Name':<22} {'Room':<10} {'Checkin':<12} {'Prop'}")
        print(f"  {'-'*55}")
        for i, (t, tname) in enumerate(sorted(future_booking, key=lambda x: x[0].checkin_date), 1):
            room = room_by_id.get(t.room_id)
            rnum = room.room_number if room else "?"
            prop = room_prop.get(t.room_id, "?")[:12]
            print(f"  {i:<4} {tname:<22} {rnum:<10} {str(t.checkin_date):<12} {prop}")
        print()

    print("=" * W)
    print()


if __name__ == "__main__":
    asyncio.run(main())
