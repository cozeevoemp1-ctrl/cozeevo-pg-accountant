"""
Seed script — run once to populate master data into Supabase.
  python -m src.database.seed

Seeds:
  1. authorized_users  — Kiran (admin) + partner (power_user)
  2. properties        — Cozeevo THOR + Cozeevo HULK
  3. food_plans        — veg / non-veg / egg / none
  4. expense_categories — all standard PG expense types
"""
import asyncio
import os
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select

load_dotenv()

from src.database.models import (
    Base, AuthorizedUser, UserRole,
    Property, FoodPlan, ExpenseCategory
)

DATABASE_URL = os.environ["DATABASE_URL"]


async def seed():
    engine = create_async_engine(DATABASE_URL, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as session:
        async with session.begin():

            # ── 1. Authorized Users ──────────────────────────────────────
            existing = await session.execute(select(AuthorizedUser))
            if not existing.scalars().first():
                session.add_all([
                    AuthorizedUser(
                        phone="+917845952289",
                        name="Kiran",
                        role=UserRole.admin,
                        added_by="system",
                    ),
                    AuthorizedUser(
                        phone="+917358341775",
                        name="Partner",
                        role=UserRole.power_user,
                        added_by="+917845952289",
                    ),
                    AuthorizedUser(
                        phone="+966534015243",
                        name="Prabhakaran Devarjulu",
                        role=UserRole.power_user,
                        added_by="+917845952289",
                    ),
                ])
                print("  [OK] authorized_users seeded")
            else:
                print("  [SKIP] authorized_users already exist")

            # ── 2. Properties ────────────────────────────────────────────
            existing = await session.execute(select(Property))
            if not existing.scalars().first():
                session.add_all([
                    Property(
                        name="Cozeevo THOR",
                        address="Chennai, Tamil Nadu",
                        owner_name="Kiran",
                        phone="+917845952289",
                        total_rooms=30,
                        active=True,
                    ),
                    Property(
                        name="Cozeevo HULK",
                        address="Chennai, Tamil Nadu",
                        owner_name="Kiran",
                        phone="+917845952289",
                        total_rooms=20,
                        active=True,
                    ),
                ])
                print("  [OK] properties seeded (THOR + HULK)")
            else:
                print("  [SKIP] properties already exist")

            # ── 3. Food Plans ────────────────────────────────────────────
            existing = await session.execute(select(FoodPlan))
            if not existing.scalars().first():
                session.add_all([
                    FoodPlan(name="none",    includes_lunch_box=False, monthly_cost=0,    active=True),
                    FoodPlan(name="veg",     includes_lunch_box=False, monthly_cost=0,    active=True),
                    FoodPlan(name="non-veg", includes_lunch_box=False, monthly_cost=0,    active=True),
                    FoodPlan(name="egg",     includes_lunch_box=False, monthly_cost=0,    active=True),
                    FoodPlan(name="veg + lunch box",     includes_lunch_box=True, monthly_cost=0, active=True),
                    FoodPlan(name="non-veg + lunch box", includes_lunch_box=True, monthly_cost=0, active=True),
                ])
                print("  [OK] food_plans seeded")
            else:
                print("  [SKIP] food_plans already exist")

            # ── 4. Expense Categories ────────────────────────────────────
            existing = await session.execute(select(ExpenseCategory))
            if not existing.scalars().first():
                categories = [
                    # Utilities
                    ("Electricity", None),
                    ("Water", None),
                    ("Internet / WiFi", None),
                    ("Gas", None),
                    # Staff
                    ("Staff Salary", None),
                    ("Staff Bonus", None),
                    # Maintenance
                    ("Maintenance & Repair", None),
                    ("Cleaning Supplies", None),
                    ("Pest Control", None),
                    # Food & Kitchen
                    ("Groceries", None),
                    ("Cooking Gas", None),
                    # Admin
                    ("Property Tax", None),
                    ("Insurance", None),
                    ("Legal & Professional", None),
                    # Miscellaneous
                    ("Transport", None),
                    ("Miscellaneous", None),
                ]
                session.add_all([
                    ExpenseCategory(name=name, active=True)
                    for name, _ in categories
                ])
                print(f"  [OK] expense_categories seeded ({len(categories)} categories)")
            else:
                print("  [SKIP] expense_categories already exist")

    await engine.dispose()
    print("\nSeed complete.")


if __name__ == "__main__":
    asyncio.run(seed())
