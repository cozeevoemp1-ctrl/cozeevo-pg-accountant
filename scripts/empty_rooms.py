"""
Empty rooms + occupancy detail — transactional view.
Exports empty rooms to CSV for cross-verification.

Run: PYTHONPATH=. PYTHONUTF8=1 venv/Scripts/python scripts/empty_rooms.py
Output: empty_rooms_<date>.csv
"""
import asyncio, os, sys, csv
from datetime import date
from dotenv import load_dotenv
load_dotenv()

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from src.database.models import Room, Property, Tenancy, Tenant, TenancyStatus

DATABASE_URL = os.environ["DATABASE_URL"]
TODAY = date.today()
BEDS = {"single": 1, "double": 2, "triple": 3, "premium": 2}


async def main():
    engine = create_async_engine(DATABASE_URL, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as s:
        # Load all active rooms
        rooms_q = await s.execute(
            select(Room, Property.name.label("prop"))
            .join(Property, Room.property_id == Property.id)
            .where(Room.active == True)
            .order_by(Property.name, Room.floor, Room.room_number)
        )
        rooms_all = rooms_q.all()

        # Load ALL non-exited tenancies (active + no_show) to know which rooms are "taken"
        tenancies_q = await s.execute(
            select(Tenancy, Tenant.name.label("tname"))
            .join(Tenant, Tenancy.tenant_id == Tenant.id)
            .where(Tenancy.status.in_([TenancyStatus.active, TenancyStatus.no_show]))
        )
        all_tenancies = tenancies_q.all()

    await engine.dispose()

    # ── Build room occupancy map ──────────────────────────────────────────────
    # room_id → list of (tenancy, name, status)
    room_occupants = {}
    for t, tname in all_tenancies:
        room_occupants.setdefault(t.room_id, []).append((t, tname))

    active_only = {
        rid: [(t, n) for t, n in occ if t.status == TenancyStatus.active]
        for rid, occ in room_occupants.items()
    }
    noshow_only = {
        rid: [(t, n) for t, n in occ if t.status == TenancyStatus.no_show]
        for rid, occ in room_occupants.items()
    }

    # ── Categorise rooms ──────────────────────────────────────────────────────
    # A room is "empty" if it has NO active tenancy (no_show alone doesn't count as occupied)
    empty_rooms   = []   # no active tenancy (may have no_show)
    partial_rooms = []   # active tenants < max_occupancy (has space)
    full_rooms    = []   # active tenants >= max_occupancy

    for room, prop in rooms_all:
        if room.is_staff_room:
            continue   # skip staff rooms — they are never "empty" for tenants
        active_occ = active_only.get(room.id, [])
        noshow_occ = noshow_only.get(room.id, [])
        n_active = len(active_occ)
        max_occ  = room.max_occupancy or 1

        if n_active == 0:
            empty_rooms.append((room, prop, active_occ, noshow_occ))
        elif n_active < max_occ:
            partial_rooms.append((room, prop, active_occ, noshow_occ))
        else:
            full_rooms.append((room, prop, active_occ, noshow_occ))

    # ── Count no_show stats ───────────────────────────────────────────────────
    all_noshow = [(t, n) for t, n in all_tenancies if t.status == TenancyStatus.no_show]
    ns_in_empty  = sum(1 for r, _, _, ns in empty_rooms    if ns)
    ns_in_partial = sum(len(ns) for _, _, _, ns in partial_rooms)

    # ── Print summary ─────────────────────────────────────────────────────────
    W = 66
    print()
    print("=" * W)
    print(f"  ROOM OCCUPANCY  —  {TODAY}  (tenant rooms only, staff excluded)")
    print("=" * W)
    print(f"  {'Active tenants checked in:':<42} {sum(len(a) for _, _, a, _ in full_rooms + partial_rooms)}")
    print(f"  {'No-show bookings (room reserved, not arrived):':<42} {len(all_noshow)}")
    print()
    print(f"  {'Full rooms (no vacancy):':<42} {len(full_rooms)}")
    print(f"  {'Partial rooms (some beds free):':<42} {len(partial_rooms)}")
    print(f"  {'Empty rooms (no active tenant):':<42} {len(empty_rooms)}")
    print(f"    - of which have a no-show booking:          {ns_in_empty}")
    print()

    # No-show detail
    print("=" * W)
    print(f"  NO-SHOW BOOKINGS  ({len(all_noshow)} total — room reserved but never arrived)")
    print("=" * W)
    print(f"  {'#':<4} {'Name':<24} {'Room':<8} {'Prop':<14} {'Checkin':<12} {'Note'}")
    print(f"  {'-'*62}")
    for i, (t, tname) in enumerate(sorted(all_noshow, key=lambda x: x[0].checkin_date), 1):
        from src.database.models import Room as R2
        # find room number from the rooms_all list
        rinfo = next(((r, p) for r, p in rooms_all if r.id == t.room_id), (None, "?"))
        rnum = rinfo[0].room_number if rinfo[0] else "?"
        prop = rinfo[1][:13] if rinfo[1] else "?"
        note = "FUTURE" if t.checkin_date > TODAY else "PAST - never came"
        print(f"  {i:<4} {tname:<24} {rnum:<8} {prop:<14} {str(t.checkin_date):<12} {note}")

    # ── Empty rooms floor-wise ────────────────────────────────────────────────
    print()
    print("=" * W)
    print(f"  EMPTY ROOMS  ({len(empty_rooms)}) — no active tenant")
    print("=" * W)

    current_prop = None
    current_floor = None
    floor_label_map = {0: "Ground", 7: "7th Floor"}

    for room, prop, active_occ, noshow_occ in empty_rooms:
        floor_lbl = floor_label_map.get(room.floor, f"Floor {room.floor}")
        if prop != current_prop:
            current_prop = prop
            current_floor = None
            print(f"\n  ── {prop} ──")
        if room.floor != current_floor:
            current_floor = room.floor
            print(f"    [{floor_lbl}]")
        ns_flag = f"  *no-show: {noshow_occ[0][1]}" if noshow_occ else ""
        beds = BEDS.get(room.room_type.value, 1)
        charged = "" if room.is_charged else "  [FREE ROOM]"
        print(f"      {room.room_number:<8}  {room.room_type.value:<8}  {beds} bed(s){ns_flag}{charged}")

    # ── Partial rooms with available beds ────────────────────────────────────
    print()
    print("=" * W)
    print(f"  PARTIAL ROOMS ({len(partial_rooms)}) — has tenant(s) but beds still free")
    print("=" * W)
    print(f"  {'Room':<8} {'Type':<8} {'Max':<5} {'Occupied':<10} {'Free Beds':<10} {'Property':<14} {'Tenant(s)'}")
    print(f"  {'-'*70}")
    for room, prop, active_occ, noshow_occ in sorted(partial_rooms, key=lambda x: (x[1], x[0].floor, x[0].room_number)):
        n_active = len(active_occ)
        free = (room.max_occupancy or 1) - n_active
        tenant_names = ", ".join(n[:15] for _, n in active_occ)
        print(f"  {room.room_number:<8} {room.room_type.value:<8} {room.max_occupancy or 1:<5} {n_active:<10} {free:<10} {prop[:13]:<14} {tenant_names}")

    print()

    # ── Export empty rooms to CSV ─────────────────────────────────────────────
    csv_path = f"empty_rooms_{TODAY}.csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Property", "Floor", "Room Number", "Room Type", "Beds",
            "Is Charged", "No-Show Booking", "No-Show Tenant", "No-Show Checkin"
        ])
        for room, prop, _, noshow_occ in empty_rooms:
            floor_lbl = "G" if room.floor == 0 else str(room.floor)
            ns_tenant = noshow_occ[0][1] if noshow_occ else ""
            ns_checkin = str(noshow_occ[0][0].checkin_date) if noshow_occ else ""
            ns_flag = "YES" if noshow_occ else "NO"
            writer.writerow([
                prop, floor_lbl, room.room_number, room.room_type.value,
                BEDS.get(room.room_type.value, 1),
                "YES" if room.is_charged else "NO (FREE)",
                ns_flag, ns_tenant, ns_checkin
            ])

    print(f"  CSV exported: {csv_path}  ({len(empty_rooms)} rows)")
    print()


if __name__ == "__main__":
    asyncio.run(main())
