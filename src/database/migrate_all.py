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
    # Tenant food preference (added 2026-03-29)
    ("tenants", "food_preference",                "VARCHAR(20)"),
    # Tenant extended KYC fields (added 2026-04-05)
    ("tenants", "educational_qualification",      "VARCHAR(120)"),
    ("tenants", "office_address",                 "TEXT"),
    ("tenants", "office_phone",                   "VARCHAR(20)"),
    # Staff→room assignment (added 2026-04-20)
    ("staff",   "room_id",                        "INTEGER REFERENCES rooms(id)"),
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
    # ── Day-wise / short-stay table (added 2026-04-07) ──────────────────────
    """
    CREATE TABLE IF NOT EXISTS daywise_stays (
        id              SERIAL PRIMARY KEY,
        room_number     VARCHAR(10) NOT NULL,
        guest_name      VARCHAR(200) NOT NULL,
        phone           VARCHAR(20),
        checkin_date    DATE NOT NULL,
        checkout_date   DATE,
        num_days        INTEGER,
        stay_period     VARCHAR(100),
        sharing         INTEGER,
        occupancy       INTEGER,
        booking_amount  NUMERIC(12,2) DEFAULT 0,
        daily_rate      NUMERIC(10,2) DEFAULT 0,
        total_amount    NUMERIC(12,2) DEFAULT 0,
        maintenance     NUMERIC(10,2) DEFAULT 0,
        payment_date    DATE,
        assigned_staff  VARCHAR(50),
        status          VARCHAR(20) DEFAULT 'EXIT',
        comments        TEXT,
        source_file     VARCHAR(100),
        unique_hash     VARCHAR(64) UNIQUE,
        created_at      TIMESTAMPTZ DEFAULT NOW()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_daywise_checkin ON daywise_stays(checkin_date)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_daywise_room ON daywise_stays(room_number)
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
    print(f"  [ok] Room 114 moved THOR->HULK + staff: {r.rowcount} updated")

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
        print(f"  [ok] Room 702 moved HULK->THOR + staff: {r.rowcount}")

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
    """Add 'receptionist' value to the user_role PostgreSQL enum (idempotent).
    Skips gracefully if user_role is not a Postgres ENUM (e.g. VARCHAR column)."""
    print("\n== Receptionist role (2026-03-24) ==")
    # Check if the enum type exists first (could be 'userrole' or 'user_role')
    result = await conn.execute(text("""
        SELECT typname FROM pg_type WHERE typname IN ('userrole', 'user_role') LIMIT 1
    """))
    row = result.fetchone()
    if row:
        enum_name = row[0]
        await conn.execute(text(
            f"ALTER TYPE {enum_name} ADD VALUE IF NOT EXISTS 'receptionist'"
        ))
        print(f"  [ok] {enum_name} enum now includes 'receptionist'")
    else:
        print("  [skip] role enum type not found — role stored as text, no migration needed")


async def run_activity_log_table(conn: AsyncConnection) -> None:
    """Create activity_log table (idempotent). Added 2026-03-26."""
    print("\n== Activity log table (2026-03-26) ==")
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS activity_log (
            id            SERIAL PRIMARY KEY,
            created_at    TIMESTAMP DEFAULT NOW(),
            logged_by     VARCHAR(30) NOT NULL,
            log_type      VARCHAR(20) DEFAULT 'note',
            room          VARCHAR(20),
            tenant_name   VARCHAR(120),
            description   TEXT NOT NULL,
            amount        NUMERIC(12,2),
            media_url     VARCHAR(500),
            source        VARCHAR(20) DEFAULT 'whatsapp',
            linked_id     INTEGER,
            linked_type   VARCHAR(30),
            property_name VARCHAR(120),
            dedup_hash    VARCHAR(64)
        )
    """))
    await conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_activity_log_created
            ON activity_log (created_at)
    """))
    await conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_activity_log_logged_by
            ON activity_log (logged_by)
    """))
    await conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_activity_log_type
            ON activity_log (log_type)
    """))
    await conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_activity_log_room
            ON activity_log (room)
    """))
    await conn.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_activity_log_dedup
            ON activity_log (dedup_hash)
            WHERE dedup_hash IS NOT NULL
    """))
    print("  [ok] activity_log table ready")


async def run_chat_messages_table(conn: AsyncConnection) -> None:
    """Create chat_messages table for full conversation history (idempotent). Added 2026-03-26."""
    print("\n== Chat messages table (2026-03-26) ==")
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS chat_messages (
            id         SERIAL PRIMARY KEY,
            phone      VARCHAR(30) NOT NULL,
            direction  VARCHAR(10) NOT NULL,
            message    TEXT NOT NULL,
            intent     VARCHAR(60),
            role       VARCHAR(20),
            created_at TIMESTAMP DEFAULT NOW()
        )
    """))
    await conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_chat_messages_phone
            ON chat_messages (phone)
    """))
    await conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_chat_messages_phone_created
            ON chat_messages (phone, created_at DESC)
    """))
    print("  [ok] chat_messages table ready")


async def run_simplify_roles_2026_04_01(engine) -> None:
    """Simplify to 3 roles: admin, owner, receptionist. Remove key_user/power_user. Added 2026-04-01.
    Uses separate connections because PG requires new enum values to be committed before use."""
    print("\n== Simplify roles (2026-04-01) ==")

    # Step 1: Add 'owner' to enum in its own transaction
    async with engine.begin() as conn:
        await conn.execute(text("SET statement_timeout = '120s'"))
        await conn.execute(text("""
            DO $$ BEGIN
                ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'owner';
            EXCEPTION WHEN duplicate_object THEN NULL;
            END $$
        """))
    print("  [ok] 'owner' enum value added")

    # Step 2: Use the new value in a separate transaction
    async with engine.begin() as conn:
        # Migrate power_user → owner
        r = await conn.execute(text("""
            UPDATE authorized_users SET role = 'owner' WHERE role = 'power_user'
        """))
        print(f"  [ok] power_user -> owner: {r.rowcount} rows")

        # Migrate key_user → owner
        r = await conn.execute(text("""
            UPDATE authorized_users SET role = 'owner' WHERE role = 'key_user'
        """))
        print(f"  [ok] key_user -> owner: {r.rowcount} rows")

        # Update Lakshmi and Prabhakaran to owner
        r = await conn.execute(text("""
            UPDATE authorized_users SET role = 'owner'
            WHERE phone IN ('7358341775', '9444296681') AND role = 'admin'
        """))
        print(f"  [ok] Lakshmi + Prabhakaran -> owner: {r.rowcount} rows")

        # Remove test users
        r = await conn.execute(text("""
            DELETE FROM authorized_users WHERE phone IN ('9000000099', '9999999999')
        """))
        print(f"  [ok] removed test users: {r.rowcount} rows")

    print("  [ok] roles simplified")


async def run_add_lokesh_receptionist(conn: AsyncConnection) -> None:
    """Add Lokesh (7680814628) as receptionist. Added 2026-04-06."""
    print("\n-- Add Lokesh receptionist --")
    await conn.execute(text("""
        INSERT INTO authorized_users (phone, name, role, added_by, active)
        VALUES ('7680814628', 'Lokesh', 'receptionist', '7845952289', TRUE)
        ON CONFLICT (phone) DO UPDATE SET
            role = 'receptionist',
            active = TRUE,
            name = 'Lokesh'
    """))
    print("  [ok] Lokesh (7680814628) -> receptionist")


async def run_create_pg_config(conn: AsyncConnection) -> None:
    """Create property_config table for multi-tenant PG configuration. Added 2026-04-08."""
    print("\n-- Create property_config table --")
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS property_config (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            pg_name             TEXT NOT NULL,
            brand_name          TEXT,
            brand_voice         TEXT,
            buildings           JSONB,
            rooms               JSONB,
            staff_rooms         JSONB,
            staff               JSONB,
            admin_phones        JSONB,
            pricing             JSONB,
            bank_config         JSONB,
            expense_categories  JSONB,
            custom_intents      JSONB,
            business_rules      JSONB,
            whatsapp_config     JSONB,
            gsheet_config       JSONB,
            timezone            TEXT DEFAULT 'Asia/Kolkata',
            is_active           BOOLEAN DEFAULT TRUE,
            created_at          TIMESTAMPTZ DEFAULT NOW(),
            updated_at          TIMESTAMPTZ DEFAULT NOW()
        )
    """))
    print("  [ok] property_config table ready")


async def run_create_intent_examples(conn: AsyncConnection) -> None:
    """Create intent_examples table for agentic learning. Added 2026-04-08."""
    print("\n-- Create intent_examples table --")
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS intent_examples (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            pg_id           UUID REFERENCES property_config(id),
            message_text    TEXT NOT NULL,
            intent          TEXT NOT NULL,
            role            TEXT,
            entities        JSONB,
            confidence      FLOAT,
            source          TEXT,
            confirmed_by    TEXT,
            is_active       BOOLEAN DEFAULT TRUE,
            created_at      TIMESTAMPTZ DEFAULT NOW(),
            updated_at      TIMESTAMPTZ DEFAULT NOW()
        )
    """))
    await conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_intent_examples_pg_id
        ON intent_examples(pg_id)
    """))
    await conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_intent_examples_intent
        ON intent_examples(intent)
    """))
    print("  [ok] intent_examples table + indexes ready")


async def run_create_classification_log(conn: AsyncConnection) -> None:
    """Create classification_log table for tracking intent classification results. Added 2026-04-08."""
    print("\n-- Create classification_log table --")
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS classification_log (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            pg_id               UUID REFERENCES property_config(id),
            message_text        TEXT,
            phone               TEXT,
            role                TEXT,
            regex_result        TEXT,
            regex_confidence    FLOAT,
            llm_result          TEXT,
            llm_confidence      FLOAT,
            final_intent        TEXT,
            was_corrected       BOOLEAN DEFAULT FALSE,
            corrected_to        TEXT,
            created_at          TIMESTAMPTZ DEFAULT NOW()
        )
    """))
    await conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_classification_log_pg_id
        ON classification_log(pg_id)
    """))
    print("  [ok] classification_log table + index ready")


async def run_seed_cozeevo_pg_config(conn: AsyncConnection) -> None:
    """Seed Cozeevo Co-living as the first PG in pg_config. Added 2026-04-08."""
    print("\n-- Seed Cozeevo property_config --")
    existing = await conn.execute(text("""
        SELECT id FROM property_config WHERE pg_name = 'Cozeevo Co-living' LIMIT 1
    """))
    if existing.fetchone():
        print("  [skip] Cozeevo Co-living already exists")
        return
    await conn.execute(
        text("""
        INSERT INTO property_config (
            pg_name, brand_name, brand_voice,
            buildings, staff_rooms, admin_phones,
            pricing, expense_categories, business_rules,
            timezone, is_active
        ) VALUES (
            :pg_name, :brand_name, :brand_voice,
            cast(:buildings as jsonb), cast(:staff_rooms as jsonb), cast(:admin_phones as jsonb),
            cast(:pricing as jsonb), cast(:expense_categories as jsonb), cast(:business_rules as jsonb),
            :timezone, TRUE
        )
        """).bindparams(
            pg_name="Cozeevo Co-living",
            brand_name="Cozeevo Help Desk",
            brand_voice="You are Cozeevo Help Desk, a friendly and efficient AI assistant for Cozeevo Co-living PG in Chennai. Be concise, professional, and helpful. Use simple English. No emojis unless the user uses them first.",
            buildings='[{"name":"THOR","floors":7,"type":"male"},{"name":"HULK","floors":6,"type":"female"}]',
            staff_rooms='["G05","G06","107","108","701","702","G12","114","618"]',
            admin_phones='["+917845952289","+917358341775","+919444296681"]',
            pricing='{"sharing_3":7500,"sharing_2":9000,"single":12000,"single_ac":15000}',
            expense_categories='["Electricity","Water","Salaries","Food","Furniture","Maintenance","IT","Internet","Gas","Property Rent","Police/Govt","Marketing","Shopping","Bank Charges","Housekeeping","Security","Insurance","Legal","Other"]',
            business_rules='{"proration":"first_month_standard_only","checkout_notice_day":5,"deposit_months":1,"billing_cycle":"monthly","checkout_full_month_charged":true}',
            timezone="Asia/Kolkata",
        )
    )
    print("  [ok] Cozeevo Co-living seeded into pg_config")


async def run_add_receipt_url_column(conn: AsyncConnection) -> None:
    """Add receipt_url column to payments table. Added 2026-04-10."""
    print("\n-- Add receipt_url to payments --")
    await conn.execute(text("""
        ALTER TABLE payments ADD COLUMN IF NOT EXISTS receipt_url VARCHAR(500)
    """))
    print("  [ok] receipt_url column added")


async def run_audit_log_tables(conn: AsyncConnection) -> None:
    """Create audit_log and rent_revisions tables. Added 2026-04-11."""
    print("\n== Create audit_log + rent_revisions tables ==")

    # audit_log
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id          SERIAL PRIMARY KEY,
            created_at  TIMESTAMPTZ DEFAULT NOW(),
            changed_by  VARCHAR(30) NOT NULL,
            entity_type VARCHAR(30) NOT NULL,
            entity_id   INTEGER NOT NULL,
            entity_name VARCHAR(120),
            field       VARCHAR(60) NOT NULL,
            old_value   VARCHAR(500),
            new_value   VARCHAR(500),
            room_number VARCHAR(20),
            source      VARCHAR(20) DEFAULT 'whatsapp',
            note        TEXT
        )
    """))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_audit_log_created ON audit_log(created_at)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_audit_log_entity ON audit_log(entity_type, entity_id)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_audit_log_changed_by ON audit_log(changed_by)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_audit_log_room ON audit_log(room_number)"))
    print("  [ok] audit_log table created")

    # rent_revisions
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS rent_revisions (
            id              SERIAL PRIMARY KEY,
            tenancy_id      INTEGER NOT NULL REFERENCES tenancies(id),
            old_rent        NUMERIC(12,2) NOT NULL,
            new_rent        NUMERIC(12,2) NOT NULL,
            effective_date  DATE NOT NULL,
            changed_by      VARCHAR(30) NOT NULL,
            reason          VARCHAR(200),
            created_at      TIMESTAMPTZ DEFAULT NOW()
        )
    """))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_rent_rev_tenancy ON rent_revisions(tenancy_id)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_rent_rev_effective ON rent_revisions(effective_date)"))
    print("  [ok] rent_revisions table created")


async def run_add_org_id_2026_04_19(conn) -> None:
    """Add org_id column + index to all multi-tenant tables. Added 2026-04-19.

    The canonical logic lives in migrations/add_org_id_2026_04_19.py and uses
    sync SQLAlchemy so it can also be exercised in unit tests (SQLite in-memory).
    Here we replicate the same idempotent DDL directly on the async connection.
    """
    print("\n-- Add org_id to multi-tenant tables (2026-04-19) --")
    try:
        from src.database.migrations.add_org_id_2026_04_19 import TABLES
    except ImportError:
        from database.migrations.add_org_id_2026_04_19 import TABLES  # VPS import path

    for table in TABLES:
        # Skip if table doesn't exist
        exists = await conn.execute(text(
            "SELECT tablename FROM pg_tables WHERE tablename=:t"
        ), {"t": table})
        if not exists.fetchone():
            print(f"  [skip] {table} — table not found")
            continue

        # Check column existence
        has_col = await conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name=:t AND column_name='org_id'"
        ), {"t": table})
        if not has_col.fetchone():
            await conn.execute(text(
                f"ALTER TABLE {table} ADD COLUMN org_id INTEGER NOT NULL DEFAULT 1"
            ))
            print(f"  [added] {table}.org_id")
        else:
            print(f"  [skip] {table}.org_id already exists")

        await conn.execute(text(
            f"CREATE INDEX IF NOT EXISTS idx_{table}_org_id ON {table}(org_id)"
        ))

    print("  [ok] org_id migration complete")


async def run_add_staff_room_id_2026_04_20(conn) -> None:
    """Add staff.room_id FK so staff can be linked to the room they live in.
    Added 2026-04-20. Many staff can share one room — no max_occupancy / sharing cap."""
    print("\n-- Add staff.room_id (2026-04-20) --")

    has_col = await conn.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='staff' AND column_name='room_id'"
    ))
    if has_col.fetchone():
        print("  [skip] staff.room_id already exists")
    else:
        await conn.execute(text(
            "ALTER TABLE staff ADD COLUMN room_id INTEGER REFERENCES rooms(id)"
        ))
        print("  [added] staff.room_id")

    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_staff_room_id ON staff(room_id)"
    ))
    print("  [ok] staff.room_id migration complete")


async def run_allow_unassigned_room_2026_04_24(conn) -> None:
    """Allow room_id to be NULL on tenancies for future bookings. Added 2026-04-24."""
    print("\n== Make tenancies.room_id nullable ==")
    try:
        await conn.execute(text(
            "ALTER TABLE tenancies ALTER COLUMN room_id DROP NOT NULL"
        ))
        print("  [ok] tenancies.room_id is now nullable")
    except Exception as e:
        print(f"  [skip] tenancies.room_id nullable: {e}")


async def run_unhandled_requests_table(conn) -> None:
    """Create unhandled_requests table for logging unknown intents. Added 2026-04-13."""
    print("\n== Create unhandled_requests table ==")
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS unhandled_requests (
            id              SERIAL PRIMARY KEY,
            created_at      TIMESTAMPTZ DEFAULT now(),
            phone           VARCHAR(20) NOT NULL,
            message         TEXT NOT NULL,
            role            VARCHAR(20),
            resolved        BOOLEAN DEFAULT FALSE,
            intent_created  VARCHAR(60)
        )
    """))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_unhandled_created ON unhandled_requests(created_at)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_unhandled_resolved ON unhandled_requests(resolved)"))
    print("  [ok] unhandled_requests table created")


async def run_extend_onboarding_sessions(conn) -> None:
    """Extend onboarding_sessions table for digital form flow."""
    print("\n-- Extend onboarding_sessions for digital form --")
    new_cols = [
        ("token", "VARCHAR(36)"),
        ("status", "VARCHAR(20) DEFAULT 'draft'"),
        ("created_by_phone", "VARCHAR(20)"),
        ("tenant_phone", "VARCHAR(20)"),
        ("room_id", "INTEGER REFERENCES rooms(id)"),
        ("agreed_rent", "NUMERIC(12,2) DEFAULT 0"),
        ("security_deposit", "NUMERIC(12,2) DEFAULT 0"),
        ("maintenance_fee", "NUMERIC(10,2) DEFAULT 0"),
        ("booking_amount", "NUMERIC(12,2) DEFAULT 0"),
        ("advance_mode", "VARCHAR(10)"),
        ("checkin_date", "DATE"),
        ("stay_type", "VARCHAR(10) DEFAULT 'monthly'"),
        ("lock_in_months", "INTEGER DEFAULT 0"),
        ("special_terms", "TEXT"),
        ("tenant_data", "TEXT"),
        ("signature_image", "TEXT"),
        ("agreement_pdf_path", "VARCHAR(255)"),
        ("completed_at", "TIMESTAMP"),
        ("approved_at", "TIMESTAMP"),
    ]
    for col_name, col_type in new_cols:
        try:
            await conn.execute(text(
                f"ALTER TABLE onboarding_sessions ADD COLUMN IF NOT EXISTS {col_name} {col_type}"
            ))
        except Exception:
            pass
    await conn.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_onboarding_token ON onboarding_sessions(token)"
    ))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_onboarding_status ON onboarding_sessions(status)"
    ))
    try:
        await conn.execute(text(
            "ALTER TABLE onboarding_sessions ALTER COLUMN tenant_id DROP NOT NULL"
        ))
    except Exception:
        pass
    # Daily stay fields + sharing override
    for col_name, col_type in [
        ("checkout_date", "DATE"),
        ("num_days", "INTEGER DEFAULT 0"),
        ("daily_rate", "NUMERIC(10,2) DEFAULT 0"),
        ("sharing_type", "VARCHAR(20)"),
    ]:
        try:
            await conn.execute(text(
                f"ALTER TABLE onboarding_sessions ADD COLUMN IF NOT EXISTS {col_name} {col_type}"
            ))
        except Exception:
            pass
    print("  [ok] onboarding_sessions extended")


async def run_enable_rls_all_tables(conn) -> None:
    """Enable RLS on ALL application tables. Idempotent — safe to run every migration.
    Uses pg_tables to discover all public-schema tables dynamically,
    so new tables are covered automatically."""
    print("\n-- Enable RLS on all tables --")
    result = await conn.execute(text("""
        SELECT tablename FROM pg_tables
        WHERE schemaname = 'public'
        ORDER BY tablename
    """))
    tables = [row[0] for row in result.fetchall()]
    enabled = 0
    for t in tables:
        # Skip Postgres/Supabase internal tables and non-owned views
        if t.startswith(('_', 'sql_')) or t in (
            'schema_migrations', 'spatial_ref_sys',
            'pg_config', 'pg_stat_statements',
        ):
            continue
        try:
            await conn.execute(text(f'SAVEPOINT rls_{enabled}'))
            await conn.execute(text(f'ALTER TABLE "{t}" ENABLE ROW LEVEL SECURITY'))
            await conn.execute(text(f'RELEASE SAVEPOINT rls_{enabled}'))
            enabled += 1
        except Exception as e:
            await conn.execute(text(f'ROLLBACK TO SAVEPOINT rls_{enabled}'))
            print(f"  [skip] {t} - {e}")
    print(f"  [ok] RLS enabled on {enabled} tables")


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
            await run_activity_log_table(conn)
            await run_chat_messages_table(conn)
            await run_add_lokesh_receptionist(conn)
            await run_create_pg_config(conn)
            await run_create_intent_examples(conn)
            await run_create_classification_log(conn)
            await run_seed_cozeevo_pg_config(conn)
            await run_add_receipt_url_column(conn)
            await run_audit_log_tables(conn)
            await run_unhandled_requests_table(conn)
            await run_extend_onboarding_sessions(conn)
            await run_add_org_id_2026_04_19(conn)
            await run_add_staff_room_id_2026_04_20(conn)
            await run_allow_unassigned_room_2026_04_24(conn)
        # Runs outside the main transaction (needs separate commits for enum values)
        try:
            await run_simplify_roles_2026_04_01(engine)
        except Exception as e:
            print(f"  [warn] simplify_roles failed (non-fatal): {e}")
        if args.seed:
            async with engine.begin() as conn2:
                await run_seed(conn2)
    # RLS in its own transaction so it always commits independently
    async with engine.begin() as conn:
        await run_enable_rls_all_tables(conn)
    await engine.dispose()
    print("\nDone.\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cozeevo PG - master DB migration")
    parser.add_argument("--seed",   action="store_true", help="Also insert seed data")
    parser.add_argument("--status", action="store_true", help="Show DB state only, no changes")
    asyncio.run(main(parser.parse_args()))
