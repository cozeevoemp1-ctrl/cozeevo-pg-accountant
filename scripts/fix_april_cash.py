"""
scripts/fix_april_cash.py
Replace ALL April cash payments with Kiran's confirmed list.
"""
import asyncio
import os
import sys
from datetime import date
from decimal import Decimal

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import select, update
from src.database.db_manager import init_engine, get_session
from src.database.models import (
    Tenancy, Tenant, Payment, PaymentMode, PaymentFor
)

# Kiran's authoritative cash list for April
USER_CASH = [
    ("Bala Subramanyam", 15500), ("Kiran", 13500), ("Kishan", 13500),
    ("Lakshmiprasanna", 12500), ("Ashish Das", 18500), ("Mayur", 14000),
    ("Sipan Pal", 13000), ("Sujal Jaiswal", 13000), ("Jeewan kant Oberoi", 14000),
    ("Dinesh", 14000), ("T.M.V S G  Pavan", 14000), ("Ashok Reddy", 14000),
    ("Venkatha Supramanian", 27000), ("Shreyakarpe", 1600), ("V.Sathya Priya", 7750),
    ("Harsh", 27700), ("Neha Pramod", 13000), ("V Leela Yugandhar", 4000),
    ("Nagarajan", 12000), ("Sneha AK", 28000), ("Tejas HR", 15000),
    ("Vedant", 14000), ("Pratik", 14000), ("Adnan Doshi", 14500),
    ("V. Bhanu Prakash", 7750), ("Jaya Prakash", 14500), ("Kamesh", 13000),
    ("Prithviraj", 12000), ("Sai Shankar", 20000), ("Lakshmi Priya", 13000),
    ("Yelagani Anuhya", 13000), ("Namit Mehta", 13000), ("Saksham", 13000),
    ("Srikar", 13000), ("Muhesh.M", 13000), ("Balaji", 12000),
    ("Chaitanya Phad", 8000), ("sampriti Chowdary", 15000), ("Aparna Shahare", 15500),
    ("Thirumurugan", 10000), ("Rajdeep B", 21000),
    ("Arjun Sumanth", 13000), ("Akshayarathna A", 12250), ("Chinmay pagey", 41000),
    ("Anshika Gahlot", 1500), ("Abhishek sharma", 12500), ("Sachin", 16250),
    ("Surya shivani", 49000), ("Veena.T", 16250), ("Ritik", 22000),
    ("Lokesh Sanaka", 13500), ("Rakesh Sanaka", 13500), ("Adithya Reddy", 10000),
    ("Manya", 16000), ("Roshni", 13000), ("Tejas", 12000),
    ("Anugun", 20000), ("Sparsh Gupta", 10000), ("Preesha", 13000),
    ("Amisha Mohta", 13000), ("Arpit Mathur", 18000), ("Vadi Raj Nandlal", 23600),
]

APRIL = date(2026, 4, 1)


async def main():
    init_engine(os.getenv("DATABASE_URL"))
    total_target = sum(amt for _, amt in USER_CASH)
    print(f"Target cash total: Rs.{total_target:,} ({len(USER_CASH)} entries)")

    async with get_session() as s:
        # 1. Void ALL existing April cash rent payments
        existing = (await s.execute(
            select(Payment).where(
                Payment.period_month == APRIL,
                Payment.payment_mode == PaymentMode.cash,
                Payment.for_type == PaymentFor.rent,
                Payment.is_void == False,
            )
        )).scalars().all()
        for p in existing:
            p.is_void = True
        print(f"Voided {len(existing)} existing April cash payments")

        # 2. Build name lookup
        rows = await s.execute(
            select(Tenant, Tenancy).join(Tenancy, Tenancy.tenant_id == Tenant.id)
        )
        by_name = {}
        for t, tenancy in rows.all():
            k = t.name.lower().strip()
            by_name.setdefault(k, []).append((t, tenancy))

        missing = []
        added = 0
        added_total = 0
        for name, amt in USER_CASH:
            matches = by_name.get(name.lower().strip(), [])
            if not matches:
                for k, v in by_name.items():
                    if name.lower().strip() in k or k in name.lower().strip():
                        matches = v
                        break
            if not matches:
                first = name.lower().split()[0]
                for k, v in by_name.items():
                    if first in k.split():
                        matches = v
                        break
            if not matches:
                missing.append(name)
                continue
            tenant, tenancy = matches[0]
            s.add(Payment(
                tenancy_id=tenancy.id,
                amount=Decimal(str(amt)),
                payment_date=APRIL,
                payment_mode=PaymentMode.cash,
                for_type=PaymentFor.rent,
                period_month=APRIL,
                notes="April cash — reconciled to Kiran's authoritative list",
            ))
            added += 1
            added_total += amt

        # 3. Add notes to R67 + R87 tenancies about Chandra
        for chandra_name in ["Shubhi Vishnoi", "Saurabh Kumar", "Saurabh kumar"]:
            matches = by_name.get(chandra_name.lower().strip(), [])
            if matches:
                t, tenancy = matches[0]
                note = tenancy.notes or ""
                if "chandra" not in note.lower():
                    tenancy.notes = (note + " | Need to collect Rs.15,500 from Chandra (April)").strip(" |")
                    print(f"Added Chandra note to {t.name}")

        await s.commit()

        print(f"\nAdded {added} payments, Rs.{added_total:,}")
        if missing:
            print(f"\nMissing in DB ({len(missing)}):")
            for n in missing:
                print(f"  - {n}")


asyncio.run(main())
