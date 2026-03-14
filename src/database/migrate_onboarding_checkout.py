"""
Migration: Add onboarding_sessions and checkout_records tables.

Run once:
    python -m src.database.migrate_onboarding_checkout

Creates:
  - onboarding_sessions  (tracks multi-step KYC form per new tenant)
  - checkout_records     (offboarding checklist: keys, damages, dues, deposit)
  - 4 indexes
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
        print("Creating onboarding_sessions table...")
        await session.execute(text("""
            CREATE TABLE IF NOT EXISTS onboarding_sessions (
                id              SERIAL PRIMARY KEY,
                tenant_id       INTEGER NOT NULL REFERENCES tenants(id),
                tenancy_id      INTEGER REFERENCES tenancies(id),
                step            VARCHAR(40) DEFAULT 'ask_gender',
                collected_data  TEXT,
                expires_at      TIMESTAMP NOT NULL,
                completed       BOOLEAN DEFAULT FALSE,
                created_at      TIMESTAMP DEFAULT NOW()
            )
        """))
        await session.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_onboarding_tenant "
            "ON onboarding_sessions(tenant_id)"
        ))
        await session.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_onboarding_expires "
            "ON onboarding_sessions(expires_at)"
        ))

        print("Creating checkout_records table...")
        await session.execute(text("""
            CREATE TABLE IF NOT EXISTS checkout_records (
                id                      SERIAL PRIMARY KEY,
                tenancy_id              INTEGER NOT NULL UNIQUE REFERENCES tenancies(id),
                cupboard_key_returned   BOOLEAN DEFAULT FALSE,
                main_key_returned       BOOLEAN DEFAULT FALSE,
                damage_notes            TEXT,
                other_comments          TEXT,
                pending_dues_amount     NUMERIC(12,2) DEFAULT 0,
                deposit_refunded_amount NUMERIC(12,2) DEFAULT 0,
                deposit_refund_date     DATE,
                actual_exit_date        DATE,
                recorded_by             VARCHAR(20),
                created_at              TIMESTAMP DEFAULT NOW(),
                updated_at              TIMESTAMP DEFAULT NOW()
            )
        """))
        await session.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_checkout_tenancy "
            "ON checkout_records(tenancy_id)"
        ))

        await session.commit()

    await engine.dispose()
    print("Done: onboarding_sessions and checkout_records tables ready.")


if __name__ == "__main__":
    asyncio.run(run())
