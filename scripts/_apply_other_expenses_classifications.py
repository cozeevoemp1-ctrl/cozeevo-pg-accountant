"""
One-off: apply Kiran's classifications from 'others not classified.xlsx' to bank_transactions DB.
Run: venv/Scripts/python scripts/_apply_other_expenses_classifications.py
"""
from __future__ import annotations
import asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

DB = "postgresql+asyncpg://postgres:Anchorstrong123!@db.oxiqomoilqwfxjauxhzp.supabase.co:5432/postgres"

# (db_id, category, sub_category)
UPDATES = [
    # Operational Expenses - Chandrasekhar / Akhil PG expense advances
    (2617, "Operational Expenses", "Cash Advance - Akhil/Chandra"),
    (2630, "Operational Expenses", "Cash Advance - Akhil/Chandra"),

    # Fuel & Diesel
    (1174, "Fuel & Diesel", "Diesel"),
    (1683, "Fuel & Diesel", "Diesel Commission"),

    # Food & Groceries
    (2320, "Food & Groceries", "Dairy - Real Value Mart"),
    (2275, "Food & Groceries", "Provisions"),
    (1863, "Food & Groceries", "Provisions"),
    (2075, "Food & Groceries", "Vegetables"),
    (1619, "Food & Groceries", "Flipkart Groceries"),
    (2096, "Food & Groceries", "Flipkart Groceries"),
    (2154, "Food & Groceries", "Flipkart Groceries"),
    (1778, "Food & Groceries", "Flipkart Groceries"),
    (1610, "Food & Groceries", "Flipkart Groceries"),
    (2173, "Food & Groceries", "Flipkart Groceries"),
    (2164, "Food & Groceries", "Flipkart Groceries"),
    (1872, "Food & Groceries", "Flipkart Groceries"),
    (1881, "Food & Groceries", "Vegetables"),
    (2425, "Food & Groceries", "Vegetables"),
    (2418, "Food & Groceries", "Vegetables"),
    (2417, "Food & Groceries", "Vegetables"),
    (1679, "Food & Groceries", "Vegetables"),
    (1110, "Food & Groceries", "Water for Guests"),
    (1586, "Food & Groceries", "Staff Food"),

    # Staff & Labour
    (1935, "Staff & Labour", "Vivek Salary"),
    (2481, "Staff & Labour", "Bhukesh Salary"),
    (1934, "Staff & Labour", "Vivek Salary"),

    # Tenant Deposit Refund
    (2412, "Tenant Deposit Refund", "Booking Cancellation - Arun Philip"),
    (1539, "Tenant Deposit Refund", "Adithya Saraf"),
    (2557, "Tenant Deposit Refund", "Radhika"),
    (2321, "Tenant Deposit Refund", "Majji Divya - Day Wise"),
    (2315, "Tenant Deposit Refund", "Prem - Day Wise"),
    (1765, "Tenant Deposit Refund", "Prem - Day Wise"),
    (1217, "Tenant Deposit Refund", "Room 610 Akshayaratna"),
    (1042, "Tenant Deposit Refund", "Bhanu Prakash"),
    (1708, "Tenant Deposit Refund", "Anudeep"),
    (1216, "Tenant Deposit Refund", "Ankit Kumar"),
    (1601, "Tenant Deposit Refund", "Dhruv"),

    # Shopping & Supplies
    (2461, "Shopping & Supplies", "D-Mart"),
    (2470, "Shopping & Supplies", "D-Mart"),

    # Furniture & Fittings
    (2366, "Furniture & Fittings", "Porter - Bed Frames"),
    (2374, "Furniture & Fittings", "Porter - Bed Frames"),
    (1565, "Furniture & Fittings", "Photo Frame / Decor"),
    (1654, "Furniture & Fittings", "Porter - Shoe Racks"),
    (1639, "Furniture & Fittings", "Porter - Study Tables"),
    (1852, "Furniture & Fittings", "Porter - Shoe Racks"),

    # Maintenance & Repairs
    (1146, "Maintenance & Repairs", "Key Maker"),
    (2464, "Maintenance & Repairs", "Key Maker"),
    (1002, "Maintenance & Repairs", "Key Maker"),
    (1806, "Maintenance & Repairs", "Key Maker"),
    (1214, "Maintenance & Repairs", "Key Maker"),
    (1127, "Maintenance & Repairs", "Key Maker"),
    (1670, "Maintenance & Repairs", "Refrigerator Installation"),
    (1932, "Maintenance & Repairs", "Hardware"),
    (1722, "Maintenance & Repairs", "Hardware"),
    (1231, "Maintenance & Repairs", "Hardware"),
    (1689, "Maintenance & Repairs", "Carpenter"),

    # Cleaning Supplies
    (1558, "Cleaning Supplies", "Triveni Soap & Oil"),
    (1732, "Cleaning Supplies", "Triveni Soap & Oil"),
    (1031, "Cleaning Supplies", "Triveni Soap & Oil"),
    (1037, "Cleaning Supplies", "Triveni Soap & Oil"),
    (1710, "Cleaning Supplies", "Triveni Soap & Oil"),
    (1036, "Cleaning Supplies", "Triveni Soap & Oil"),
    (1566, "Cleaning Supplies", "Wellcare - Office Supplies"),
    (2297, "Cleaning Supplies", "Housekeeping Supplier"),
    (1818, "Cleaning Supplies", "Kundan - Housekeeping"),

    # Operational Expenses
    (1671, "Operational Expenses", "Water Barrel Porter"),
    (1259, "Operational Expenses", "Mobile Recharge"),
    (1705, "Operational Expenses", "Mobile Recharge"),
    (1119, "Operational Expenses", "Mobile Recharge"),
    (1996, "Operational Expenses", "Mobile Recharge"),
    (1527, "Operational Expenses", "Mobile Recharge"),
    (1164, "Operational Expenses", "Mobile Recharge"),
    (2194, "Operational Expenses", "Prime Realtors"),
    (1918, "Operational Expenses", "Staff Medical - Loki"),
    (2312, "Operational Expenses", "Plants Porter"),

    # Marketing
    (1943, "Marketing", "Print Flyers - Saurav Kumar"),

    # DB ID 1984 stays as Other Expenses (Kiran: "record nowhere found")
]


async def main():
    engine = create_async_engine(DB)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as session:
        print(f"Applying {len(UPDATES)} classification updates...\n")
        ok = 0
        by_cat: dict[str, int] = {}

        for db_id, cat, sub in UPDATES:
            await session.execute(
                sa.text("UPDATE bank_transactions SET category=:cat, sub_category=:sub WHERE id=:id"),
                {"cat": cat, "sub": sub, "id": db_id}
            )
            by_cat[cat] = by_cat.get(cat, 0) + 1
            ok += 1

        await session.commit()
        print(f"Done: {ok} rows updated\n")
        print("Breakdown by category:")
        for cat, count in sorted(by_cat.items()):
            print(f"  {cat}: {count} rows")

        # Verify remaining Other Expenses
        res = await session.execute(
            sa.text("SELECT id, amount, description FROM bank_transactions WHERE category='Other Expenses' AND txn_type='expense' ORDER BY amount DESC")
        )
        rows = res.fetchall()
        total = sum(r.amount for r in rows)
        print(f"\nRemaining Other Expenses: {len(rows)} rows, Rs. {total:,.2f}")
        for r in rows:
            print(f"  id={r.id}  Rs.{r.amount:,.0f}  {r.description[:70]}")

    await engine.dispose()


asyncio.run(main())
