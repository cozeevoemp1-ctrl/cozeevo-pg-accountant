"""
Room Master Data — static room properties only (NO transaction/occupancy data).
Run: python scripts/show_rooms.py
"""
import asyncio, os, sys
from dotenv import load_dotenv
load_dotenv()

# Force UTF-8 output on Windows
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from src.database.models import Room, Property

DATABASE_URL = os.environ["DATABASE_URL"]

# Bed capacity per room type (physical beds, regardless of who books)
BEDS = {"single": 1, "double": 2, "triple": 3, "premium": 2}

async def main():
    engine = create_async_engine(DATABASE_URL, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as s:
        result = await s.execute(
            select(Room, Property.name.label("prop_name"))
            .join(Property, Room.property_id == Property.id)
            .order_by(Property.name, Room.floor, Room.room_number)
        )
        rows = result.all()

    await engine.dispose()

    # ── Print MDG table ───────────────────────────────────────────────────────
    sep = "-" * 86
    header = (
        f"{'#':<4} {'Property':<14} {'Floor':<7} {'Room No':<10} "
        f"{'Type':<10} {'Beds':<6} {'AC':<4} {'Bath':<6} {'Staff Room':<12} {'Active':<7} {'Notes'}"
    )

    print()
    print("=" * 86)
    print("  ROOM MASTER DATA (MDG)  —  static properties only, no transaction data")
    print("=" * 86)
    print(header)
    print(sep)

    # Track summary
    total_beds = 0
    staff_beds = 0
    type_counts = {}   # {type: {rooms:0, beds:0, staff_rooms:0, staff_beds:0}}
    prop_counts = {}   # {prop_name: {rooms:0, beds:0}}

    for i, (room, prop) in enumerate(rows, 1):
        rtype = room.room_type.value
        beds = BEDS.get(rtype, 1)
        ac   = "Y" if room.has_ac else "N"
        bath = "Y" if room.has_attached_bath else "N"
        staff = "STAFF" if room.is_staff_room else ""
        active = "Y" if room.active else "N"
        floor_label = f"G" if room.floor == 0 else str(room.floor)
        notes = (room.notes or "")[:30]

        print(
            f"{i:<4} {prop:<14} {floor_label:<7} {room.room_number:<10} "
            f"{rtype:<10} {beds:<6} {ac:<4} {bath:<6} {staff:<12} {active:<7} {notes}"
        )

        # Aggregate
        if rtype not in type_counts:
            type_counts[rtype] = {"rooms": 0, "beds": 0, "staff_rooms": 0, "staff_beds": 0}
        if prop not in prop_counts:
            prop_counts[prop] = {"rooms": 0, "beds": 0}

        type_counts[rtype]["rooms"] += 1
        type_counts[rtype]["beds"] += beds
        prop_counts[prop]["rooms"] += 1
        prop_counts[prop]["beds"] += beds

        if room.is_staff_room:
            staff_beds += beds
            type_counts[rtype]["staff_rooms"] += 1
            type_counts[rtype]["staff_beds"] += beds
        else:
            total_beds += beds

        total_beds_all = total_beds + staff_beds  # recalc below

    # Final totals
    all_beds = sum(v["beds"] for v in type_counts.values())
    all_rooms = sum(v["rooms"] for v in type_counts.values())

    # ── By property ───────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("  SUMMARY BY PROPERTY")
    print("=" * 60)
    print(f"  {'Property':<20} {'Rooms':<10} {'Total Beds'}")
    print(f"  {'-'*45}")
    for prop, d in sorted(prop_counts.items()):
        print(f"  {prop:<20} {d['rooms']:<10} {d['beds']}")

    # ── By bed type ───────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("  SUMMARY BY BED TYPE  (beds = physical sleeping spots)")
    print("=" * 60)
    print(f"  {'Type':<12} {'Rooms':<8} {'Beds':<8} {'Staff Rooms':<14} {'Staff Beds'}")
    print(f"  {'-'*55}")
    for rtype in ["single", "double", "triple", "premium"]:
        if rtype in type_counts:
            d = type_counts[rtype]
            print(f"  {rtype:<12} {d['rooms']:<8} {d['beds']:<8} {d['staff_rooms']:<14} {d['staff_beds']}")

    # ── Grand total ───────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("  BED COUNT TOTAL  (double=2, triple=3, single=1, premium=2)")
    print("=" * 60)
    print(f"  Total rooms in DB:         {all_rooms}")
    print(f"  Total beds in DB:          {all_beds}")
    print(f"    - Tenant rooms + beds:   {all_rooms - sum(v['staff_rooms'] for v in type_counts.values())} rooms  /  {all_beds - sum(v['staff_beds'] for v in type_counts.values())} beds")
    print(f"    - Staff rooms + beds:    {sum(v['staff_rooms'] for v in type_counts.values())} rooms  /  {sum(v['staff_beds'] for v in type_counts.values())} beds")
    print()
    print("  NOTE: User said 166 rooms (83 THOR + 83 HULK), 164 charged.")
    print(f"  DB currently has {all_rooms} rooms — please verify and correct if needed.")
    print("=" * 60)
    print()

if __name__ == "__main__":
    asyncio.run(main())
