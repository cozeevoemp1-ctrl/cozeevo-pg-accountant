"""
Migration: Add complaints table.

Run once:
    python -m src.database.migrate_complaints

Creates:
  - complaintcategory enum (plumbing, electricity, wifi, food, furniture, other)
  - complaintstatus enum  (open, in_progress, resolved, closed)
  - complaints table
  - 3 indexes
"""
from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]


async def run():
    if DATABASE_URL.startswith("postgresql://"):
        url = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
    else:
        url = DATABASE_URL

    engine = create_async_engine(url, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as session:
        print("Creating enum types (if not exist)...")
        await session.execute(text(
            "DO $$ BEGIN "
            "  CREATE TYPE complaintcategory AS ENUM "
            "    ('plumbing','electricity','wifi','food','furniture','other'); "
            "EXCEPTION WHEN duplicate_object THEN NULL; "
            "END $$;"
        ))
        await session.execute(text(
            "DO $$ BEGIN "
            "  CREATE TYPE complaintstatus AS ENUM "
            "    ('open','in_progress','resolved','closed'); "
            "EXCEPTION WHEN duplicate_object THEN NULL; "
            "END $$;"
        ))

        print("Creating complaints table...")
        await session.execute(text("""
            CREATE TABLE IF NOT EXISTS complaints (
                id          SERIAL PRIMARY KEY,
                tenancy_id  INTEGER NOT NULL REFERENCES tenancies(id),
                category    complaintcategory NOT NULL,
                sub_item    VARCHAR(100),
                description TEXT NOT NULL,
                status      complaintstatus DEFAULT 'open',
                created_at  TIMESTAMP DEFAULT NOW(),
                resolved_at TIMESTAMP,
                resolved_by VARCHAR(20),
                notes       TEXT
            )
        """))

        print("Creating indexes...")
        await session.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_complaints_tenancy "
            "ON complaints(tenancy_id)"
        ))
        await session.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_complaints_status "
            "ON complaints(status)"
        ))
        await session.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_complaints_created "
            "ON complaints(created_at)"
        ))

        await session.commit()

    await engine.dispose()
    print("\nDone: complaints table ready.")


if __name__ == "__main__":
    asyncio.run(run())
