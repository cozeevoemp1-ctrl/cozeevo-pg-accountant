"""One-off: apply Kiran's rulings from data/reports/classified 08_08.xlsx (July 2026).

Sheet 1 answers came back in the COMMENT column — applied here row by row.
Sheet 2: Jalluram x2 + Ninjacart x2 confirmed legit (no change); Chandra +
G Ravikumar confirmed non-P&L (already Non-Operating); TVS bike -> back to
Other Expenses/misc per Kiran. Inar Devi CONFLICTS (sheet1 says refund,
sheet2 says staff) -> left unchanged, re-asked.

Run:  venv/Scripts/python scripts/_apply_classified_2026_08_08.py
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

# (desc LIKE, amount, category, sub_category)
CHANGES = [
    ("%abhinav.rastogi4567%",        3750, "Tenant Deposit Refund", "Other Refund / Exit"),
    ("%panner and cleaning%",        4028, "Food & Groceries",      "Vegetables & Greens"),
    ("%lalbabukumar7292%",           3500, "Staff & Labour",        "Staff Advance"),
    ("%Heat pump tank pipe%",        2450, "Maintenance & Repairs", "General Maintenance"),
    ("%EB Line man tips%",            750, "Maintenance & Repairs", "Electrician / Electrical"),
    ("%Garbage removal supervisor%",  500, "Waste Disposal",        "Garbage / Supervisor"),
    ("%Corrindar%",                   465, "Food & Groceries",      "Vegetables & Greens"),
    ("%2 Hand Shower%",               400, "Maintenance & Repairs", "Plumbing"),
    ("%Sweeing mesh for atta%",       350, "Food & Groceries",      "Cooking Oil / Masala"),
    ("%Washing Machine service%",     350, "Maintenance & Repairs", "General Maintenance"),
    ("%For Mutter%",                  298, "Food & Groceries",      "Vegetables & Greens"),
    ("%Water tank top lid%",          260, "Maintenance & Repairs", "Plumbing"),
    ("%T joint 2 fevicol%",           220, "Shopping & Supplies",   "Hardware / Fittings"),
    ("%HG gas delivery man%",         200, "Maintenance & Repairs", "General Maintenance"),
    ("%Gas delivery man tips%",       200, "Maintenance & Repairs", "General Maintenance"),
    ("%Pumpkin coconut%",             170, "Food & Groceries",      "Vegetables & Greens"),
    ("%Note book for Register%",      160, "Shopping & Supplies",   "Stationery"),
    ("%prasantamajumdar878%",         139, "Food & Groceries",      "Vegetables & Greens"),
    ("%Alen ky tool%",                110, "Maintenance & Repairs", "General Maintenance"),
    ("%q283663049@ybl/Tomoto%",        90, "Food & Groceries",      "Vegetables & Greens"),
    # Kiran: bike is NOT furniture — plain misc other expense
    ("%TVS 110 CC Jupiter Bike%",   50000, "Other Expenses",        "Misc UPI Payments"),
    ("%Paid for me TVS Jupiter%",     872, "Other Expenses",        "Misc UPI Payments"),
]


async def main() -> None:
    async with get_session() as s:
        total = 0
        for like, amt, cat, sub in CHANGES:
            res = await s.execute(text(
                "UPDATE bank_transactions SET category=:cat, sub_category=:sub "
                "WHERE txn_date BETWEEN '2026-07-01' AND '2026-07-31' AND txn_type='expense' "
                "AND amount=:amt AND description LIKE :like RETURNING id"
            ), {"cat": cat, "sub": sub, "amt": amt, "like": like})
            n = len(res.all())
            total += n
            if n != 1:
                print(f"  !! {like} -> matched {n} rows (expected 1)")
        await s.commit()
        print(f"applied {total} reclassifications")
        print("\n== July Other Expenses after rulings ==")
        for r in (await s.execute(text(
            "SELECT sub_category, COUNT(*), SUM(amount) FROM bank_transactions "
            "WHERE txn_type='expense' AND category='Other Expenses' "
            "AND txn_date BETWEEN '2026-07-01' AND '2026-07-31' GROUP BY 1 ORDER BY 3 DESC"))):
            print(f"  {str(r[0])[:30]:30} n={r[1]:3} {float(r[2]):>10,.0f}")


if __name__ == "__main__":
    asyncio.run(main())
