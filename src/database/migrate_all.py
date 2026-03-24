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
          ('Partner', '7358341775', 'admin', TRUE)
        ON CONFLICT (phone) DO NOTHING
    """))
    print("  [ok] authorized_users - admin + admin")

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


async def run_room_master_fix(conn: AsyncConnection) -> None:
    """
    Fix room master data to match verified layout (BRAIN.md §15, verified 2026-03-17).
    Safe to re-run — all UPDATEs are idempotent.

    Staff rooms (is_staff_room=True, excluded from occupancy/revenue):
      THOR: G05, G06, 107, 108, 114, 701
      HULK: G12, 702

    max_occupancy corrections:
      THOR ground: G01,G10=1  G02,G03,G04=2  G07,G08,G09=3
      THOR floors 1-6: x01,x12=1  x02-x11=2
      HULK ground: G11,G20=1  G13,G14=3  G15-G19=2
    """
    print("\n== Room master fix (BRAIN.md §15) ==")

    # ── 1. Mark staff rooms ────────────────────────────────────────────────
    thor_staff = "('G05','G06','107','108','114','701')"
    hulk_staff = "('G12','702')"

    r = await conn.execute(text(f"""
        UPDATE rooms SET is_staff_room = TRUE
        WHERE property_id = (SELECT id FROM properties WHERE name ILIKE '%THOR%' LIMIT 1)
          AND room_number IN {thor_staff}
          AND is_staff_room IS DISTINCT FROM TRUE
    """))
    print(f"  [ok] THOR staff rooms flagged: {r.rowcount} updated")

    r = await conn.execute(text(f"""
        UPDATE rooms SET is_staff_room = TRUE
        WHERE property_id = (SELECT id FROM properties WHERE name ILIKE '%HULK%' LIMIT 1)
          AND room_number IN {hulk_staff}
          AND is_staff_room IS DISTINCT FROM TRUE
    """))
    print(f"  [ok] HULK staff rooms flagged: {r.rowcount} updated")

    # ── 2. THOR ground floor max_occupancy ────────────────────────────────
    r = await conn.execute(text("""
        UPDATE rooms SET max_occupancy = 1
        WHERE property_id = (SELECT id FROM properties WHERE name ILIKE '%THOR%' LIMIT 1)
          AND room_number IN ('G01','G10')
          AND max_occupancy IS DISTINCT FROM 1
    """))
    print(f"  [ok] THOR ground singles (G01,G10): {r.rowcount} updated")

    r = await conn.execute(text("""
        UPDATE rooms SET max_occupancy = 2
        WHERE property_id = (SELECT id FROM properties WHERE name ILIKE '%THOR%' LIMIT 1)
          AND room_number IN ('G02','G03','G04')
          AND max_occupancy IS DISTINCT FROM 2
    """))
    print(f"  [ok] THOR ground doubles (G02-G04): {r.rowcount} updated")

    r = await conn.execute(text("""
        UPDATE rooms SET max_occupancy = 3
        WHERE property_id = (SELECT id FROM properties WHERE name ILIKE '%THOR%' LIMIT 1)
          AND room_number IN ('G07','G08','G09')
          AND max_occupancy IS DISTINCT FROM 3
    """))
    print(f"  [ok] THOR ground triples (G07-G09): {r.rowcount} updated")

    # ── 3. THOR floors 1-6: x01 and x12 = single, x02-x11 = double ───────
    r = await conn.execute(text("""
        UPDATE rooms SET max_occupancy = 1
        WHERE property_id = (SELECT id FROM properties WHERE name ILIKE '%THOR%' LIMIT 1)
          AND is_staff_room = FALSE
          AND (room_number ~ '^[1-6]01$' OR room_number ~ '^[1-6]12$')
          AND max_occupancy IS DISTINCT FROM 1
    """))
    print(f"  [ok] THOR floors 1-6 end-singles (x01,x12): {r.rowcount} updated")

    r = await conn.execute(text("""
        UPDATE rooms SET max_occupancy = 2
        WHERE property_id = (SELECT id FROM properties WHERE name ILIKE '%THOR%' LIMIT 1)
          AND is_staff_room = FALSE
          AND room_number ~ '^[1-6](0[2-9]|1[01])$'
          AND max_occupancy IS DISTINCT FROM 2
    """))
    print(f"  [ok] THOR floors 1-6 doubles (x02-x11): {r.rowcount} updated")

    # ── 4. HULK ground floor max_occupancy ───────────────────────────────
    r = await conn.execute(text("""
        UPDATE rooms SET max_occupancy = 1
        WHERE property_id = (SELECT id FROM properties WHERE name ILIKE '%HULK%' LIMIT 1)
          AND room_number IN ('G11','G20')
          AND max_occupancy IS DISTINCT FROM 1
    """))
    print(f"  [ok] HULK ground singles (G11,G20): {r.rowcount} updated")

    r = await conn.execute(text("""
        UPDATE rooms SET max_occupancy = 3
        WHERE property_id = (SELECT id FROM properties WHERE name ILIKE '%HULK%' LIMIT 1)
          AND room_number IN ('G13','G14')
          AND max_occupancy IS DISTINCT FROM 3
    """))
    print(f"  [ok] HULK ground triples (G13,G14): {r.rowcount} updated")

    r = await conn.execute(text("""
        UPDATE rooms SET max_occupancy = 2
        WHERE property_id = (SELECT id FROM properties WHERE name ILIKE '%HULK%' LIMIT 1)
          AND room_number IN ('G15','G16','G17','G18','G19')
          AND max_occupancy IS DISTINCT FROM 2
    """))
    print(f"  [ok] HULK ground doubles (G15-G19): {r.rowcount} updated")

    print("  [done] Room master fix complete")


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


async def run_promote_partner_to_admin(conn: AsyncConnection) -> None:
    """Promote 7358341775 (partner) from power_user → admin."""
    await conn.execute(text("""
        UPDATE authorized_users
        SET role = 'admin'
        WHERE phone = '7358341775' AND role != 'admin'
    """))
    print("  [ok] authorized_users - 7358341775 promoted to admin")


async def run_bank_analytics_tables(conn: AsyncConnection) -> None:
    """Create bank_uploads and bank_transactions tables (idempotent)."""
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS bank_uploads (
            id          SERIAL PRIMARY KEY,
            phone       VARCHAR(20) NOT NULL,
            file_path   VARCHAR(500),
            row_count   INTEGER DEFAULT 0,
            new_count   INTEGER DEFAULT 0,
            from_date   DATE,
            to_date     DATE,
            status      VARCHAR(20) DEFAULT 'processed',
            uploaded_at TIMESTAMP DEFAULT NOW()
        )
    """))
    await conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_bank_uploads_phone
            ON bank_uploads (phone)
    """))

    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS bank_transactions (
            id            SERIAL PRIMARY KEY,
            upload_id     INTEGER REFERENCES bank_uploads(id),
            txn_date      DATE NOT NULL,
            description   TEXT DEFAULT '',
            amount        NUMERIC(12,2) NOT NULL,
            txn_type      VARCHAR(10) DEFAULT 'expense',
            category      VARCHAR(80) DEFAULT 'Other Expenses',
            sub_category  VARCHAR(120) DEFAULT '',
            upi_reference VARCHAR(120),
            source        VARCHAR(40) DEFAULT 'bank_statement',
            unique_hash   VARCHAR(64),
            created_at    TIMESTAMP DEFAULT NOW()
        )
    """))
    await conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_btxn_date     ON bank_transactions (txn_date)
    """))
    await conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_btxn_type     ON bank_transactions (txn_type)
    """))
    await conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_btxn_category ON bank_transactions (category)
    """))
    await conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_btxn_upload   ON bank_transactions (upload_id)
    """))
    await conn.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_btxn_hash
            ON bank_transactions (unique_hash)
            WHERE unique_hash IS NOT NULL
    """))
    print("  [ok] bank_uploads + bank_transactions tables ready")


async def run_room_cleanup_2026_03_23(conn: AsyncConnection) -> None:
    """
    Room cleanup migration (2026-03-23). Idempotent — safe to re-run.

    1. Delete junk rooms (no real rooms, import artifacts)
    2. Fix HULK corner rooms to max_occupancy=1 (single beds)
    3. Fix staff room assignments (114→HULK, 702→THOR, 618→staff)
    4. Ensure room 702 exists for THOR as staff room
    """
    print("\n== Room cleanup (2026-03-23) ==")

    # ── 1. Delete junk rooms ─────────────────────────────────────────────────
    # These are import artifacts / typos, not real rooms.
    # First nullify tenancy room_id references, then delete.
    # 702 excluded from HULK junk — handled separately (moved to THOR).
    thor_junk = "('113','117','308/118','414','42','DAILY','G13','G14','121','122','11','21','31','41','51','219')"
    hulk_junk = "('12','22','32','62','308','May','504')"

    # Nullify tenancy references to junk rooms so we can delete them
    for prop, junk in [('THOR', thor_junk), ('HULK', hulk_junk)]:
        await conn.execute(text(f"""
            UPDATE tenancies SET room_id = NULL
            WHERE room_id IN (
                SELECT id FROM rooms
                WHERE property_id = (SELECT id FROM properties WHERE name ILIKE '%{prop}%' LIMIT 1)
                  AND room_number IN {junk}
            )
        """))

    r = await conn.execute(text(f"""
        DELETE FROM rooms
        WHERE property_id = (SELECT id FROM properties WHERE name ILIKE '%THOR%' LIMIT 1)
          AND room_number IN {thor_junk}
    """))
    print(f"  [ok] THOR junk rooms deleted: {r.rowcount}")

    r = await conn.execute(text(f"""
        DELETE FROM rooms
        WHERE property_id = (SELECT id FROM properties WHERE name ILIKE '%HULK%' LIMIT 1)
          AND room_number IN {hulk_junk}
    """))
    print(f"  [ok] HULK junk rooms deleted: {r.rowcount}")

    # ── 2. Fix HULK corner rooms to max_occupancy=1 ─────────────────────────
    hulk_corners = "('113','124','213','224','313','324','413','424','513','524','613','624')"
    r = await conn.execute(text(f"""
        UPDATE rooms SET max_occupancy = 1
        WHERE property_id = (SELECT id FROM properties WHERE name ILIKE '%HULK%' LIMIT 1)
          AND room_number IN {hulk_corners}
          AND max_occupancy IS DISTINCT FROM 1
    """))
    print(f"  [ok] HULK corner rooms set to max_occupancy=1: {r.rowcount} updated")

    # ── 3. Fix staff room assignments ────────────────────────────────────────

    # Room 114: move to HULK property and mark as staff
    r = await conn.execute(text("""
        UPDATE rooms
        SET property_id = (SELECT id FROM properties WHERE name ILIKE '%HULK%' LIMIT 1),
            is_staff_room = TRUE
        WHERE room_number = '114'
          AND property_id = (SELECT id FROM properties WHERE name ILIKE '%THOR%' LIMIT 1)
    """))
    print(f"  [ok] Room 114 moved THOR→HULK + staff: {r.rowcount} updated")

    # If 114 already belongs to HULK, just ensure staff flag
    r = await conn.execute(text("""
        UPDATE rooms SET is_staff_room = TRUE
        WHERE room_number = '114'
          AND property_id = (SELECT id FROM properties WHERE name ILIKE '%HULK%' LIMIT 1)
          AND is_staff_room IS DISTINCT FROM TRUE
    """))
    if r.rowcount:
        print(f"  [ok] Room 114 (HULK) staff flag set: {r.rowcount}")

    # Room 618 (HULK): mark as staff
    r = await conn.execute(text("""
        UPDATE rooms SET is_staff_room = TRUE
        WHERE room_number = '618'
          AND property_id = (SELECT id FROM properties WHERE name ILIKE '%HULK%' LIMIT 1)
          AND is_staff_room IS DISTINCT FROM TRUE
    """))
    print(f"  [ok] Room 618 (HULK) staff flag set: {r.rowcount} updated")

    # Room 702: ensure it's THOR + staff. First try moving from HULK if it exists there.
    r = await conn.execute(text("""
        UPDATE rooms
        SET property_id = (SELECT id FROM properties WHERE name ILIKE '%THOR%' LIMIT 1),
            is_staff_room = TRUE
        WHERE room_number = '702'
          AND property_id = (SELECT id FROM properties WHERE name ILIKE '%HULK%' LIMIT 1)
    """))
    if r.rowcount:
        print(f"  [ok] Room 702 moved HULK→THOR + staff: {r.rowcount}")

    # Ensure 702 is staff if already in THOR
    r = await conn.execute(text("""
        UPDATE rooms SET is_staff_room = TRUE
        WHERE room_number = '702'
          AND property_id = (SELECT id FROM properties WHERE name ILIKE '%THOR%' LIMIT 1)
          AND is_staff_room IS DISTINCT FROM TRUE
    """))
    if r.rowcount:
        print(f"  [ok] Room 702 (THOR) staff flag set: {r.rowcount}")

    # ── 4. Ensure room 702 exists for THOR ───────────────────────────────────
    r = await conn.execute(text("""
        INSERT INTO rooms (property_id, room_number, floor, max_occupancy, is_staff_room)
        SELECT
            (SELECT id FROM properties WHERE name ILIKE '%THOR%' LIMIT 1),
            '702', 7, 1, TRUE
        WHERE NOT EXISTS (
            SELECT 1 FROM rooms
            WHERE room_number = '702'
              AND property_id = (SELECT id FROM properties WHERE name ILIKE '%THOR%' LIMIT 1)
        )
    """))
    if r.rowcount:
        print(f"  [ok] Room 702 (THOR) created as staff room")
    else:
        print(f"  [skip] Room 702 (THOR) already exists")

    # ── 5. Correct old staff room list from previous migration ───────────────
    # Previous migration marked 114 as THOR staff and 702 as HULK staff.
    # Remove 114 from THOR staff list (it's now HULK).
    # 701 should be THOR staff (unchanged).
    # Unmark any rooms that shouldn't be staff:
    # THOR staff: G05, G06, 107, 108, 701
    # HULK staff: G12, 114, 618

    print("  [done] Room cleanup complete")


async def run_sharing_type_column(conn: AsyncConnection) -> None:
    """Add sharing_type column to tenancies + create SharingType enum. Idempotent."""
    print("\n== Sharing type column (2026-03-23) ==")

    # Create enum type if not exists
    await conn.execute(text("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'sharingtype') THEN
                CREATE TYPE sharingtype AS ENUM ('single','double','triple','premium');
            END IF;
        END $$;
    """))

    # Add column if not exists
    await conn.execute(text("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'tenancies' AND column_name = 'sharing_type'
            ) THEN
                ALTER TABLE tenancies ADD COLUMN sharing_type sharingtype;
            END IF;
        END $$;
    """))
    print("  [ok] sharing_type column ready")

    # Remove 'premium' from roomtype enum if it exists (premium is tenancy attribute, not room)
    # Don't alter existing enum — just note that new rooms should only use single/double/triple

    print("  [done] Sharing type migration complete")


async def _add_receptionist_role(conn: AsyncConnection) -> None:
    """Add 'receptionist' value to the user_role PostgreSQL enum (idempotent)."""
    print("\n== Receptionist role (2026-03-24) ==")
    await conn.execute(text(
        "ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'receptionist'"
    ))
    print("  [ok] user_role enum now includes 'receptionist'")


async def main(args: argparse.Namespace) -> None:
    if not DB_URL or DB_URL == "+asyncpg://":
        print("ERROR: DATABASE_URL not set in .env")
        sys.exit(1)

    engine = create_async_engine(DB_URL, echo=False)
    async with engine.begin() as conn:
        await show_status(conn)
        if not args.status:
            await run_schema(conn)
            await run_room_master_fix(conn)
            await run_promote_partner_to_admin(conn)
            await run_bank_analytics_tables(conn)
            await run_room_cleanup_2026_03_23(conn)
            await run_sharing_type_column(conn)
            await _add_receptionist_role(conn)
        if args.seed:
            await run_seed(conn)
    await engine.dispose()
    print("\nDone.\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cozeevo PG - master DB migration")
    parser.add_argument("--seed",   action="store_true", help="Also insert seed data")
    parser.add_argument("--status", action="store_true", help="Show DB state only, no changes")
    asyncio.run(main(parser.parse_args()))
