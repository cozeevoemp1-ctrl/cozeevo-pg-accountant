"""One-off: July 2026 narration-based reclassifications after CSV import.

- G Ravikumar NEFT 2,00,000 (narration: "hand Loan") -> Non-Operating /
  Hand Loan - G Ravikumar (bank). Loans are never opex (Kiran 2026-07-11).
- Jalluram NEFT 20,000 (THOR) -> Staff & Labour / Housekeeping — same person
  paid 20,000 from HULK the same day with "Housekeeping Person" narration.
- Raghu Nandha Mandadi NEFT 94,938 "cozeevo kaveri water bill pay" -> Water
  (it's the Kaveri water bill routed via the landlord, not rent).
- TVS Jupiter bike 50,000 -> Furniture & Supplies (CAPEX abolished 2026-05-13,
  assets bought from PG account are opex line) — flagged for Kiran.
- Sump cleaning 9,500 -> Maintenance & Repairs.

Run:  venv/Scripts/python scripts/_reclass_july_2026.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import text

from src.database.db_manager import get_session, init_engine
init_engine(os.environ["DATABASE_URL"])

# (match description LIKE, expected amount, new category, new sub_category)
CHANGES = [
    ("%G Ravikumar%hand Loan%",            200000, "Non-Operating",         "Hand Loan - G Ravikumar (bank)"),
    ("%Jalluram-SBIN0040784-IFB%",          20000, "Staff & Labour",        "Housekeeping / Cleaning Staff"),
    ("%kaveri water bill pay%",             94938, "Water",                 "Kaveri Water (via landlord)"),
    ("%TVS 110 CC Jupiter Bike%",           50000, "Furniture & Supplies",  "TVS Jupiter Bike (staff vehicle)"),
    ("%Sump cleaning changes%",              9500, "Maintenance & Repairs", "Sump / Tank Cleaning"),
]


async def main() -> None:
    async with get_session() as s:
        for like, amt, cat, sub in CHANGES:
            res = await s.execute(text(
                "UPDATE bank_transactions SET category=:cat, sub_category=:sub "
                "WHERE txn_date >= '2026-07-01' AND txn_date <= '2026-07-31' "
                "AND txn_type='expense' AND amount=:amt AND description LIKE :like "
                "RETURNING id, amount"
            ), {"cat": cat, "sub": sub, "amt": amt, "like": like})
            rows = res.all()
            print(f"{cat}/{sub}: {len(rows)} row(s) -> {[r[0] for r in rows]}")
        await s.commit()


if __name__ == "__main__":
    asyncio.run(main())
