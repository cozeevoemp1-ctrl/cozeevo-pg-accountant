"""
scripts/seed_demo_data.py
==========================
Populates a FRESH demo database with realistic, fully-fictional data so every
screen of the PWA looks alive (occupancy, dues, payments, notices, checkouts,
pending bookings, complaints, finance/P&L, unit economics, investment section).

SAFETY
------
This script REFUSES to run unless:
  1. Environment variable DEMO_MODE is truthy ("1", "true", "yes"), AND
  2. The `--confirm` CLI flag is passed, AND
  3. The `tenants` table in the target DB has ZERO rows.

It prints the DATABASE_URL host before doing anything else so you can verify
you are not pointed at production.

ROOMS
-----
`migrate_all.py` does NOT create rooms/properties on a fresh DB (its own
`run_seed()` explicitly skips them — "use excel_import.py for master data").
So this script seeds rooms itself when the `rooms` table is empty, using
ROOMS_DATA below — a static literal embedded from a one-time, read-only
dump of the real room layout (room_number/floor/room_type/max_occupancy/
is_staff_room — building structure, not personal data; the two buildings
are named generically "Building A"/"Building B", never the real brand).
If rooms already exist in the target DB, seeding is skipped and whatever
is there is used as-is.

AUTHORIZED USERS
-----------------
`migrate_all.py --seed` / `src/database/seed.py` insert real people
(real admin/owner phone numbers and names) into `authorized_users` and
real property names into `properties`. If those already ran against this
DB (e.g. a demo VPS setup script that runs migrate_all first), this script
scrubs them: deletes/renames any row matching known real people or brand
names and replaces them with generic demo rows ("Demo Admin", "Demo
Manager") and generic property names ("Building A"/"Building B").

Usage:
    DEMO_MODE=1 venv/Scripts/python scripts/seed_demo_data.py --confirm

Never run this against a real database. It is a one-shot fresh-DB seeder,
not idempotent (no upsert/on-conflict handling for tenants/tenancies).
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import random
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import dotenv_values
env = dotenv_values(".env")
os.environ.update({k: v for k, v in env.items() if v is not None and k not in os.environ})

from sqlalchemy import select, func

from src.database.db_manager import init_engine, get_session
from src.database.models import (
    Property, Room, RoomType, Tenant, Tenancy, RentSchedule, Payment, CheckoutRecord,
    OnboardingSession, Complaint, OperationalLog,
    BankUpload, BankTransaction, PnlMonthlyAdjustment, InvestmentExpense,
    StayType, SharingType, TenancyStatus, RentStatus, PaymentMode, PaymentFor,
    ComplaintCategory, ComplaintStatus, AuthorizedUser, UserRole,
)
from src.services.rent_schedule import first_month_rent_due

RNG = random.Random(42)

# ══════════════════════════════════════════════════════════════════════════
# ROOMS_DATA — static literal embedded from a one-time READ-ONLY dump of the
# real room layout (SELECT room_number, floor, room_type, max_occupancy,
# is_staff_room, property linkage). Building structure only — no personal
# data, no real names. Buildings renamed "Building A" / "Building B".
# Tuple shape: (building, room_number, floor, room_type, max_occupancy, is_staff_room)
# Dumped 2026-07-20: 166 rooms total (84 Building A, 82 Building B).
# ══════════════════════════════════════════════════════════════════════════

ROOMS_DATA: list[tuple[str, str, int, str, int, bool]] = [
    ('A', 'G01', 0, 'single', 1, False),
    ('A', 'G02', 0, 'double', 2, False),
    ('A', 'G03', 0, 'double', 2, False),
    ('A', 'G04', 0, 'double', 2, False),
    ('A', 'G05', 0, 'triple', 3, True),
    ('A', 'G06', 0, 'double', 2, True),
    ('A', 'G07', 0, 'triple', 3, False),
    ('A', 'G08', 0, 'triple', 3, False),
    ('A', 'G09', 0, 'triple', 3, False),
    ('A', 'G10', 0, 'single', 1, False),
    ('A', '101', 1, 'single', 1, False),
    ('A', '102', 1, 'double', 2, False),
    ('A', '103', 1, 'double', 2, False),
    ('A', '104', 1, 'double', 2, False),
    ('A', '105', 1, 'double', 2, False),
    ('A', '106', 1, 'double', 2, False),
    ('A', '107', 1, 'double', 2, False),
    ('A', '108', 1, 'double', 2, False),
    ('A', '109', 1, 'double', 2, False),
    ('A', '110', 1, 'double', 2, False),
    ('A', '111', 1, 'double', 2, False),
    ('A', '112', 1, 'single', 1, False),
    ('A', '201', 2, 'single', 1, False),
    ('A', '202', 2, 'double', 2, False),
    ('A', '203', 2, 'double', 2, False),
    ('A', '204', 2, 'double', 2, False),
    ('A', '205', 2, 'double', 2, False),
    ('A', '206', 2, 'double', 2, False),
    ('A', '207', 2, 'double', 2, False),
    ('A', '208', 2, 'double', 2, False),
    ('A', '209', 2, 'double', 2, False),
    ('A', '210', 2, 'double', 2, False),
    ('A', '211', 2, 'double', 2, False),
    ('A', '212', 2, 'single', 1, False),
    ('A', '301', 3, 'single', 1, False),
    ('A', '302', 3, 'double', 2, False),
    ('A', '303', 3, 'double', 2, False),
    ('A', '304', 3, 'double', 2, False),
    ('A', '305', 3, 'double', 2, False),
    ('A', '306', 3, 'double', 2, False),
    ('A', '307', 3, 'double', 2, False),
    ('A', '308', 3, 'double', 2, False),
    ('A', '309', 3, 'double', 2, False),
    ('A', '310', 3, 'double', 2, False),
    ('A', '311', 3, 'double', 2, False),
    ('A', '312', 3, 'single', 1, False),
    ('A', '401', 4, 'single', 1, False),
    ('A', '402', 4, 'double', 2, False),
    ('A', '403', 4, 'double', 2, False),
    ('A', '404', 4, 'double', 2, False),
    ('A', '405', 4, 'double', 2, False),
    ('A', '406', 4, 'double', 2, False),
    ('A', '407', 4, 'double', 2, False),
    ('A', '408', 4, 'double', 2, False),
    ('A', '409', 4, 'double', 2, False),
    ('A', '410', 4, 'double', 2, False),
    ('A', '411', 4, 'double', 2, False),
    ('A', '412', 4, 'single', 1, False),
    ('A', '501', 5, 'single', 1, False),
    ('A', '502', 5, 'double', 2, False),
    ('A', '503', 5, 'double', 2, False),
    ('A', '504', 5, 'double', 2, False),
    ('A', '505', 5, 'double', 2, False),
    ('A', '506', 5, 'double', 2, False),
    ('A', '507', 5, 'double', 2, False),
    ('A', '508', 5, 'double', 2, False),
    ('A', '509', 5, 'double', 2, False),
    ('A', '510', 5, 'double', 2, False),
    ('A', '511', 5, 'double', 2, False),
    ('A', '512', 5, 'single', 1, False),
    ('A', '601', 6, 'single', 1, False),
    ('A', '602', 6, 'double', 2, False),
    ('A', '603', 6, 'double', 2, False),
    ('A', '604', 6, 'double', 2, False),
    ('A', '605', 6, 'double', 2, False),
    ('A', '606', 6, 'double', 2, False),
    ('A', '607', 6, 'double', 2, False),
    ('A', '608', 6, 'double', 2, False),
    ('A', '609', 6, 'double', 2, False),
    ('A', '610', 6, 'double', 2, False),
    ('A', '611', 6, 'double', 2, False),
    ('A', '612', 6, 'single', 1, False),
    ('A', '701', 7, 'single', 1, True),
    ('A', '702', 7, 'single', 1, True),
    ('B', 'G11', 0, 'single', 1, False),
    ('B', 'G12', 0, 'triple', 3, True),
    ('B', 'G13', 0, 'triple', 3, False),
    ('B', 'G14', 0, 'triple', 3, False),
    ('B', 'G15', 0, 'double', 2, False),
    ('B', 'G16', 0, 'single', 1, False),
    ('B', 'G17', 0, 'double', 2, False),
    ('B', 'G18', 0, 'double', 2, False),
    ('B', 'G19', 0, 'double', 2, False),
    ('B', 'G20', 0, 'single', 1, False),
    ('B', '113', 1, 'single', 1, False),
    ('B', '114', 1, 'double', 2, False),
    ('B', '115', 1, 'double', 2, False),
    ('B', '116', 1, 'double', 2, False),
    ('B', '117', 1, 'double', 2, False),
    ('B', '118', 1, 'double', 2, False),
    ('B', '119', 1, 'double', 2, False),
    ('B', '120', 1, 'double', 2, False),
    ('B', '121', 1, 'double', 2, False),
    ('B', '122', 1, 'double', 2, False),
    ('B', '123', 1, 'double', 2, False),
    ('B', '124', 1, 'single', 1, False),
    ('B', '213', 2, 'single', 1, False),
    ('B', '214', 2, 'double', 2, False),
    ('B', '215', 2, 'double', 2, False),
    ('B', '216', 2, 'double', 2, False),
    ('B', '217', 2, 'double', 2, False),
    ('B', '218', 2, 'double', 2, False),
    ('B', '219', 2, 'double', 2, False),
    ('B', '220', 2, 'double', 2, False),
    ('B', '221', 2, 'double', 2, False),
    ('B', '222', 2, 'double', 2, False),
    ('B', '223', 2, 'double', 2, False),
    ('B', '224', 2, 'single', 1, False),
    ('B', '313', 3, 'single', 1, False),
    ('B', '314', 3, 'double', 2, False),
    ('B', '315', 3, 'double', 2, False),
    ('B', '316', 3, 'double', 2, False),
    ('B', '317', 3, 'double', 2, False),
    ('B', '318', 3, 'double', 2, False),
    ('B', '319', 3, 'double', 2, False),
    ('B', '320', 3, 'double', 2, False),
    ('B', '321', 3, 'double', 2, False),
    ('B', '322', 3, 'double', 2, False),
    ('B', '323', 3, 'double', 2, False),
    ('B', '324', 3, 'single', 1, False),
    ('B', '413', 4, 'single', 1, False),
    ('B', '414', 4, 'double', 2, False),
    ('B', '415', 4, 'double', 2, False),
    ('B', '416', 4, 'double', 2, False),
    ('B', '417', 4, 'double', 2, False),
    ('B', '418', 4, 'double', 2, False),
    ('B', '419', 4, 'double', 2, False),
    ('B', '420', 4, 'double', 2, False),
    ('B', '421', 4, 'double', 2, False),
    ('B', '422', 4, 'double', 2, False),
    ('B', '423', 4, 'double', 2, False),
    ('B', '424', 4, 'single', 1, False),
    ('B', '513', 5, 'single', 1, False),
    ('B', '514', 5, 'double', 2, False),
    ('B', '515', 5, 'double', 2, False),
    ('B', '516', 5, 'double', 2, False),
    ('B', '517', 5, 'double', 2, False),
    ('B', '518', 5, 'double', 2, False),
    ('B', '519', 5, 'double', 2, False),
    ('B', '520', 5, 'double', 2, False),
    ('B', '521', 5, 'double', 2, False),
    ('B', '522', 5, 'double', 2, False),
    ('B', '523', 5, 'double', 2, False),
    ('B', '524', 5, 'single', 1, False),
    ('B', '613', 6, 'single', 1, False),
    ('B', '614', 6, 'double', 2, False),
    ('B', '615', 6, 'double', 2, False),
    ('B', '616', 6, 'double', 2, False),
    ('B', '617', 6, 'double', 2, False),
    ('B', '618', 6, 'double', 2, False),
    ('B', '619', 6, 'double', 2, False),
    ('B', '620', 6, 'double', 2, False),
    ('B', '621', 6, 'double', 2, False),
    ('B', '622', 6, 'double', 2, False),
    ('B', '623', 6, 'double', 2, False),
    ('B', '624', 6, 'single', 1, False),
]

# Demo identities — the ONLY authorized users / property names allowed to
# survive the scrub. On a fresh demo DB every pre-existing row in
# authorized_users/properties came from migrate_all.py --seed / seed.py
# (the real business's admins and buildings), so the scrub removes/renames
# everything outside this set — no real details need to be embedded here.
DEMO_ADMIN_PHONES = {"919000000001", "919000000002"}
GENERIC_PROPERTY_NAMES = ["Building A", "Building B", "Building C", "Building D"]

TODAY = date(2026, 7, 20)  # matches "today" for this seed run (see script header)

# ══════════════════════════════════════════════════════════════════════════
# Name pools — fully fictional, never real business names
# ══════════════════════════════════════════════════════════════════════════

MALE_FIRST_NAMES = [
    "Aarav", "Vihaan", "Aditya", "Arjun", "Sai", "Reyansh", "Krishna", "Ishaan",
    "Rohan", "Karthik", "Vikram", "Siddharth", "Aryan", "Dev", "Nikhil", "Rahul",
    "Amit", "Suresh", "Ganesh", "Manoj", "Deepak", "Ashwin", "Harish", "Naveen",
    "Praveen", "Sandeep", "Vinay", "Yash", "Varun", "Tarun", "Akash", "Chirag",
    "Kunal", "Mohit", "Nitin", "Pranav", "Raghav", "Sameer", "Tanmay", "Uday",
    "Vishal", "Gautam", "Harsh", "Jayant", "Kartik", "Lakshman", "Madhav", "Neeraj",
    "Om", "Pankaj", "Rajat", "Sagar", "Tejas", "Umesh", "Vivek", "Aniket",
    "Bhavesh", "Chetan", "Dhruv", "Eshaan", "Girish", "Hemant", "Indraneel", "Jatin",
    "Kishore", "Lalit", "Manish", "Nishant", "Omkar", "Pratik", "Ramesh", "Satish",
    "Tushar", "Utkarsh", "Vaibhav", "Yogesh", "Abhinav", "Balaji", "Chandan",
]

FEMALE_FIRST_NAMES = [
    "Aanya", "Diya", "Ananya", "Ishita", "Kavya", "Meera", "Nisha", "Pooja",
    "Riya", "Sneha", "Tanvi", "Vidya", "Anjali", "Bhavya", "Charu", "Divya",
    "Esha", "Farah", "Gauri", "Hema", "Isha", "Jyoti", "Kajal", "Lavanya2",
    "Madhuri", "Nandini", "Oviya", "Priya", "Radha", "Sanya", "Trisha", "Uma",
    "Varsha", "Yamini", "Zara", "Aditi", "Bhoomi", "Chaitra", "Deepika", "Ekta",
    "Falguni", "Geetha", "Harini", "Indira", "Janani", "Kiruthika", "Lakshita",
    "Manasa", "Neha", "Ojasvi", "Pallavi", "Rachana", "Swathi", "Tejaswini", "Usha2",
    "Vaishnavi", "Yashika", "Aishwarya", "Bhavana", "Chandrika2", "Devika",
    "Eshwari", "Gayathri", "Harshita", "Ishwarya", "Jahnavi", "Keerthi", "Lasya",
    "Monika", "Nithya", "Padma", "Ramya", "Shreya", "Tanuja", "Vandana", "Yukti",
]

SURNAMES = [
    "Sharma", "Verma", "Iyer", "Nair", "Reddy", "Rao", "Menon", "Pillai",
    "Gupta", "Mehta", "Joshi", "Kulkarni", "Patil", "Desai", "Shah", "Bose",
    "Chatterjee", "Mukherjee", "Banerjee", "Das", "Kumar3", "Singh2", "Yadav",
    "Chauhan", "Rathore", "Bhatt", "Trivedi", "Pandey", "Mishra", "Tiwari",
    "Naidu", "Setty", "Gowda", "Hegde", "Shetty", "Kamath", "Bhat", "Prabhu",
    "Acharya", "Bhandari", "Chandra", "Dutta", "Ghosh", "Jain", "Kapoor",
    "Malhotra", "Nagar", "Oberoi", "Puri", "Rastogi", "Saxena", "Thakur",
    "Vyas", "Warrier", "Xalxo", "Yogi", "Zaveri", "Anand", "Balakrishnan",
    "Chidambaram",
]

FOOD_PREFS = ["veg", "non-veg", "egg"]
OCCUPATIONS = [
    "Software Engineer", "Data Analyst", "Student", "Marketing Executive",
    "Accountant", "Sales Associate", "Graphic Designer", "HR Executive",
    "Business Analyst", "Civil Engineer", "Mechanical Engineer", "Nurse",
    "Teacher", "Consultant", "Product Manager", "Customer Support",
]

INVESTORS = ["Rajesh Verma", "Anita Desai"]

# ══════════════════════════════════════════════════════════════════════════
# Fake phone generator — reserved fake range, never colliding with real numbers
# ══════════════════════════════════════════════════════════════════════════

_phone_counter = [0]


def next_fake_phone() -> str:
    """9xxxxxxxxx from a reserved demo range: 90000 00000 .. 90000 99999."""
    n = _phone_counter[0]
    _phone_counter[0] += 1
    if n > 99999:
        raise RuntimeError("Exhausted reserved fake phone range")
    return f"90000{n:05d}"


def gen_name(gender: str) -> str:
    pool = MALE_FIRST_NAMES if gender == "male" else FEMALE_FIRST_NAMES
    first = RNG.choice(pool)
    last = RNG.choice(SURNAMES)
    return f"{first} {last}"


def make_hash(*parts) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()


# ══════════════════════════════════════════════════════════════════════════
# Safety guard
# ══════════════════════════════════════════════════════════════════════════

async def safety_guard(confirm: bool) -> None:
    db_url = os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL") or ""
    if not db_url:
        print("ABORT: DATABASE_URL not set in environment/.env")
        sys.exit(1)

    host = urlparse(db_url.replace("postgresql+asyncpg://", "postgresql://")).hostname
    print(f"Target DB host: {host}")

    if os.environ.get("DEMO_MODE", "").lower() not in ("1", "true", "yes"):
        print("ABORT: DEMO_MODE env var is not set/truthy. Refusing to run.")
        print("       Set DEMO_MODE=1 to explicitly opt in to seeding demo data.")
        sys.exit(1)

    if not confirm:
        print("ABORT: --confirm flag not passed. Refusing to run.")
        sys.exit(1)

    init_engine(db_url)
    async with get_session() as session:
        tenant_count = await session.scalar(select(func.count()).select_from(Tenant))
        if tenant_count and tenant_count > 0:
            print(f"ABORT: tenants table already has {tenant_count} rows. "
                  "This script only runs against a FRESH database (zero tenants).")
            sys.exit(1)

    print("Safety checks passed. Proceeding with demo seed...")


# ══════════════════════════════════════════════════════════════════════════
# Room + property seeding (only runs when `rooms` table is empty)
# ══════════════════════════════════════════════════════════════════════════

async def seed_rooms_if_empty(session) -> tuple[int, int]:
    """If the `rooms` table already has rows, do nothing (use what's there).
    Otherwise create the 2 generic property rows + all rooms from ROOMS_DATA.
    Returns (properties_created, rooms_created)."""
    existing = await session.scalar(select(func.count()).select_from(Room))
    if existing and existing > 0:
        print(f"  [skip] rooms table already has {existing} rows — using existing layout")
        return (0, 0)

    prop_a = Property(name="Building A", address="Demo Address", owner_name="Demo Admin",
                       total_rooms=0, active=True)
    prop_b = Property(name="Building B", address="Demo Address", owner_name="Demo Admin",
                       total_rooms=0, active=True)
    session.add_all([prop_a, prop_b])
    await session.flush()

    prop_by_letter = {"A": prop_a, "B": prop_b}
    rooms_created = 0
    counts = {"A": 0, "B": 0}
    for building, room_number, floor, room_type, max_occ, is_staff in ROOMS_DATA:
        prop = prop_by_letter[building]
        session.add(Room(
            property_id=prop.id,
            room_number=room_number,
            floor=floor,
            room_type=RoomType(room_type),
            max_occupancy=max_occ,
            is_staff_room=is_staff,
            active=True,
        ))
        rooms_created += 1
        counts[building] += 1

    prop_a.total_rooms = counts["A"]
    prop_b.total_rooms = counts["B"]
    await session.flush()
    print(f"  [ok] rooms seeded from ROOMS_DATA: {rooms_created} rooms "
          f"(Building A: {counts['A']}, Building B: {counts['B']})")
    return (2, rooms_created)


# ══════════════════════════════════════════════════════════════════════════
# Authorized-users + property-name scrub — removes real people/brand names
# inserted by migrate_all.py --seed / src/database/seed.py on a fresh DB.
# ══════════════════════════════════════════════════════════════════════════

def _norm_phone(p: str) -> str:
    return "".join(c for c in str(p or "") if c.isdigit())


async def scrub_authorized_users_and_properties(session) -> dict:
    """Remove every authorized user that isn't a demo identity, and rename
    every property not already carrying a generic name. On a fresh demo DB
    all pre-existing rows were inserted by migrate_all.py --seed / seed.py
    with the real business's data — none of them belong in a demo."""
    result = {"users_deleted": 0, "users_inserted": 0, "properties_renamed": 0}

    demo_phones_norm = {_norm_phone(p) for p in DEMO_ADMIN_PHONES}
    users = (await session.execute(select(AuthorizedUser))).scalars().all()
    for u in users:
        if _norm_phone(u.phone) not in demo_phones_norm:
            await session.delete(u)
            result["users_deleted"] += 1

    # Insert generic demo replacements (idempotent-ish: skip if already present)
    demo_users = [
        ("Demo Admin",   "919000000001", UserRole.admin),
        ("Demo Manager", "919000000002", UserRole.owner),
    ]
    for name, phone, role in demo_users:
        exists = await session.scalar(select(AuthorizedUser).where(AuthorizedUser.phone == phone))
        if exists:
            continue
        session.add(AuthorizedUser(name=name, phone=phone, role=role, added_by="demo_seed", active=True))
        result["users_inserted"] += 1

    # Rename any property row not already carrying a generic demo name
    # (covers "Cozeevo THOR"/"Cozeevo HULK" created by migrate_all/seed.py,
    # without embedding the real names here).
    props = (await session.execute(select(Property))).scalars().all()
    used_names = {p.name for p in props if p.name in GENERIC_PROPERTY_NAMES}
    for p in props:
        if p.name in GENERIC_PROPERTY_NAMES:
            continue
        new_name = next((n for n in GENERIC_PROPERTY_NAMES if n not in used_names),
                        f"Building {len(used_names) + 1}")
        used_names.add(new_name)
        p.name = new_name
        p.owner_name = "Demo Admin"
        p.phone = None
        result["properties_renamed"] += 1

    await session.flush()
    print(f"  [ok] authorized_users scrubbed: {result['users_deleted']} deleted, "
          f"{result['users_inserted']} demo rows inserted; "
          f"{result['properties_renamed']} property rows renamed")
    return result


# ══════════════════════════════════════════════════════════════════════════
# Room helpers
# ══════════════════════════════════════════════════════════════════════════

RENT_RANGES = {
    "single":  (16000, 24000),
    "double":  (11000, 15000),
    "triple":  (8000, 11000),
    "premium": (24000, 28000),
}

MAINTENANCE_FEE = Decimal("5000")


async def load_rooms(session) -> list[Room]:
    rooms = (await session.execute(
        select(Room).where(Room.active == True, Room.room_number != "000")
    )).scalars().all()
    if not rooms:
        print("ABORT: no rooms found in `rooms` table. Load room master data first "
              "(migrate_all.py does NOT seed rooms/properties — see its --seed output).")
        sys.exit(1)
    return list(rooms)


def room_type_str(room: Room) -> str:
    return room.room_type.value if hasattr(room.room_type, "value") else str(room.room_type)


def rent_for_room(room: Room) -> Decimal:
    lo, hi = RENT_RANGES.get(room_type_str(room), (10000, 15000))
    return Decimal(RNG.randrange(lo, hi + 1, 500))


def sharing_for_room(room: Room, whole_room: bool = False) -> SharingType:
    if whole_room:
        return SharingType.premium
    rt = room_type_str(room)
    try:
        return SharingType(rt)
    except ValueError:
        return SharingType.double


# ══════════════════════════════════════════════════════════════════════════
# Weighted check-in date generator (Mar-Jul 2026, weighted earlier)
# ══════════════════════════════════════════════════════════════════════════

MONTHS_MAR_JUL = [(2026, 3), (2026, 4), (2026, 5), (2026, 6), (2026, 7)]
MONTH_WEIGHTS = [30, 26, 22, 14, 8]  # weighted earlier


def random_checkin_date(max_month: tuple[int, int] | None = None, upto_today: bool = False) -> date:
    import calendar as _cal
    choices = MONTHS_MAR_JUL
    weights = MONTH_WEIGHTS
    if max_month:
        idx = choices.index(max_month) if max_month in choices else len(choices) - 1
        choices = choices[: idx + 1]
        weights = weights[: idx + 1]
    y, m = RNG.choices(choices, weights=weights, k=1)[0]
    last_day = _cal.monthrange(y, m)[1]
    if upto_today and (y, m) == (TODAY.year, TODAY.month):
        last_day = min(last_day, TODAY.day)
    day = RNG.randint(1, last_day)
    return date(y, m, day)


def months_between(start: date, end: date) -> list[date]:
    """List of 1st-of-month dates from start's month to end's month inclusive."""
    out = []
    cur = start.replace(day=1)
    end_m = end.replace(day=1)
    while cur <= end_m:
        out.append(cur)
        if cur.month == 12:
            cur = cur.replace(year=cur.year + 1, month=1)
        else:
            cur = cur.replace(month=cur.month + 1)
    return out


# ══════════════════════════════════════════════════════════════════════════
# Tenant + tenancy creation (active monthly)
# ══════════════════════════════════════════════════════════════════════════

async def create_active_monthly_tenant(
    session, room: Room, whole_room: bool = False,
) -> Tenancy:
    gender = RNG.choice(["male", "female"])
    name = gen_name(gender)
    phone = next_fake_phone()
    checkin = random_checkin_date(upto_today=True)
    rent = rent_for_room(room)
    deposit = rent  # one month rent
    tenant = Tenant(
        name=name,
        gender=gender,
        phone=phone,
        occupation=RNG.choice(OCCUPATIONS),
        food_preference=RNG.choice(FOOD_PREFS),
        emergency_contact_name=gen_name(gender),
        emergency_contact_phone=next_fake_phone(),
        emergency_contact_relationship=RNG.choice(["Father", "Mother", "Sibling", "Friend"]),
        id_proof_type="Aadhar",
        id_proof_number=f"DEMO{RNG.randint(100000000000, 999999999999)}",
    )
    session.add(tenant)
    await session.flush()

    tenancy = Tenancy(
        tenant_id=tenant.id,
        room_id=room.id,
        stay_type=StayType.monthly,
        sharing_type=sharing_for_room(room, whole_room),
        status=TenancyStatus.active,
        checkin_date=checkin,
        booking_amount=Decimal("0"),
        security_deposit=deposit,
        maintenance_fee=MAINTENANCE_FEE,
        agreed_rent=rent,
        entered_by="demo_seed",
    )
    session.add(tenancy)
    await session.flush()
    return tenancy


async def seed_rent_schedule_and_payments(session, tenancy: Tenancy) -> None:
    """Create RentSchedule rows checkin-month -> July, first month prorated
    per src/services/rent_schedule.first_month_rent_due(). Populate payments
    ~85% fully paid, ~10% partial, ~5% unpaid for the CURRENT month; earlier
    months are always paid in full (a live tenant with old unpaid dues would
    already be on notice)."""
    periods = months_between(tenancy.checkin_date, TODAY)
    current_period = TODAY.replace(day=1)

    for period in periods:
        due = first_month_rent_due(tenancy, period)
        rs = RentSchedule(
            tenancy_id=tenancy.id,
            period_month=period,
            rent_due=due,
            maintenance_due=Decimal("0"),
            status=RentStatus.pending,
            due_date=period,
        )
        session.add(rs)

        is_current = period == current_period
        roll = RNG.random()
        if is_current:
            if roll < 0.85:
                pay_fraction = 1.0
            elif roll < 0.95:
                pay_fraction = RNG.choice([0.3, 0.5, 0.6])
            else:
                pay_fraction = 0.0
        else:
            pay_fraction = 1.0  # historical months always settled

        if pay_fraction <= 0:
            rs.status = RentStatus.pending
            continue

        paid_amount = (due * Decimal(str(pay_fraction))).quantize(Decimal("1"))
        if paid_amount <= 0:
            continue

        mode = PaymentMode.upi if RNG.random() < 0.6 else PaymentMode.cash
        pay_day = min(RNG.randint(1, 10), 28)
        # Never date a payment before check-in or after "today"
        py, pm = period.year, period.month
        pdate = date(py, pm, pay_day)
        if pdate < tenancy.checkin_date:
            pdate = tenancy.checkin_date
        if pdate > TODAY:
            pdate = TODAY

        payment = Payment(
            tenancy_id=tenancy.id,
            amount=paid_amount,
            payment_date=pdate,
            payment_mode=mode,
            for_type=PaymentFor.rent,
            period_month=period,
            notes="Demo seed rent payment",
        )
        session.add(payment)
        rs.status = RentStatus.paid if pay_fraction >= 0.999 else RentStatus.partial


# ══════════════════════════════════════════════════════════════════════════
# Day-stay tenants
# ══════════════════════════════════════════════════════════════════════════

DAY_RATE_RANGE = (600, 1200)


async def create_daystay_tenant(session, room: Room, active: bool) -> Tenancy:
    gender = RNG.choice(["male", "female"])
    name = gen_name(gender)
    phone = next_fake_phone()
    nights = RNG.randint(1, 8)
    if active:
        checkin = TODAY - timedelta(days=RNG.randint(0, min(nights - 1, nights)))
        checkout = checkin + timedelta(days=nights)
    else:
        checkin = random_checkin_date()
        checkout = checkin + timedelta(days=nights)
        if checkout >= TODAY:
            checkout = TODAY - timedelta(days=RNG.randint(1, 5))
            if checkout <= checkin:
                checkout = checkin + timedelta(days=1)

    rate = Decimal(RNG.randrange(*DAY_RATE_RANGE, 50))
    total = rate * nights
    deposit = Decimal(RNG.choice([500, 1000, 1500]))

    tenant = Tenant(
        name=name, gender=gender, phone=phone,
        occupation=RNG.choice(OCCUPATIONS),
        food_preference=RNG.choice(FOOD_PREFS),
    )
    session.add(tenant)
    await session.flush()

    status = TenancyStatus.active if active else TenancyStatus.exited
    tenancy = Tenancy(
        tenant_id=tenant.id,
        room_id=room.id,
        stay_type=StayType.daily,
        sharing_type=sharing_for_room(room),
        status=status,
        checkin_date=checkin,
        checkout_date=None if active else checkout,
        booking_amount=deposit,
        security_deposit=deposit,
        maintenance_fee=Decimal("0"),
        agreed_rent=rate,  # daily convention: agreed_rent holds per-day rate
        entered_by="demo_seed",
    )
    session.add(tenancy)
    await session.flush()

    payment = Payment(
        tenancy_id=tenancy.id,
        amount=total,
        payment_date=checkin,
        payment_mode=RNG.choice([PaymentMode.upi, PaymentMode.cash]),
        for_type=PaymentFor.rent,
        notes="Demo seed day-stay payment",
    )
    session.add(payment)

    if not active:
        cr = CheckoutRecord(
            tenancy_id=tenancy.id,
            cupboard_key_returned=True,
            main_key_returned=True,
            pending_dues_amount=Decimal("0"),
            deposit_refunded_amount=deposit,
            deposit_refund_date=checkout,
            actual_exit_date=checkout,
            recorded_by="demo_seed",
            biometric_removed=True,
            room_condition_ok=True,
        )
        session.add(cr)

    return tenancy


# ══════════════════════════════════════════════════════════════════════════
# Exited monthly tenancies (history) + checkout records
# ══════════════════════════════════════════════════════════════════════════

async def create_exited_monthly_tenant(session, room: Room) -> Tenancy:
    gender = RNG.choice(["male", "female"])
    name = gen_name(gender)
    phone = next_fake_phone()
    checkin_month = RNG.choice(MONTHS_MAR_JUL[:4])  # Mar-Jun checkin
    import calendar as _cal
    last_day = _cal.monthrange(*checkin_month)[1]
    checkin = date(checkin_month[0], checkin_month[1], RNG.randint(1, min(15, last_day)))
    stay_months = RNG.randint(1, 3)
    checkout_period_idx = MONTHS_MAR_JUL.index(checkin_month) + stay_months
    checkout_period_idx = min(checkout_period_idx, 4)  # cap at Jul
    co_y, co_m = MONTHS_MAR_JUL[checkout_period_idx]
    co_last = _cal.monthrange(co_y, co_m)[1]
    checkout = date(co_y, co_m, RNG.randint(1, co_last))
    if checkout <= checkin:
        checkout = checkin + timedelta(days=30)
    if checkout >= TODAY:
        checkout = TODAY - timedelta(days=RNG.randint(1, 20))
    if checkout <= checkin:
        checkout = checkin + timedelta(days=15)

    rent = rent_for_room(room)
    deposit = rent

    tenant = Tenant(
        name=name, gender=gender, phone=phone,
        occupation=RNG.choice(OCCUPATIONS),
        food_preference=RNG.choice(FOOD_PREFS),
        id_proof_type="Aadhar",
        id_proof_number=f"DEMO{RNG.randint(100000000000, 999999999999)}",
    )
    session.add(tenant)
    await session.flush()

    notice_given = RNG.random() < 0.7
    notice_date = None
    if notice_given:
        nd_month = checkout.month - 1 or 12
        nd_year = checkout.year if checkout.month > 1 else checkout.year - 1
        nd_last = _cal.monthrange(nd_year, nd_month)[1]
        notice_date = date(nd_year, nd_month, RNG.randint(1, nd_last))
        if notice_date >= checkout:
            notice_date = None

    tenancy = Tenancy(
        tenant_id=tenant.id,
        room_id=room.id,
        stay_type=StayType.monthly,
        sharing_type=sharing_for_room(room),
        status=TenancyStatus.exited,
        checkin_date=checkin,
        checkout_date=checkout,
        notice_date=notice_date,
        booking_amount=Decimal("0"),
        security_deposit=deposit,
        maintenance_fee=MAINTENANCE_FEE,
        agreed_rent=rent,
        entered_by="demo_seed",
    )
    session.add(tenancy)
    await session.flush()

    # Rent schedule + payments for every month of the stay, all fully paid (exited clean)
    for period in months_between(checkin, checkout):
        due = first_month_rent_due(tenancy, period)
        rs = RentSchedule(
            tenancy_id=tenancy.id, period_month=period, rent_due=due,
            maintenance_due=Decimal("0"), status=RentStatus.paid, due_date=period,
        )
        session.add(rs)
        pdate = max(period, checkin)
        pdate = min(pdate + timedelta(days=RNG.randint(0, 5)), checkout)
        session.add(Payment(
            tenancy_id=tenancy.id, amount=due, payment_date=pdate,
            payment_mode=RNG.choice([PaymentMode.upi, PaymentMode.cash]),
            for_type=PaymentFor.rent, period_month=period,
            notes="Demo seed rent payment",
        ))

    # Checkout record — deposit refund minus maintenance
    refund = max(deposit - MAINTENANCE_FEE, Decimal("0"))
    session.add(CheckoutRecord(
        tenancy_id=tenancy.id,
        cupboard_key_returned=True,
        main_key_returned=True,
        pending_dues_amount=Decimal("0"),
        deposit_refunded_amount=refund,
        deposit_refund_date=checkout + timedelta(days=RNG.randint(1, 7)),
        actual_exit_date=checkout,
        recorded_by="demo_seed",
        biometric_removed=True,
        room_condition_ok=True,
        deductions=MAINTENANCE_FEE,
        deduction_reason="Maintenance fee retained",
        refund_mode=RNG.choice(["upi", "cash"]),
    ))
    return tenancy


# ══════════════════════════════════════════════════════════════════════════
# Active notices (on active monthly tenants)
# ══════════════════════════════════════════════════════════════════════════

async def give_notice(session, tenancy: Tenancy, late: bool) -> None:
    import calendar as _cal
    day = RNG.randint(6, 25) if late else RNG.randint(1, 5)
    day = min(day, _cal.monthrange(TODAY.year, TODAY.month)[1])
    notice_date = date(TODAY.year, TODAY.month, day)
    if late:
        m = TODAY.month + 1
        y = TODAY.year
        if m > 12:
            m, y = 1, y + 1
        last = _cal.monthrange(y, m)[1]
        expected_checkout = date(y, m, last)
    else:
        last = _cal.monthrange(TODAY.year, TODAY.month)[1]
        expected_checkout = date(TODAY.year, TODAY.month, last)
    tenancy.notice_date = notice_date
    tenancy.expected_checkout = expected_checkout
    session.add(tenancy)


# ══════════════════════════════════════════════════════════════════════════
# Pending bookings / onboarding sessions (no_show tenancies with advances)
# ══════════════════════════════════════════════════════════════════════════

async def create_pending_booking(session, room: Room, status: str) -> None:
    gender = RNG.choice(["male", "female"])
    name = gen_name(gender)
    phone = next_fake_phone()
    checkin = TODAY + timedelta(days=RNG.randint(1, 20))
    rent = rent_for_room(room)
    deposit = rent
    booking_amount = Decimal(RNG.choice([2000, 3000, 5000]))

    tenant = Tenant(name=name, gender=gender, phone=phone)
    session.add(tenant)
    await session.flush()

    sharing = sharing_for_room(room)
    tenancy = Tenancy(
        tenant_id=tenant.id,
        room_id=room.id,
        stay_type=StayType.monthly,
        sharing_type=sharing,
        status=TenancyStatus.no_show,
        checkin_date=checkin,
        booking_amount=booking_amount,
        security_deposit=deposit,
        maintenance_fee=MAINTENANCE_FEE,
        agreed_rent=rent,
        entered_by="demo_seed_quick_book",
    )
    session.add(tenancy)
    await session.flush()

    session.add(Payment(
        tenancy_id=tenancy.id,
        amount=booking_amount,
        payment_date=TODAY,
        payment_mode=RNG.choice([PaymentMode.upi, PaymentMode.cash]),
        for_type=PaymentFor.booking,
        notes="Demo seed advance at pre-booking",
    ))

    import uuid as _uuid
    import json as _json
    obs = OnboardingSession(
        token=str(_uuid.uuid4()),
        status=status,
        created_by_phone="90000000000",
        tenant_phone=phone,
        room_id=room.id,
        agreed_rent=rent,
        security_deposit=deposit,
        maintenance_fee=MAINTENANCE_FEE,
        booking_amount=booking_amount,
        advance_mode="upi",
        sharing_type=sharing.value,
        checkin_date=checkin,
        stay_type="monthly",
        tenant_data=_json.dumps({"name": name}),
        tenant_id=tenant.id,
        tenancy_id=tenancy.id,
        expires_at=datetime.utcnow() + timedelta(hours=48),
    )
    session.add(obs)


# ══════════════════════════════════════════════════════════════════════════
# Complaints + operational logs
# ══════════════════════════════════════════════════════════════════════════

async def create_complaints(session, tenancies: list[Tenancy], n: int) -> int:
    if not tenancies:
        return 0
    count = 0
    categories = list(ComplaintCategory)
    for _ in range(n):
        t = RNG.choice(tenancies)
        cat = RNG.choice(categories)
        status = RNG.choices(
            list(ComplaintStatus), weights=[40, 20, 30, 10], k=1
        )[0]
        desc_map = {
            ComplaintCategory.plumbing: "Tap leaking in bathroom",
            ComplaintCategory.electricity: "Fan not working",
            ComplaintCategory.wifi: "WiFi very slow in room",
            ComplaintCategory.food: "Food quality needs improvement",
            ComplaintCategory.furniture: "Chair is broken",
            ComplaintCategory.other: "General maintenance request",
        }
        c = Complaint(
            tenancy_id=t.id,
            category=cat,
            description=desc_map.get(cat, "General request"),
            status=status,
            created_at=datetime.combine(TODAY - timedelta(days=RNG.randint(0, 20)), datetime.min.time()),
        )
        if status in (ComplaintStatus.resolved, ComplaintStatus.closed):
            c.resolved_at = datetime.combine(TODAY - timedelta(days=RNG.randint(0, 10)), datetime.min.time())
            c.resolved_by = "90000000000"
        session.add(c)
        count += 1
    return count


async def create_operational_logs(session, n: int) -> int:
    categories = ["power_outage", "hp_gas", "water_tanker", "garbage_collection"]
    for i in range(n):
        cat = RNG.choice(categories)
        details = {
            "power_outage": {"duration_hours": RNG.randint(1, 4)},
            "hp_gas": {"cylinders": RNG.randint(1, 3)},
            "water_tanker": {"liters": RNG.choice([5000, 8000, 10000])},
            "garbage_collection": {"status": "collected"},
        }[cat]
        session.add(OperationalLog(
            category=cat,
            details=details,
            notes="Demo seed log",
            logged_by="Demo Staff",
            created_at=datetime.combine(TODAY - timedelta(days=RNG.randint(0, 60)), datetime.min.time()),
        ))
    return n


# ══════════════════════════════════════════════════════════════════════════
# Finance — bank_transactions, pnl_monthly_adjustments, investment_expenses
# ══════════════════════════════════════════════════════════════════════════

EXPENSE_CATEGORIES_AMOUNTS = {
    # category -> (weight, min, max) per single-transaction spread across the month
    "Property Rent":         (2,  180000, 260000),
    "Electricity":            (2,   80000, 140000),
    "Water":                  (3,    6000,  15000),
    "IT & Software":          (2,    2000,   8000),
    "Internet & WiFi":        (2,    3000,   9000),
    "Food & Groceries":       (14,   8000,  35000),
    "Fuel & Diesel":          (3,    3000,  12000),
    "Staff & Labour":         (8,   15000,  45000),
    "Maintenance & Repairs":  (6,    3000,  20000),
    "Cleaning Supplies":      (4,    2000,   8000),
    "Waste Disposal":         (1,    3000,   4000),
    "Shopping & Supplies":    (4,    2000,  10000),
    "Furniture & Fittings":   (2,    5000,  30000),
    "Marketing":              (2,    2000,  10000),
    "Govt & Regulatory":      (1,    3000,  15000),
    "Bank Charges":           (2,     200,   2000),
    "Other Expenses":         (3,    1000,   8000),
}

VENDOR_DESCRIPTIONS = {
    "Property Rent": ["UPI/Landlord Rent Payment", "NEFT Property Rent"],
    "Electricity": ["BESCOM Bill Payment", "EB Bill UPI"],
    "Water": ["Water Tanker Vendor", "BWSSB Bill"],
    "IT & Software": ["Hostinger VPS", "Software Subscription"],
    "Internet & WiFi": ["Broadband Bill", "WiFi Vendor UPI"],
    "Food & Groceries": ["Grocery Vendor UPI", "Vegetable Supplier", "Kirana Store Payment"],
    "Fuel & Diesel": ["Diesel Vendor", "Fuel Station UPI"],
    "Staff & Labour": ["Staff Salary UPI", "Housekeeping Payment"],
    "Maintenance & Repairs": ["Plumber Payment", "Electrician UPI", "Handyman Service"],
    "Cleaning Supplies": ["Cleaning Supplies Vendor"],
    "Waste Disposal": ["Garbage Collection Vendor"],
    "Shopping & Supplies": ["General Supplies UPI", "Hardware Store"],
    "Furniture & Fittings": ["Furniture Vendor", "Fittings Purchase"],
    "Marketing": ["Marketing Agency UPI", "Ad Spend"],
    "Govt & Regulatory": ["BBMP Tax Payment", "Govt Fee"],
    "Bank Charges": ["Bank Service Charge", "IMPS Charges"],
    "Other Expenses": ["Misc UPI Payment"],
}


def _spread_days(year: int, month: int, n: int) -> list[date]:
    import calendar as _cal
    last = _cal.monthrange(year, month)[1]
    return sorted(date(year, month, RNG.randint(1, last)) for _ in range(n))


async def seed_bank_month(session, upload_thor: BankUpload, upload_hulk: BankUpload,
                           year: int, month: int, target_revenue: int, target_opex: int,
                           running_balance: dict) -> None:
    """Seed income + expense bank_transactions for one month across THOR/HULK,
    plus a matching pnl_monthly_adjustments row. running_balance is a mutable
    dict {"THOR": float, "HULK": float} tracking the running balance across months."""
    import calendar as _cal
    last_day = _cal.monthrange(year, month)[1]

    # ── Income: rent credits split ~60/40 THOR/HULK, ~18-22 txns per account ──
    for acct, upload, weight in (("THOR", upload_thor, 0.6), ("HULK", upload_hulk, 0.4)):
        acct_target = int(target_revenue * weight)
        n_txns = RNG.randint(16, 22)
        amounts = []
        remaining = acct_target
        for i in range(n_txns):
            if i == n_txns - 1:
                amt = max(remaining, 5000)
            else:
                amt = RNG.randint(8000, 22000)
                amt = min(amt, max(remaining - 5000 * (n_txns - i - 1), 5000))
            amounts.append(max(amt, 1000))
            remaining -= amt
        for amt, d in zip(amounts, _spread_days(year, month, len(amounts))):
            running_balance[acct] += amt
            desc = f"UPI/Tenant Rent Payment {RNG.randint(100000,999999)}"
            uhash = make_hash("income", acct, d, amt, desc, RNG.random())
            session.add(BankTransaction(
                upload_id=upload.id, txn_date=d, description=desc,
                amount=Decimal(amt), txn_type="income", category="Rent Income",
                sub_category="Direct UPI from Tenants", source="bank_statement",
                unique_hash=uhash, account_name=acct,
                balance=Decimal(str(round(running_balance[acct], 2))),
            ))

    # ── Expenses: spread across categories, weighted, capped near target_opex ──
    total_weight = sum(w for w, _, _ in EXPENSE_CATEGORIES_AMOUNTS.values())
    spent = 0
    for cat, (weight, lo, hi) in EXPENSE_CATEGORIES_AMOUNTS.items():
        cat_budget = int(target_opex * weight / total_weight)
        n_txns = max(1, weight // 2)
        per_txn = max(cat_budget // n_txns, lo)
        descs = VENDOR_DESCRIPTIONS.get(cat, ["Vendor Payment"])
        for d in _spread_days(year, month, n_txns):
            amt = RNG.randint(lo, hi) if n_txns > 1 else max(per_txn, lo)
            amt = min(amt, hi)
            acct = RNG.choice(["THOR", "HULK"])
            upload = upload_thor if acct == "THOR" else upload_hulk
            running_balance[acct] -= amt
            desc = RNG.choice(descs)
            uhash = make_hash("expense", acct, d, amt, desc, cat, RNG.random())
            session.add(BankTransaction(
                upload_id=upload.id, txn_date=d, description=desc,
                amount=Decimal(amt), txn_type="expense", category=cat,
                sub_category="", source="bank_statement",
                unique_hash=uhash, account_name=acct,
                balance=Decimal(str(round(running_balance[acct], 2))),
            ))
            spent += amt

    # ── Manual P&L adjustments (cash figures never in the bank CSV) ──
    session.add(PnlMonthlyAdjustment(
        month=date(year, month, 1),
        cash_holding=Decimal(RNG.randint(30000, 90000)),
        rent_paid_cash=Decimal(RNG.randint(20000, 60000)),
        cash_expense=Decimal(RNG.randint(5000, 25000)),
        notes="Demo seed adjustment",
        updated_by="demo_seed",
    ))


async def seed_investment_expenses(session) -> int:
    count = 0
    for investor in INVESTORS:
        for i in range(3):
            d = date(2026, RNG.choice([3, 4, 5]), RNG.randint(1, 28))
            amt = Decimal(RNG.randint(50000, 300000))
            purpose = RNG.choice([
                "Furniture procurement", "Interior setup", "Equipment purchase",
                "Renovation contribution", "Working capital top-up",
            ])
            uhash = make_hash("investment", investor, d, amt, purpose, i)
            session.add(InvestmentExpense(
                sno=count + 1,
                purpose=purpose,
                amount=amt,
                paid_by=investor,
                transaction_date=d,
                transaction_id=f"DEMO-TXN-{RNG.randint(100000,999999)}",
                paid_to="Demo Vendor",
                property="Demo PG",
                unique_hash=uhash,
                notes="Demo seed investment expense",
            ))
            count += 1
    return count


# ══════════════════════════════════════════════════════════════════════════
# Main orchestration
# ══════════════════════════════════════════════════════════════════════════

async def run(confirm: bool) -> None:
    await safety_guard(confirm)

    counts = {
        "properties_created": 0,
        "rooms_created": 0,
        "rooms_found": 0,
        "authorized_users_deleted": 0,
        "authorized_users_inserted": 0,
        "properties_renamed": 0,
        "active_monthly_tenants": 0,
        "active_daystay_tenants": 0,
        "exited_daystay_tenants": 0,
        "exited_monthly_tenants": 0,
        "notices_active": 0,
        "pending_bookings": 0,
        "complaints": 0,
        "operational_logs": 0,
        "payments": 0,
        "rent_schedule_rows": 0,
        "bank_transactions": 0,
        "pnl_adjustments": 0,
        "investment_expenses": 0,
        "checkout_records": 0,
    }

    async with get_session() as session:
        props_created, rooms_created_n = await seed_rooms_if_empty(session)
        counts["properties_created"] = props_created
        counts["rooms_created"] = rooms_created_n

        scrub_result = await scrub_authorized_users_and_properties(session)
        counts["authorized_users_deleted"] = scrub_result["users_deleted"]
        counts["authorized_users_inserted"] = scrub_result["users_inserted"]
        counts["properties_renamed"] = scrub_result["properties_renamed"]

        rooms = await load_rooms(session)
        counts["rooms_found"] = len(rooms)
        RNG.shuffle(rooms)

        non_staff_rooms = [r for r in rooms if not r.is_staff_room]
        if not non_staff_rooms:
            print("ABORT: every room is flagged is_staff_room — nothing to seed.")
            sys.exit(1)

        # ── Occupy ~92% of non-staff beds with active monthly tenants ────────
        # Reserve a handful of rooms as whole-room "premium" bookings.
        premium_room_count = max(1, len(non_staff_rooms) // 20)
        premium_rooms = set(r.id for r in non_staff_rooms[:premium_room_count])

        active_tenancies: list[Tenancy] = []
        total_beds = sum(max(r.max_occupancy or 1, 1) for r in non_staff_rooms)
        target_occupied_beds = int(total_beds * 0.92)
        occupied_beds = 0

        for room in non_staff_rooms:
            if occupied_beds >= target_occupied_beds:
                break
            capacity = max(room.max_occupancy or 1, 1)
            whole_room = room.id in premium_rooms
            if whole_room:
                tenancy = await create_active_monthly_tenant(session, room, whole_room=True)
                await seed_rent_schedule_and_payments(session, tenancy)
                active_tenancies.append(tenancy)
                occupied_beds += capacity
                continue
            beds_to_fill = capacity if RNG.random() < 0.85 else max(capacity - 1, 0)
            for _ in range(beds_to_fill):
                if occupied_beds >= target_occupied_beds:
                    break
                tenancy = await create_active_monthly_tenant(session, room)
                await seed_rent_schedule_and_payments(session, tenancy)
                active_tenancies.append(tenancy)
                occupied_beds += 1

        counts["active_monthly_tenants"] = len(active_tenancies)

        # ── Active notices on a handful of active tenants ────────────────────
        notice_candidates = RNG.sample(active_tenancies, min(6, len(active_tenancies)))
        for i, t in enumerate(notice_candidates):
            late = i % 3 == 0  # ~1/3 late notices
            await give_notice(session, t, late=late)
            counts["notices_active"] += 1

        # ── Day-stay tenants: ~8-10 across the months, 2-3 active ────────────
        daystay_room_pool = non_staff_rooms[: min(12, len(non_staff_rooms))]
        n_daystay_active = 3
        n_daystay_history = 6
        for _ in range(n_daystay_active):
            room = RNG.choice(daystay_room_pool)
            await create_daystay_tenant(session, room, active=True)
            counts["active_daystay_tenants"] += 1
        for _ in range(n_daystay_history):
            room = RNG.choice(daystay_room_pool)
            await create_daystay_tenant(session, room, active=False)
            counts["exited_daystay_tenants"] += 1
            counts["checkout_records"] += 1

        # ── History: ~40 exited monthly tenancies spread Mar-Jun ────────────
        for _ in range(40):
            room = RNG.choice(non_staff_rooms)
            await create_exited_monthly_tenant(session, room)
            counts["exited_monthly_tenants"] += 1
            counts["checkout_records"] += 1

        # ── Pending bookings: ~6 no_show tenancies with advances ────────────
        for i in range(6):
            room = RNG.choice(non_staff_rooms)
            status = "pending_review" if i < 2 else "pending_tenant"
            await create_pending_booking(session, room, status)
            counts["pending_bookings"] += 1

        # ── Complaints + operational logs ────────────────────────────────────
        all_tenancies_for_complaints = active_tenancies
        counts["complaints"] = await create_complaints(session, all_tenancies_for_complaints, 12)
        counts["operational_logs"] = await create_operational_logs(session, 10)

        await session.flush()

        # ── Finance: bank_transactions for Jun + Jul 2026 ────────────────────
        upload_thor_jun = BankUpload(phone="90000000000", file_path="demo_seed_thor_jun.csv",
                                      row_count=0, new_count=0, status="processed", account_name="THOR")
        upload_hulk_jun = BankUpload(phone="90000000000", file_path="demo_seed_hulk_jun.csv",
                                      row_count=0, new_count=0, status="processed", account_name="HULK")
        upload_thor_jul = BankUpload(phone="90000000000", file_path="demo_seed_thor_jul.csv",
                                      row_count=0, new_count=0, status="processed", account_name="THOR")
        upload_hulk_jul = BankUpload(phone="90000000000", file_path="demo_seed_hulk_jul.csv",
                                      row_count=0, new_count=0, status="processed", account_name="HULK")
        session.add_all([upload_thor_jun, upload_hulk_jun, upload_thor_jul, upload_hulk_jul])
        await session.flush()

        running_balance = {"THOR": 850000.0, "HULK": 1900000.0}

        before = await session.scalar(select(func.count()).select_from(BankTransaction))
        await seed_bank_month(session, upload_thor_jun, upload_hulk_jun, 2026, 6,
                               target_revenue=3300000, target_opex=2700000, running_balance=running_balance)
        await seed_bank_month(session, upload_thor_jul, upload_hulk_jul, 2026, 7,
                               target_revenue=3400000, target_opex=2800000, running_balance=running_balance)
        await session.flush()
        after = await session.scalar(select(func.count()).select_from(BankTransaction))
        counts["bank_transactions"] = (after or 0) - (before or 0)
        counts["pnl_adjustments"] = 2

        # ── Investment expenses (2 fictional investors) ──────────────────────
        counts["investment_expenses"] = await seed_investment_expenses(session)

        await session.flush()

        # ── Final counts that need a query ────────────────────────────────
        counts["payments"] = await session.scalar(select(func.count()).select_from(Payment)) or 0
        counts["rent_schedule_rows"] = await session.scalar(select(func.count()).select_from(RentSchedule)) or 0

    print("\n== Demo seed complete ==")
    for k, v in counts.items():
        print(f"  {k}: {v}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed a fresh demo DB with fictional data")
    parser.add_argument("--confirm", action="store_true",
                         help="Required — explicit confirmation to run")
    args = parser.parse_args()
    asyncio.run(run(args.confirm))


if __name__ == "__main__":
    main()
