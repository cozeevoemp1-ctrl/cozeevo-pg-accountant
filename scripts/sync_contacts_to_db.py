"""
Sync WhatsApp chat contacts into pg_contacts table in Supabase.
- Updates existing contacts with enriched info (amount_paid, remaining, comments)
- Inserts new contacts not yet in DB
- Matches by phone number (normalized to digits only)
"""
import asyncio
import hashlib
import re
from decimal import Decimal
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

DB_URL = "postgresql+asyncpg://postgres:Anchorstrong123!@db.oxiqomoilqwfxjauxhzp.supabase.co:5432/postgres"

def normalize_phone(phone: str) -> str:
    """Strip to digits only, remove leading 91 if 12 digits."""
    if not phone:
        return ""
    # Remove .0 suffix from float-stored phones
    phone = re.sub(r"\.0$", "", phone.strip())
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    return digits


def make_hash(name: str, phone: str, category: str) -> str:
    """Generate unique_hash for pg_contacts row."""
    raw = f"{name or ''}|{phone or ''}|{category or ''}"
    return hashlib.sha256(raw.encode()).hexdigest()


# New contacts to INSERT (not in DB yet) — from WhatsApp chat extraction
# Format: (name, phone, category, contact_for, amount_paid, remaining, comments, referred_by)
NEW_CONTACTS = [
    # Partners (for reference — not vendors but useful in pg_contacts)
    ("Jitendra (Paisanurture.in, CFP)", "8978888551", "partner", "Partner / Senior Advisor, BNI Arka", None, None, "Financial planning, vendor sourcing", None),
    ("Chandrasekhar (Chandu)", "8548884455", "partner", "Partner / Ops Manager, on-site", None, None, "Staff, kitchen, procurement management", None),

    # Staff
    ("Anurudh V", "9092780783", "staff", "Gym manager / Site staff", None, None, "Gym equipment, CCTV, water leakage reports", None),
    ("Chef Vijaykumar Kumar", "9972334783", "staff", "Head Cook (2nd chef)", None, None, "Salary 25k->26k", None),

    # Furniture & Fittings — NEW
    ("Royal Furniture", "9900322679", "furniture", "Iron wardrobes 2,700-3,000/unit", None, None, "", None),
    ("Somnath", "9632784999", "carpenter", "Foldable study tables @1,650, plumbing work", None, None, "Also does plumbing. 1,500/day rate", None),
    ("Wakefit", "", "furniture", "Mattresses & Pillows", Decimal("339693"), None, "100 mattresses + pillows. Via Martin contact", None),
    ("Jubair (Grace Traders)", "", "furniture", "Bed frames / Cots. Bank: Union Bank 395301010031026", Decimal("774000"), None, "170 cots (3x6@4600 + 2.5x6@4200). Settled.", None),

    # Construction & Fabrication
    ("Shyam Reddy", "9731260340", "construction", "Fabricator — gas shelter, study tables, blue drums", None, None, "Gas cylinder shelter 20k", None),
    ("Govinda Nayaku", "9342205440", "construction", "Gas piping contractor — copper piping", Decimal("45000"), None, "45k advance paid", None),
    ("Imran Saki", "9901650624", "construction", "Gas cage fabricator", None, None, "Contact from Govinda Nayaku", "Govinda Nayaku"),
    ("PRITHVI Steel Kraft (RAJ)", "7259752457", "vendor", "Kitchen steel items / utensils", Decimal("100000"), None, "1L paid", None),
    ("Manju (Cozeevo Engineer)", "9738361211", "construction", "Builder engineer — plumbing, painting coord", None, None, "Building construction issues", None),

    # Interior
    ("Prakash Reddy", "8904402406", "design", "Custom photo frames (20x30 inch)", None, None, "Not readymade", None),
    ("Dinesh (Scaffoldings)", "9900232936", "construction", "Scaffolding rental", Decimal("8000"), None, "Profile light install", None),

    # Electricians — NEW
    ("Pavan (Electrician)", "8310318123", "electrician", "Room light install/repairs", None, None, "", None),
    ("Md Akbar", "7644867491", "electrician", "Local electrician", None, None, "", None),
    ("Mahesh (Electrician)", "7624807174", "electrician", "Tamil electrician, apartment background", None, None, "", None),
    ("Gopal Ele", "9901950658", "electrician", "Electrician", None, None, "From VCF", None),

    # Plumbers — NEW
    ("Jaffar Mithri", "8310106797", "plumber", "Plumber", None, None, "From VCF", None),
    ("Shriniwash", "9740213289", "plumber", "Plumber — blockage specialist", None, None, "400-500 per job", None),
    ("Rambabu (Lift Mechanic)", "9003157415", "facility", "Lift mechanic — frequent breakdowns", None, None, "", None),

    # Internet
    ("Sreeram (Airwire owner)", "9945344115", "internet", "Airwire owner — escalation contact for WiFi", None, None, "Use when Thiyagu unreachable", None),

    # Power / Diesel
    ("Suhail", "9886148862", "facility", "Diesel supplier — multiple vehicles", None, None, "Used during Mar 2026 diesel crisis. Jitendra ref.", "Jitendra"),
    ("Jayalakshmi", "9845066039", "facility", "DG / Power solutions — commercial generator rental", None, None, "", None),
    ("Sudheesh (OJUS DJI)", "9686699609", "facility", "DG service — main service for OJUS generator", None, None, "", None),
    ("Jai Bescom", "9449874375", "government", "BESCOM electricity contact", None, None, "", None),

    # Food & Kitchen
    ("Ram Kumar (HP Gas)", "8619377620", "food_supply", "Gas delivery — Sakthi Gas HP distributor", None, None, "", None),
    ("HP Gas booking", "8310745974", "food_supply", "Commercial gas cylinder booking office", None, None, "", None),

    # Manpower
    ("Sakthi Vel", "9740074470", "facility", "Cleaner supplier — 15k salary + food/accom, 10% commission", None, None, "", None),
    ("Vergiese", "9900631199", "facility", "Manpower agency — staff recruitment", None, None, "", None),
    ("Lokesh (Blue Collar)", "9901007990", "facility", "Manpower agency — cleaning staff", None, None, "", None),
    ("Nirdesh", "6363293493", "facility", "Housekeeping", None, None, "Via Kiran Prabhu (Bellandur)", "Kiran Prabhu"),
    ("Ganesh (cleaner family)", "6364544461", "facility", "Cleaner couple — 12k/person", None, None, "Needed separate room", None),
    ("Abhishek Kumar (cleaner)", "6362712216", "facility", "Cleaner couple — joined Mar 2026", None, None, "", None),

    # Marketing
    ("Viplab", "8918431221", "marketing", "Marketing / Video — Find my PG collab", None, None, "25k initial + 10k asked. GPay number.", None),
    ("Pg Marketing", "9019653917", "marketing", "Marketing", None, None, "From VCF", None),
    ("Sandeep Gowda", "9632139796", "vendor", "Projector / Sound system rental", None, None, "T20 World Cup event", None),

    # Water tankers — NEW
    ("Vinay Kumar (Tanker)", "9739647672", "facility", "Water tanker — BM Shoma area", None, None, "", None),
    ("Muneshwara (Tanker)", "8553167678", "facility", "Water tanker supply", None, None, "", None),

    # Key & Locks
    ("Key Shop BMR", "9148809732", "vendor", "Key cutting, locks. Alt: 9015404182", None, None, "", None),

    # Professional
    ("Ashok (Auditor)", "9844036556", "professional", "Auditor — for Dhana/Narendra", None, None, "", None),

    # Corporate
    ("Satish Kumar J (Celestial Systems)", "", "corporate", "Corporate booking — Celestial Systems / Hitachi. Signed.", None, None, "Email: skjayakumar@celestialsys.com", None),
    ("Venkata Rao", "9502506702", "vendor", "Other PG operator — industry contact", None, None, "", None),
    ("Anitha (BNI Arka)", "9483859240", "vendor", "BNI reference contact", None, None, "Shared 15 Feb 2026", "Jitendra"),

    # Sports
    ("9Balls India (Sports)", "7349705199", "gym_sports", "Pool 72K, Foosball 33K, TT 24K, Subsoccer 42K, Carrom 7.5K, Chess 6K + GST", Decimal("198075"), None, "Returned chess + carrom (11K refund)", None),

    # Fire Safety
    ("Pramod (Pragathi Fire)", "", "vendor", "Fire extinguishers — 14 ABC 6kg + 1 CO2 + 1 K-type", Decimal("32700"), None, "Paid", None),
]


# Updates for EXISTING contacts — matched by phone
# Format: (phone_digits, updates_dict)
UPDATES = [
    ("7406036220", {"contact_for": "Wallpaper / Stickers — installation + printing", "amount_paid": Decimal("52540"), "comments": "From WhatsApp chat"}),
    ("9986593093", {"contact_for": "RO water system, water tank sensors (6,900 each)", "comments": "Also does automation / sensors"}),
    ("9845934818", {"contact_for": "Painter — reception, gym, building. BNI Pragathi", "comments": "Charged extra 5000 for redo work"}),
    ("7022970608", {"contact_for": "Interior: Cushion, vertical garden, bar stools, curtains, pillows. BNI Pragati AECS Decor", "comments": "Multiple installment payments"}),
    ("984453290", {"contact_for": "Electronics — TVs (BPL 9800/unit), washing machines, microwaves, fridges, dispensers. Usha Trading Co", "comments": "Credit note 45,891 pending"}),
    ("973900167", {"contact_for": "Natural plants for reception"}),
    ("9663753024", {"contact_for": "Plants — Vcare Plants, alternative supplier"}),
    ("990023293", {"contact_for": "Scaffolding rental — profile light install", "amount_paid": Decimal("8000")}),
    ("9976535858", {"contact_for": "WiFi Setup — 1,000/floor/month. Slow. Replaced by Airwire for Hulk", "comments": "Old WiFi provider"}),
    ("9845419873", {"contact_for": "CC Cameras — Unisol Communications. Project Manager", "amount_paid": Decimal("100000"), "remaining": "1.02L pending (cash + online)"}),
    ("9845227633", {"contact_for": "Chairs — 150 THOR + 83 HULK ordered. Also does mattress, cushions, curtains, bedsheets", "amount_paid": None, "remaining": "~23 chairs HULK pending delivery", "comments": "Wholesale: +91 99011 60099"}),
    ("9113858973", {"contact_for": "Shoe racks — 1,675/rack, 88 total (~1.47L)", "comments": "Fully paid"}),
    ("9632694840", {"contact_for": "Carpenter — wardrobe repairs, headboards and cupboards"}),
    ("9924540656", {"contact_for": "Second-hand furniture — side tables, key locks (Chikpet)"}),
    ("9379687293", {"contact_for": "Gym flooring — 648 sft rubber @135/sft = 87,480. Also cloth drying hangers", "amount_paid": Decimal("60000"), "remaining": "Balance on gym flooring"}),
    ("9035338896", {"contact_for": "Electrician — light installation. 20K agreed, 10K paid, 15K pending (incl 5K rope lights)", "amount_paid": Decimal("10000"), "remaining": "10K + 5K rope lights"}),
    ("9743317333", {"contact_for": "Study tables / Chairs — imported tables @1,650 each. Also bar stools", "comments": "Sample paid"}),
    ("7760960636", {"contact_for": "Signages — sign boards, room/floor numbers", "amount_paid": Decimal("52426"), "comments": "43,426 + 9,000 GST"}),
    ("6366411789", {"contact_for": "Garbage collector — waste collection"}),
    ("9036409106", {"contact_for": "T-shirts / Uniforms / Corporate gifting — staff uniforms"}),
    ("7795076250", {"contact_for": "Airwire Internet — Hulk block WiFi. Frequently unreliable", "comments": "Thiyagu. Often doesn't show up. Escalation: Sreeram 9945344115"}),
    ("9663049651", {"category": "food_supply", "contact_for": "Vegetables — KR Market delivery to PGs"}),
    ("8795514149", {"category": "electrician", "contact_for": "Electrician — local/emergency", "name": "Alam"}),
    ("8747884323", {"category": "government", "contact_for": "BBMP contact — trade license", "name": "BBMP Manju"}),
    ("7348877664", {"contact_for": "Plumber — Whitefield area"}),
    ("7349663198", {"contact_for": "Water tanker — HWS supply"}),
    ("9902618311", {"contact_for": "Hot water tank / heat pump technician. Often unreachable", "comments": "Recommended automatic machine for power fluctuation"}),
    ("7411535239", {"contact_for": "Diesel supplier — generator diesel pump"}),
    ("9060477309", {"contact_for": "Police — Whitefield. Emergency contact", "name": "Subhan Police WF"}),
    ("7899601416", {"contact_for": "Plumber — emergency plumbing, hot water. Brother: Jayanth"}),
    ("9916515779", {"contact_for": "Plumber WF — Dilip's brother"}),
    ("9880401360", {"contact_for": "Electrician WF — room repairs, wiring fixes"}),
    ("9337929447", {"contact_for": "Plumber — AECS Layout"}),
    ("7899421056", {"contact_for": "Plumber BMR"}),
    ("9740793471", {"contact_for": "Manpower agency (Rock Power) — Security 21k, housekeeping 20k/person. BNI ARKA", "name": "Rohit / Poojayya (Rock Power)"}),
]


async def main():
    engine = create_async_engine(DB_URL)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # 1. Get existing contacts
        res = await session.execute(text("SELECT id, name, phone FROM pg_contacts"))
        existing = res.fetchall()
        existing_phones = {}
        for row in existing:
            phone_norm = normalize_phone(row[2] or "")
            if phone_norm:
                existing_phones[phone_norm] = row[0]  # phone -> id

        print(f"Existing contacts: {len(existing)}")
        print(f"Existing phones indexed: {len(existing_phones)}")

        # 2. Update existing contacts
        updated = 0
        for phone_digits, updates in UPDATES:
            norm = normalize_phone(phone_digits)
            if norm in existing_phones:
                contact_id = existing_phones[norm]
                set_parts = []
                params = {"cid": contact_id}
                for k, v in updates.items():
                    set_parts.append(f"{k} = :{k}")
                    params[k] = v
                sql = f"UPDATE pg_contacts SET {', '.join(set_parts)} WHERE id = :cid"
                await session.execute(text(sql), params)
                updated += 1
            else:
                print(f"  SKIP update (phone not found): {phone_digits}")

        print(f"Updated: {updated}")

        # 3. Insert new contacts
        inserted = 0
        skipped = 0
        for name, phone, category, contact_for, amount_paid, remaining, comments, referred_by in NEW_CONTACTS:
            phone_norm = normalize_phone(phone)
            if phone_norm and phone_norm in existing_phones:
                skipped += 1
                continue

            uhash = make_hash(name, phone_norm, category)
            await session.execute(
                text("""
                    INSERT INTO pg_contacts (name, phone, category, contact_for, amount_paid, remaining, comments, referred_by, property, visible_to, unique_hash)
                    VALUES (:name, :phone, :category, :contact_for, :amount_paid, :remaining, :comments, :referred_by, 'Whitefield', 'owner,staff', :uhash)
                """),
                {
                    "name": name,
                    "phone": phone_norm or None,
                    "category": category,
                    "contact_for": contact_for,
                    "amount_paid": amount_paid,
                    "remaining": remaining,
                    "comments": comments,
                    "referred_by": referred_by,
                    "uhash": uhash,
                },
            )
            inserted += 1

        await session.commit()
        print(f"Inserted: {inserted}")
        print(f"Skipped (already exists): {skipped}")

        # 4. Final count
        res = await session.execute(text("SELECT count(*) FROM pg_contacts"))
        print(f"Total contacts now: {res.scalar()}")

    await engine.dispose()


asyncio.run(main())
