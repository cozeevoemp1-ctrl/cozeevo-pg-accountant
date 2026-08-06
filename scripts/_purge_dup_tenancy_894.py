"""One-off: hard-delete the duplicate Rakesh record (tenant 897 / tenancy 894).

Runs AFTER _merge_duplicate_tenants_415_615.py, which already moved every unique
payment, document and onboarding session onto the surviving tenancy 901 and voided
the 3 duplicated payment rows.

Everything deleted here is a duplicate whose true copy lives on tenancy 901.
Rows are dumped to scripts/_backup_dup_tenancy_894.json before deletion; audit_log
entries are kept (no FK), so the merge remains traceable.

Dry run:  python scripts/_purge_dup_tenancy_894.py
Apply:    python scripts/_purge_dup_tenancy_894.py --write
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import date, datetime
from decimal import Decimal

from dotenv import load_dotenv
from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

from src.database.db_manager import get_session, init_engine  # noqa: E402

DUP_TENANCY, DUP_TENANT = 894, 897
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_backup_dup_tenancy_894.json")

CHILD_TABLES = [
    "checkout_records", "checkout_sessions", "complaints", "documents",
    "onboarding_sessions", "payments", "refunds", "reminders",
    "rent_revisions", "rent_schedule", "upi_collection_entries", "vacations",
]


def _json(o):
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    if isinstance(o, Decimal):
        return float(o)
    return str(o)


async def main(write: bool) -> None:
    init_engine(os.getenv("DATABASE_URL"))
    dump: dict[str, list] = {}

    async with get_session() as s:
        if write:
            await s.execute(text("SET LOCAL app.allow_historical_write = 'true'"))

        for t in CHILD_TABLES:
            rows = (await s.execute(text(f"SELECT * FROM {t} WHERE tenancy_id = :d"),
                                    {"d": DUP_TENANCY})).mappings().all()
            if rows:
                dump[t] = [dict(r) for r in rows]
                live = [r["id"] for r in rows if not r.get("is_void", False)]
                print(f"{t}: {len(rows)} row(s) {[r['id'] for r in rows]}"
                      + (f"  !! NON-VOID: {live}" if t == "payments" and live else ""))

        for t in ("documents", "onboarding_sessions"):
            rows = (await s.execute(text(f"SELECT * FROM {t} WHERE tenant_id = :d"),
                                    {"d": DUP_TENANT})).mappings().all()
            if rows:
                dump.setdefault(t, []).extend(dict(r) for r in rows)
                print(f"{t} (by tenant): {[r['id'] for r in rows]}")

        dump["tenancies"] = [dict(r) for r in (await s.execute(
            text("SELECT * FROM tenancies WHERE id = :d"), {"d": DUP_TENANCY})).mappings()]
        dump["tenants"] = [dict(r) for r in (await s.execute(
            text("SELECT * FROM tenants WHERE id = :d"), {"d": DUP_TENANT})).mappings()]

        # Refuse to run if any surviving (non-void) payment is still attached.
        live_pmts = [p["id"] for p in dump.get("payments", []) if not p["is_void"]]
        if live_pmts:
            print(f"ABORT: tenancy {DUP_TENANCY} still has non-void payments {live_pmts}")
            return

        with open(BACKUP, "w", encoding="utf-8") as fh:
            json.dump(dump, fh, default=_json, indent=2)
        print(f"\nbackup -> {BACKUP}")

        if not write:
            print("DRY RUN — nothing deleted. Re-run with --write")
            return

        for t in CHILD_TABLES:
            if t in dump:
                await s.execute(text(f"DELETE FROM {t} WHERE tenancy_id = :d"), {"d": DUP_TENANCY})
        await s.execute(text("DELETE FROM tenancies WHERE id = :d"), {"d": DUP_TENANCY})
        await s.execute(text("DELETE FROM tenants WHERE id = :d"), {"d": DUP_TENANT})
        await s.execute(text("""
            INSERT INTO audit_log (created_at, changed_by, entity_type, entity_id, entity_name,
                                   field, old_value, new_value, room_number, source, note, org_id)
            VALUES (now(), 'Kiran', 'tenancy', :d, 'Rakesh Thallapally', 'tenancy.delete',
                    'cancelled', NULL, '415', 'script',
                    'Duplicate of tenancy 901 purged after merge; rows backed up to scripts/_backup_dup_tenancy_894.json', 1)
        """), {"d": DUP_TENANCY})
        await s.commit()
        print("DELETED tenancy 894 + tenant 897 and their duplicate rows")


if __name__ == "__main__":
    asyncio.run(main("--write" in sys.argv))
