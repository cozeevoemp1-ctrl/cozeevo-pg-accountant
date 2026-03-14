"""
migrate_rooms.py — Rebuild room master data from canonical layout rules.

Rules:
  THOR  ground floor: G01–G10, G01 & G10 = single, rest = double/triple (as designed)
  HULK  ground floor: G11–G20, G11 & G20 = single, rest = double/triple (as designed)
  THOR  floors 1–6:   rooms X01–X12, X01 & X12 = single, X02–X11 = double
  HULK  floors 1–6:   rooms X13–X24, X13 & X24 = single, X14–X23 = double
  7th floor: 701 (THOR), 702 (HULK) — single, staff

Staff rooms:
  G05 THOR  — Ram (chef), Ram Pukar (helper), Vivek (helper)    [triple]
  G06 THOR  — 2 cleaners                                         [double]
  G12 HULK  — Arjun Family + 3 cleaners                         [triple]
  107 THOR  — Chandra                                            [double]
  108 THOR  — Lokesh (Receptionist)                              [double]
  114 HULK  — Naresh (Receptionist)                             [double]
  701 THOR  — Lakshmi (Owner)                                    [single]
  702 HULK  — Lakshmi (Owner)                                    [single]

Bed counting: single=1, double=2, triple=3  (premium is a billing/tenancy concept, not MDG)

Run: python -m src.database.migrate_rooms
"""
import asyncio, os
from dotenv import load_dotenv
load_dotenv()

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, text
from src.database.models import Room, Property, RoomType

DATABASE_URL = os.environ["DATABASE_URL"]

# ── Canonical room list ────────────────────────────────────────────────────────
# (room_number, floor, room_type, is_staff_room, notes)

THOR_ROOMS = [
    # Ground floor
    ("G01", 0, "single", False, None),
    ("G02", 0, "double", False, None),
    ("G03", 0, "double", False, None),
    ("G04", 0, "double", False, None),
    ("G05", 0, "triple", True,  "Staff: Ram (chef), Ram Pukar (helper), Vivek (helper)"),
    ("G06", 0, "double", True,  "Staff: 2 cleaners"),
    ("G07", 0, "triple", False, None),
    ("G08", 0, "triple", False, None),
    ("G09", 0, "triple", False, None),
    ("G10", 0, "single", False, None),
    # Floor 1  (101–112)
    ("101", 1, "single", False, None),
    ("102", 1, "double", False, None),
    ("103", 1, "double", False, None),
    ("104", 1, "double", False, None),
    ("105", 1, "double", False, None),
    ("106", 1, "double", False, None),
    ("107", 1, "double", True,  "Staff: Chandra"),
    ("108", 1, "double", True,  "Staff: Lokesh (Receptionist)"),
    ("109", 1, "double", False, None),
    ("110", 1, "double", False, None),
    ("111", 1, "double", False, None),
    ("112", 1, "single", False, None),
    # Floor 2  (201–212)
    ("201", 2, "single", False, None),
    ("202", 2, "double", False, None),
    ("203", 2, "double", False, None),
    ("204", 2, "double", False, None),
    ("205", 2, "double", False, None),
    ("206", 2, "double", False, None),
    ("207", 2, "double", False, None),
    ("208", 2, "double", False, None),
    ("209", 2, "double", False, None),
    ("210", 2, "double", False, None),
    ("211", 2, "double", False, None),
    ("212", 2, "single", False, None),
    # Floor 3  (301–312)
    ("301", 3, "single", False, None),
    ("302", 3, "double", False, None),
    ("303", 3, "double", False, None),
    ("304", 3, "double", False, None),
    ("305", 3, "double", False, None),
    ("306", 3, "double", False, None),
    ("307", 3, "double", False, None),
    ("308", 3, "double", False, None),
    ("309", 3, "double", False, None),
    ("310", 3, "double", False, None),
    ("311", 3, "double", False, None),
    ("312", 3, "single", False, None),
    # Floor 4  (401–412)
    ("401", 4, "single", False, None),
    ("402", 4, "double", False, None),
    ("403", 4, "double", False, None),
    ("404", 4, "double", False, None),
    ("405", 4, "double", False, None),
    ("406", 4, "double", False, None),
    ("407", 4, "double", False, None),
    ("408", 4, "double", False, None),
    ("409", 4, "double", False, None),
    ("410", 4, "double", False, None),
    ("411", 4, "double", False, None),
    ("412", 4, "single", False, None),
    # Floor 5  (501–512)
    ("501", 5, "single", False, None),
    ("502", 5, "double", False, None),
    ("503", 5, "double", False, None),
    ("504", 5, "double", False, None),
    ("505", 5, "double", False, None),
    ("506", 5, "double", False, None),
    ("507", 5, "double", False, None),
    ("508", 5, "double", False, None),
    ("509", 5, "double", False, None),
    ("510", 5, "double", False, None),
    ("511", 5, "double", False, None),
    ("512", 5, "single", False, None),
    # Floor 6  (601–612)
    ("601", 6, "single", False, None),
    ("602", 6, "double", False, None),
    ("603", 6, "double", False, None),
    ("604", 6, "double", False, None),
    ("605", 6, "double", False, None),
    ("606", 6, "double", False, None),
    ("607", 6, "double", False, None),
    ("608", 6, "double", False, None),
    ("609", 6, "double", False, None),
    ("610", 6, "double", False, None),
    ("611", 6, "double", False, None),
    ("612", 6, "single", False, None),
    # Floor 7  (staff)
    ("701", 7, "single", True,  "Staff: Lakshmi (Owner)"),
]

HULK_ROOMS = [
    # Ground floor
    ("G11", 0, "single", False, None),
    ("G12", 0, "triple", True,  "Staff: Arjun Family, 3 cleaners"),
    ("G13", 0, "double", False, None),
    ("G14", 0, "triple", False, None),
    ("G15", 0, "double", False, None),
    ("G16", 0, "double", False, None),
    ("G17", 0, "double", False, None),
    ("G18", 0, "double", False, None),
    ("G19", 0, "double", False, None),
    ("G20", 0, "single", False, None),
    # Floor 1  (113–124)
    ("113", 1, "single", False, None),
    ("114", 1, "double", True,  "Staff: Naresh (Receptionist)"),
    ("115", 1, "double", False, None),
    ("116", 1, "double", False, None),
    ("117", 1, "double", False, None),
    ("118", 1, "double", False, None),
    ("119", 1, "double", False, None),
    ("120", 1, "double", False, None),
    ("121", 1, "double", False, None),
    ("122", 1, "double", False, None),
    ("123", 1, "double", False, None),
    ("124", 1, "single", False, None),
    # Floor 2  (213–224)
    ("213", 2, "single", False, None),
    ("214", 2, "double", False, None),
    ("215", 2, "double", False, None),
    ("216", 2, "double", False, None),
    ("217", 2, "double", False, None),
    ("218", 2, "double", False, None),
    ("219", 2, "double", False, None),
    ("220", 2, "double", False, None),
    ("221", 2, "double", False, None),
    ("222", 2, "double", False, None),
    ("223", 2, "double", False, None),
    ("224", 2, "single", False, None),
    # Floor 3  (313–324)
    ("313", 3, "single", False, None),
    ("314", 3, "double", False, None),
    ("315", 3, "double", False, None),
    ("316", 3, "double", False, None),
    ("317", 3, "double", False, None),
    ("318", 3, "double", False, None),
    ("319", 3, "double", False, None),
    ("320", 3, "double", False, None),
    ("321", 3, "double", False, None),
    ("322", 3, "double", False, None),
    ("323", 3, "double", False, None),
    ("324", 3, "single", False, None),
    # Floor 4  (413–424)
    ("413", 4, "single", False, None),
    ("414", 4, "double", False, None),
    ("415", 4, "double", False, None),
    ("416", 4, "double", False, None),
    ("417", 4, "double", False, None),
    ("418", 4, "double", False, None),
    ("419", 4, "double", False, None),
    ("420", 4, "double", False, None),
    ("421", 4, "double", False, None),
    ("422", 4, "double", False, None),
    ("423", 4, "double", False, None),
    ("424", 4, "single", False, None),
    # Floor 5  (513–524)
    ("513", 5, "single", False, None),
    ("514", 5, "double", False, None),
    ("515", 5, "double", False, None),
    ("516", 5, "double", False, None),
    ("517", 5, "double", False, None),
    ("518", 5, "double", False, None),
    ("519", 5, "double", False, None),
    ("520", 5, "double", False, None),
    ("521", 5, "double", False, None),
    ("522", 5, "double", False, None),
    ("523", 5, "double", False, None),
    ("524", 5, "single", False, None),
    # Floor 6  (613–624)
    ("613", 6, "single", False, None),
    ("614", 6, "double", False, None),
    ("615", 6, "double", False, None),
    ("616", 6, "double", False, None),
    ("617", 6, "double", False, None),
    ("618", 6, "double", False, None),
    ("619", 6, "double", False, None),
    ("620", 6, "double", False, None),
    ("621", 6, "double", False, None),
    ("622", 6, "double", False, None),
    ("623", 6, "double", False, None),
    ("624", 6, "single", False, None),
    # Floor 7  (staff)
    ("702", 7, "single", True,  "Staff: Lakshmi (Owner)"),
]

BEDS = {"single": 1, "double": 2, "triple": 3}

assert len(THOR_ROOMS) == 83, f"THOR count wrong: {len(THOR_ROOMS)}"
assert len(HULK_ROOMS) == 83, f"HULK count wrong: {len(HULK_ROOMS)}"


async def migrate():
    engine = create_async_engine(DATABASE_URL, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as s:
        # Get property IDs
        props = (await s.execute(select(Property))).scalars().all()
        prop_id = {p.name: p.id for p in props}

        thor_id = prop_id.get("Cozeevo THOR")
        hulk_id = prop_id.get("Cozeevo HULK")
        if not thor_id or not hulk_id:
            print("ERROR: Properties not found. Run seed.py first.")
            return

        # Build canonical set: {(property_id, room_number)}
        canonical = {}
        for rnum, floor, rtype, is_staff, notes in THOR_ROOMS:
            canonical[(thor_id, rnum)] = (floor, rtype, is_staff, notes)
        for rnum, floor, rtype, is_staff, notes in HULK_ROOMS:
            canonical[(hulk_id, rnum)] = (floor, rtype, is_staff, notes)

        # Fetch all existing rooms
        existing = (await s.execute(select(Room))).scalars().all()
        existing_map = {(r.property_id, r.room_number): r for r in existing}

        inserted = updated = deactivated = 0

        # 1. Upsert canonical rooms
        for (prop_id_key, rnum), (floor, rtype, is_staff, notes) in canonical.items():
            key = (prop_id_key, rnum)
            rt_enum = RoomType(rtype)
            max_occ = {"single": 1, "double": 2, "triple": 3}[rtype]

            if key in existing_map:
                room = existing_map[key]
                changed = False
                if room.floor != floor:
                    room.floor = floor; changed = True
                if room.room_type != rt_enum:
                    room.room_type = rt_enum; changed = True
                if room.max_occupancy != max_occ:
                    room.max_occupancy = max_occ; changed = True
                if room.is_staff_room != is_staff:
                    room.is_staff_room = is_staff; changed = True
                if notes and room.notes != notes:
                    room.notes = notes; changed = True
                if not room.active:
                    room.active = True; changed = True
                if changed:
                    updated += 1
            else:
                s.add(Room(
                    property_id=prop_id_key,
                    room_number=rnum,
                    floor=floor,
                    room_type=rt_enum,
                    max_occupancy=max_occ,
                    is_staff_room=is_staff,
                    is_charged=True,   # owner marks free rooms via WhatsApp
                    active=True,
                    notes=notes,
                ))
                inserted += 1

        # 2. Deactivate rooms not in canonical list
        for key, room in existing_map.items():
            if key not in canonical and room.active:
                room.active = False
                room.notes = (room.notes or "") + " [DEACTIVATED: not in canonical room list]"
                deactivated += 1

        await s.commit()

    await engine.dispose()

    print(f"\n  Inserted:    {inserted} new rooms")
    print(f"  Updated:     {updated} existing rooms")
    print(f"  Deactivated: {deactivated} non-canonical rooms")

    # ── Print final MDG table ─────────────────────────────────────────────────
    engine2 = create_async_engine(DATABASE_URL, echo=False)
    Session2 = sessionmaker(engine2, class_=AsyncSession, expire_on_commit=False)

    async with Session2() as s2:
        result = await s2.execute(
            select(Room, Property.name.label("prop"))
            .join(Property, Room.property_id == Property.id)
            .where(Room.active == True)
            .order_by(Property.name.desc(), Room.floor, Room.room_number)
        )
        rows = result.all()

    await engine2.dispose()

    print()
    print("=" * 90)
    print("  ROOM MASTER DATA (MDG) — post-migration")
    print("  Bed types: single=1 bed, double=2 beds, triple=3 beds")
    print("  NOTE: 'premium' is a billing/tenancy concept, not a room design — not shown here")
    print("=" * 90)
    print(f"{'#':<4} {'Property':<14} {'Fl':<4} {'Room':<7} {'Type':<8} {'Beds':<6} {'Staff':<7} {'Notes'}")
    print("-" * 90)

    type_totals = {}
    prop_totals = {}
    grand_rooms = grand_beds = staff_rooms = staff_beds = 0

    for i, (room, prop) in enumerate(rows, 1):
        rtype = room.room_type.value
        beds = BEDS.get(rtype, 1)
        fl = "G" if room.floor == 0 else str(room.floor)
        staff = "STAFF" if room.is_staff_room else ""
        notes = (room.notes or "")[:40]

        print(f"{i:<4} {prop:<14} {fl:<4} {room.room_number:<7} {rtype:<8} {beds:<6} {staff:<7} {notes}")

        type_totals.setdefault(rtype, [0, 0])
        type_totals[rtype][0] += 1
        type_totals[rtype][1] += beds
        prop_totals.setdefault(prop, [0, 0])
        prop_totals[prop][0] += 1
        prop_totals[prop][1] += beds
        grand_rooms += 1
        grand_beds += beds
        if room.is_staff_room:
            staff_rooms += 1
            staff_beds += beds

    print()
    print("=" * 60)
    print("  SUMMARY BY PROPERTY")
    print("=" * 60)
    print(f"  {'Property':<20} {'Rooms':<10} {'Total Beds'}")
    print(f"  {'-'*40}")
    for p, (r, b) in sorted(prop_totals.items()):
        print(f"  {p:<20} {r:<10} {b}")

    print()
    print("=" * 60)
    print("  SUMMARY BY ROOM TYPE  (physical design)")
    print("=" * 60)
    print(f"  {'Type':<10} {'Rooms':<10} {'Beds'}")
    print(f"  {'-'*30}")
    for rt in ["single", "double", "triple"]:
        if rt in type_totals:
            r, b = type_totals[rt]
            print(f"  {rt:<10} {r:<10} {b}")

    print()
    print("=" * 60)
    print("  BED TOTALS  (all rooms incl. staff — staff cost money too)")
    print("=" * 60)
    tenant_rooms = grand_rooms - staff_rooms
    tenant_beds  = grand_beds  - staff_beds
    print(f"  Total rooms:            {grand_rooms}  (target: 166)")
    print(f"  Total beds:             {grand_beds}")
    print(f"    Tenant rooms/beds:    {tenant_rooms} rooms / {tenant_beds} beds")
    print(f"    Staff rooms/beds:     {staff_rooms} rooms / {staff_beds} beds")
    print(f"  Charged rooms:          164 (2 uncharged — configure per owner)")
    print(f"  Fixed room rent:        Rs 13,000 x 164 = Rs {13000*164:,}/month")
    print("=" * 60)
    print()


if __name__ == "__main__":
    asyncio.run(migrate())
