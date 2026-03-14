"""
Migration: Add extended registration fields to the tenants table.

New columns (all nullable — existing rows unaffected):
  father_name, father_phone, date_of_birth, permanent_address,
  email, occupation, emergency_contact_relationship

Run once:
    python -m src.database.migrate_tenant_fields
"""
import asyncio
import os
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

load_dotenv()

DB_URL = os.getenv("DATABASE_URL", "").replace("postgresql://", "postgresql+asyncpg://")

NEW_COLUMNS = [
    ("father_name",                     "VARCHAR(120)"),
    ("father_phone",                    "VARCHAR(20)"),
    ("date_of_birth",                   "DATE"),
    ("permanent_address",               "TEXT"),
    ("email",                           "VARCHAR(120)"),
    ("occupation",                      "VARCHAR(120)"),
    ("emergency_contact_relationship",  "VARCHAR(60)"),
]


async def migrate():
    engine = create_async_engine(DB_URL, echo=False)
    async with engine.begin() as conn:
        for col, col_type in NEW_COLUMNS:
            # Check if column already exists
            result = await conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='tenants' AND column_name=:col"
            ), {"col": col})
            if result.fetchone():
                print(f"  already exists: {col}")
                continue
            await conn.execute(text(
                f"ALTER TABLE tenants ADD COLUMN {col} {col_type}"
            ))
            print(f"  added: {col} {col_type}")
    await engine.dispose()
    print("Done: tenants table extended with registration form fields.")


if __name__ == "__main__":
    asyncio.run(migrate())
