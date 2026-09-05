"""
One-off (2026-09-05): Room 106 — Raghav Mittal's 3-month lock-in was typed into the
booking note ("Lock in period three months") because the booking forms had no lock-in
field, so lock_in_months stayed 0 on both the onboarding session and the tenancy.
Sets lock_in_months=3 on tenancy 1296 + onboarding_session 273 and writes audit_log.

Dry-run by default; --write to apply. Idempotent.

    PYTHONPATH=. venv/Scripts/python.exe scripts/_fix_106_lockin.py --write
"""
import argparse
import asyncio
import os
import sys

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.database.db_manager import script_database_url, script_engine_kwargs  # noqa: E402

TENANCY_ID = 1296
SESSION_ID = 273
LOCK_IN = 3
CHANGED_BY = "kiran_script_fix_106_lockin"


async def main(write: bool):
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
    eng = create_async_engine(script_database_url(os.environ["DATABASE_URL"]), **script_engine_kwargs())
    async with eng.begin() as c:
        tn = (await c.execute(text(
            "SELECT tn.id, t.name, r.room_number, tn.lock_in_months, tn.notes "
            "FROM tenancies tn JOIN tenants t ON t.id=tn.tenant_id JOIN rooms r ON r.id=tn.room_id "
            "WHERE tn.id=:id"), {"id": TENANCY_ID})).mappings().first()
        ob = (await c.execute(text(
            "SELECT id, lock_in_months, special_terms FROM onboarding_sessions WHERE id=:id"),
            {"id": SESSION_ID})).mappings().first()
        print("tenancy:", dict(tn) if tn else None)
        print("session:", dict(ob) if ob else None)
        if not tn or tn["room_number"] != "106":
            raise SystemExit("Tenancy 1296 is not Room 106 — aborting")

        if tn["lock_in_months"] == LOCK_IN and (ob or {}).get("lock_in_months") == LOCK_IN:
            print("Already applied — nothing to do.")
            return
        if not write:
            print("\nDRY RUN — re-run with --write to apply.")
            return

        await c.execute(text("UPDATE tenancies SET lock_in_months=:v WHERE id=:id"),
                        {"v": LOCK_IN, "id": TENANCY_ID})
        await c.execute(text("UPDATE onboarding_sessions SET lock_in_months=:v WHERE id=:id"),
                        {"v": LOCK_IN, "id": SESSION_ID})
        await c.execute(text(
            "INSERT INTO audit_log (created_at, changed_by, entity_type, entity_id, entity_name, "
            "field, old_value, new_value) VALUES (NOW(), :by, 'tenancy', :id, :name, 'lock_in_months', "
            ":old, :new)"),
            {"by": CHANGED_BY, "id": TENANCY_ID, "name": f"{tn['name']} (Room 106)",
             "old": str(tn["lock_in_months"] or 0), "new": str(LOCK_IN)})
        print(f"\nApplied: tenancy {TENANCY_ID} + session {SESSION_ID} lock_in_months={LOCK_IN}, audit_log written.")
    await eng.dispose()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    asyncio.run(main(ap.parse_args().write))
