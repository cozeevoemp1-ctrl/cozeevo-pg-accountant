"""Sync Notice Date / Expected Exit / Checkout Date / Status columns on
TENANTS tab from DB, in a single batch_update. Much faster than running
normalize_tenants_tab.py which sends one API call per tenant.

Why this exists: setting Tenancy.expected_checkout / notice_date in the DB
does not automatically propagate to the TENANTS master tab. The existing
`sync_tenant_all_fields` helper fixes it per-tenant, but for a bulk
refresh (like after reloading an entire month), one batch is far faster.
"""
import asyncio
import os
import sys
from datetime import date

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import select
from src.database.db_manager import init_engine, get_session
from src.database.models import Tenancy, Tenant, Room, TenancyStatus


def _d(d):
    return d.strftime("%d/%m/%Y") if d else ""


async def main():
    init_engine(os.environ["DATABASE_URL"])

    from src.integrations.gsheets import (
        _get_worksheet_sync, _build_header_map, TENANTS_HEADERS,
    )
    import gspread.utils as gsu

    ws = _get_worksheet_sync("TENANTS")
    sheet_vals = ws.get_all_values()
    if not sheet_vals:
        print("TENANTS tab empty — nothing to do")
        return

    # Header row is row 0 (canonical format); build column-name -> index map
    hdr_map = _build_header_map(sheet_vals[0])
    required = ("room", "name", "notice date", "expected exit", "checkout date", "status")
    missing = [c for c in required if c not in hdr_map]
    if missing:
        print(f"ERROR: TENANTS tab missing columns: {missing}")
        return

    col_room = hdr_map["room"]
    col_name = hdr_map["name"]
    col_notice = hdr_map["notice date"]
    col_exp = hdr_map["expected exit"]
    col_cout = hdr_map["checkout date"]
    col_status = hdr_map["status"]

    # Build DB view keyed by (room_number, name_lower)
    async with get_session() as s:
        rows = (await s.execute(
            select(Tenancy, Tenant, Room)
            .join(Tenant, Tenant.id == Tenancy.tenant_id)
            .join(Room, Room.id == Tenancy.room_id)
        )).all()

    db_by_key = {}
    for t, ten, r in rows:
        key = (str(r.room_number).strip(), ten.name.strip().lower())
        # Prefer active over exited when duplicates
        prev = db_by_key.get(key)
        if prev and prev[0].status == TenancyStatus.active and t.status != TenancyStatus.active:
            continue
        db_by_key[key] = (t, ten, r)

    updates = []  # [{range: "N5", values: [[val]]}, ...]
    matched = 0
    skipped = 0

    for ri, row in enumerate(sheet_vals[1:], start=2):  # 1-indexed, skip header
        if len(row) <= max(col_room, col_name):
            continue
        sheet_room = str(row[col_room]).strip()
        sheet_name = str(row[col_name]).strip().lower()
        if not sheet_room or not sheet_name:
            continue
        rec = db_by_key.get((sheet_room, sheet_name))
        if not rec:
            skipped += 1
            continue
        t, ten, rm = rec
        matched += 1

        # Desired values
        desired = {
            col_notice: _d(t.notice_date),
            col_exp: _d(t.expected_checkout),
            col_cout: _d(t.checkout_date),
            col_status: t.status.value.upper() if t.status else "",
        }
        for col_idx, val in desired.items():
            cur = row[col_idx].strip() if col_idx < len(row) else ""
            if cur != val:
                a1 = gsu.rowcol_to_a1(ri, col_idx + 1)
                updates.append({"range": a1, "values": [[val]]})

    print(f"TENANTS: matched {matched} rows, skipped {skipped}, {len(updates)} cells to update")
    if not updates:
        print("Already in sync — nothing to write")
        return

    # Send in chunks to stay under per-request payload limits
    CHUNK = 200
    for i in range(0, len(updates), CHUNK):
        chunk = updates[i:i + CHUNK]
        ws.batch_update(chunk, value_input_option="USER_ENTERED")
        print(f"  wrote cells {i + 1}..{i + len(chunk)}")

    print("Done")


if __name__ == "__main__":
    asyncio.run(main())
