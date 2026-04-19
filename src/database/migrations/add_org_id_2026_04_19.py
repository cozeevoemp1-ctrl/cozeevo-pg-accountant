"""Append-only migration: add org_id to multi-tenant tables.

Default = 1 (Cozeevo). Future orgs (Kozzy SaaS customers) get incrementing IDs.
Idempotent via IF NOT EXISTS / column-exists check. Creates per-table index on org_id.

DO NOT touch this file after merging — future migrations go in new files.

Note: task spec listed 'rent_schedules' but the actual table is 'rent_schedule' (singular).
      We use the real table name here.
"""
from sqlalchemy import text
from sqlalchemy.engine import Engine

TABLES = (
    "tenancies",
    "payments",
    "rooms",
    "rent_revisions",
    "rent_schedule",   # actual table name (singular) — not rent_schedules
    "expenses",
    "leads",
    "audit_log",
)


def upgrade(engine: Engine) -> None:
    """Add org_id column + index to each table if not present. Idempotent."""
    with engine.begin() as conn:
        for table in TABLES:
            # Skip tables that don't exist in this DB (environment variance)
            if engine.dialect.name == "sqlite":
                exists = conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table' AND name=:t"),
                    {"t": table},
                ).fetchone()
            else:
                exists = conn.execute(
                    text("SELECT tablename FROM pg_tables WHERE tablename=:t"),
                    {"t": table},
                ).fetchone()

            if not exists:
                continue

            # Check if column already exists (idempotency)
            has_col = False
            try:
                if engine.dialect.name == "sqlite":
                    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
                    has_col = any(r[1] == "org_id" for r in rows)
                else:
                    row = conn.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_name=:t AND column_name='org_id'"
                        ),
                        {"t": table},
                    ).fetchone()
                    has_col = row is not None
            except Exception:
                pass

            if not has_col:
                conn.execute(text(
                    f"ALTER TABLE {table} ADD COLUMN org_id INTEGER NOT NULL DEFAULT 1"
                ))

            # Index — CREATE INDEX IF NOT EXISTS works on both SQLite and Postgres
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS idx_{table}_org_id ON {table}(org_id)"
            ))
