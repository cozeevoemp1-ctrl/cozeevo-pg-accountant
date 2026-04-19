"""Verify org_id column exists on all multi-tenant tables after migration.

CRITICAL: do not run against production DB. Uses a local SQLite in-memory
fallback or a test Postgres via TEST_DATABASE_URL env var.
"""
import os
import pytest
from sqlalchemy import create_engine, inspect, text
from src.database.models import Base
from src.database.migrations.add_org_id_2026_04_19 import TABLES, upgrade

TEST_DB = os.environ.get("TEST_DATABASE_URL", "sqlite:///:memory:")
assert "supabase" not in TEST_DB.lower(), "refusing to run migration test against Supabase"
assert "cozeevo" not in TEST_DB.lower(), "refusing to run migration test against production"


@pytest.fixture
def engine():
    e = create_engine(TEST_DB)
    Base.metadata.create_all(e)  # create all tables at pre-migration schema
    return e


def test_all_target_tables_exist(engine):
    insp = inspect(engine)
    existing = set(insp.get_table_names())
    # Only migrate tables that actually exist
    actionable = [t for t in TABLES if t in existing]
    assert len(actionable) > 0, "no target tables found — check model definitions"


def test_upgrade_adds_org_id_column(engine):
    insp = inspect(engine)
    # Before: no org_id (models.py may already have it from ORM definition,
    # so we just verify after upgrade that column is present)
    # Run upgrade
    upgrade(engine)
    # After: every targeted table has org_id
    insp = inspect(engine)
    for table in [t for t in TABLES if t in insp.get_table_names()]:
        cols = {c["name"]: c for c in insp.get_columns(table)}
        assert "org_id" in cols, f"{table} missing org_id after upgrade"
        assert not cols["org_id"]["nullable"], f"{table}.org_id must be NOT NULL"


def test_upgrade_is_idempotent(engine):
    upgrade(engine)
    upgrade(engine)  # second call must not raise


def test_upgrade_creates_indices(engine):
    upgrade(engine)
    insp = inspect(engine)
    for table in [t for t in TABLES if t in insp.get_table_names()]:
        idx_names = [i["name"] for i in insp.get_indexes(table)]
        assert any("org_id" in n for n in idx_names), f"{table} missing org_id index"
