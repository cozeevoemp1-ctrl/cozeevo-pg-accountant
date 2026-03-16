"""
Master Migration Script - Cozeevo PG Accountant
================================================
SAFE TO RUN MULTIPLE TIMES - every operation is idempotent.

Usage:
    python -m src.database.migrate_all              # full schema sync
    python -m src.database.migrate_all --seed       # schema + seed data
    python -m src.database.migrate_all --status     # show current DB state only

Strategy per scenario:
  Scenario                 | Command                   | What it does
  -------------------------|---------------------------|------------------
  Fresh install            | migrate_all --seed        | Create + seed
  Code update (new cols)   | migrate_all               | ALTER TABLE only
  Test -> Production       | migrate_all --seed        | Schema + roles
  Add new PG customer      | migrate_all --seed        | Per new Supabase
  Fix seed data            | migrate_all --seed        | ON CONFLICT skip

DATA LOAD STRATEGY:
  L0 (permanent tables)  -> INSERT ... ON CONFLICT DO NOTHING  (never wipe)
  L1 (tenants/tenancies) -> INSERT ... ON CONFLICT DO NOTHING  (Excel import owns this)
  L2 (transactions)      -> INSERT ... ON CONFLICT DO NOTHING  (never delete financial data)
  L3 (operational)       -> SAFE TO TRUNCATE for clean test reset
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text, inspect
from sqlalchemy.ext.asyncio import AsyncConnection

load_dotenv()

DB_URL = os.getenv("DATABASE_URL", "").replace("postgresql://", "postgresql+asyncpg://")

# == Schema migrations ==---------------------------
# Each entry: (table, column, sql_type, [default])
# ADD_COLUMNS are safe to re-run - skipped if column already exists.

ADD_COLUMNS: list[tuple[str, str, str]] = [
    # Tenant extended registration fields (added 2026-03-13)
    ("tenants", "father_name",                    "VARCHAR(120)"),
    ("tenants", "father_phone",                   "VARCHAR(20)"),
    ("tenants", "date_of_birth",                  "DATE"),
    ("tenants", "permanent_address",              "TEXT"),
    ("tenants", "email",                          "VARCHAR(120)"),
    ("tenants", "occupation",                     "VARCHAR(120)"),
    ("tenants", "emergency_contact_relationship", "VARCHAR(60)"),
    # WiFi floor map (added 2026-03-15)
    ("properties", "wifi_floor_map",              "JSONB"),
]

# -- Tables to create if missing -----------------------------------------------

CREATE_TABLES: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS onboarding_sessions (
        id           SERIAL PRIMARY KEY,
        tenant_id    INTEGER NOT NULL REFERENCES tenants(id),
        tenancy_id   INTEGER REFERENCES tenancies(id),
        step         VARCHAR(40) DEFAULT 'ask_dob',
        collected_data TEXT,
        expires_at   TIMESTAMP NOT NULL,
        completed    BOOLEAN DEFAULT FALSE,
        created_at   TIMESTAMP DEFAULT NOW()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_onboarding_tenant  ON onboarding_sessions(tenant_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_onboarding_expires ON onboarding_sessions(expires_at)
    """,
    """
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
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_checkout_tenancy ON checkout_records(tenancy_id)
    """,
    # ── Self-Learning tables (added 2026-03-14) ──────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS pending_learning (
        id               SERIAL PRIMARY KEY,
        phone            VARCHAR(30) NOT NULL,
        role             VARCHAR(20) DEFAULT 'lead',
        message          TEXT NOT NULL,
        detected_intent  VARCHAR(60) DEFAULT 'UNKNOWN',
        resolved         BOOLEAN DEFAULT FALSE,
        created_at       TIMESTAMP DEFAULT NOW()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_pending_learning_resolved ON pending_learning(resolved)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_pending_learning_created  ON pending_learning(created_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS learned_rules (
        id           SERIAL PRIMARY KEY,
        pattern      TEXT NOT NULL,
        intent       VARCHAR(60) NOT NULL,
        confidence   NUMERIC(4,2) DEFAULT 0.87,
        applies_to   VARCHAR(20) DEFAULT 'all',
        created_by   VARCHAR(30),
        active       BOOLEAN DEFAULT TRUE,
        created_at   TIMESTAMP DEFAULT NOW()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_learned_rules_intent ON learned_rules(intent)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_learned_rules_active ON learned_rules(active)
    """,
    # ── Complaints / maintenance tickets (added 2026-03-15) ──────────────────
    """
    CREATE TABLE IF NOT EXISTS complaints (
        id          SERIAL PRIMARY KEY,
        tenancy_id  INTEGER NOT NULL REFERENCES tenancies(id),
        category    VARCHAR(20) NOT NULL,
        sub_item    VARCHAR(100),
        description TEXT NOT NULL,
        status      VARCHAR(20) DEFAULT 'open',
        created_at  TIMESTAMP DEFAULT NOW(),
        resolved_at TIMESTAMP,
        resolved_by VARCHAR(20),
        notes       TEXT
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_complaints_tenancy ON complaints(tenancy_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_complaints_status  ON complaints(status)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_complaints_created ON complaints(created_at)
    """,
    # ── v2 Supervisor Agent: conversation history window (added 2026-03-16) ──
    """
    CREATE TABLE IF NOT EXISTS conversation_history (
        id         SERIAL PRIMARY KEY,
        phone      VARCHAR(30) NOT NULL,
        sent_by    VARCHAR(10) NOT NULL,
        message    TEXT NOT NULL,
        intent     VARCHAR(60),
        role       VARCHAR(20),
        created_at TIMESTAMP DEFAULT NOW()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_conv_hist_phone_created
        ON conversation_history(phone, created_at DESC)
    """,
]


async def _col_exists(conn: AsyncConnection, table: str, col: str) -> bool:
    r = await conn.execute(text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name=:t AND column_name=:c"
    ), {"t": table, "c": col})
    return r.fetchone() is not None


async def run_schema(conn: AsyncConnection) -> None:
    print("\n== Schema migrations ==")

    # 1. Create new tables
    for stmt in CREATE_TABLES:
        await conn.execute(text(stmt))
    print("  [ok] onboarding_sessions, checkout_records, pending_learning, learned_rules, complaints, conversation_history - created or already exist")

    # 2. Add new columns to existing tables
    for (table, col, col_type) in ADD_COLUMNS:
        if await _col_exists(conn, table, col):
            print(f"  [skip] {table}.{col} - already exists")
        else:
            await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}"))
            print(f"  [added] {table}.{col} {col_type}")


async def run_seed(conn: AsyncConnection) -> None:
    """
    Insert baseline seed rows using ON CONFLICT DO NOTHING - safe to re-run.
    Only inserts if the row doesn't already exist.
    """
    print("\n== Seed data ==")

    # authorized_users (admin + partner) - phone is UNIQUE key
    await conn.execute(text("""
        INSERT INTO authorized_users (name, phone, role, active)
        VALUES
          ('Kiran',   '7845952289', 'admin',      TRUE),
          ('Partner', '7358341775', 'power_user', TRUE)
        ON CONFLICT (phone) DO NOTHING
    """))
    print("  [ok] authorized_users - admin + power_user")

    # food_plans
    await conn.execute(text("""
        INSERT INTO food_plans (name, includes_lunch_box, monthly_cost, active)
        VALUES
          ('Veg',         FALSE, 0, TRUE),
          ('Non-Veg',     FALSE, 0, TRUE),
          ('Egg',         FALSE, 0, TRUE),
          ('Lunch Box',   TRUE,  0, TRUE),
          ('None',        FALSE, 0, TRUE)
        ON CONFLICT DO NOTHING
    """))
    print("  [ok] food_plans")

    # expense_categories
    await conn.execute(text("""
        INSERT INTO expense_categories (name)
        VALUES
          ('Electricity'), ('Water'), ('Internet'), ('Salary'),
          ('Maintenance'), ('Cleaning'), ('Plumbing'), ('Miscellaneous')
        ON CONFLICT (name) DO NOTHING
    """))
    print("  [ok] expense_categories")

    print("  [note] Properties/rooms skipped - use excel_import.py for master data")


async def show_status(conn: AsyncConnection) -> None:
    print("\n== DB Status ==")
    r = await conn.execute(text(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
    ))
    tables = [row[0] for row in r.fetchall()]
    print(f"  Tables ({len(tables)}): {', '.join(tables)}")

    # Row counts for key tables
    key_tables = ["tenants", "tenancies", "payments", "rent_schedule",
                  "onboarding_sessions", "checkout_records", "authorized_users"]
    for t in key_tables:
        if t in tables:
            r2 = await conn.execute(text(f"SELECT COUNT(*) FROM {t}"))
            print(f"  {t}: {r2.scalar()} rows")

    # Tenant columns
    r3 = await conn.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='tenants' ORDER BY ordinal_position"
    ))
    cols = [row[0] for row in r3.fetchall()]
    print(f"\n  tenants columns ({len(cols)}): {', '.join(cols)}")


async def main(args: argparse.Namespace) -> None:
    if not DB_URL or DB_URL == "+asyncpg://":
        print("ERROR: DATABASE_URL not set in .env")
        sys.exit(1)

    engine = create_async_engine(DB_URL, echo=False)
    async with engine.begin() as conn:
        await show_status(conn)
        if not args.status:
            await run_schema(conn)
        if args.seed:
            await run_seed(conn)
    await engine.dispose()
    print("\nDone.\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cozeevo PG - master DB migration")
    parser.add_argument("--seed",   action="store_true", help="Also insert seed data")
    parser.add_argument("--status", action="store_true", help="Show DB state only, no changes")
    asyncio.run(main(parser.parse_args()))
