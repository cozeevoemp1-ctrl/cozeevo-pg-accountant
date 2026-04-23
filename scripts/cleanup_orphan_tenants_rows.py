"""
scripts/cleanup_orphan_tenants_rows.py
======================================
One-shot cleanup for orphan rows in the TENANTS master tab — rows whose
tenant has no active tenancy AND no active day-wise stay in the DB.

These appear when:
  - An onboarding form completed Sheet write but the DB tenancy creation
    later failed / was rolled back.
  - The WhatsApp ADD_TENANT confirm path created a Tenancy + Sheet row
    but the Tenancy was later deleted manually (DB drift).
  - A booking was rejected late but the Sheet row was already pushed.

Action per orphan row:
  - Mark `Status` cell to `INACTIVE`
  - Clear `Room`, `Agreed Rent`, `Deposit`, `Booking`, `Maintenance`
    (so the row no longer claims to occupy a bed)
  - Append a note: `orphan-cleanup YYYY-MM-DD`

Idempotent. Safe to re-run. Default is dry-run; pass --write to apply.

Usage:
    venv/Scripts/python scripts/cleanup_orphan_tenants_rows.py           # dry
    venv/Scripts/python scripts/cleanup_orphan_tenants_rows.py --write   # apply
    venv/Scripts/python scripts/cleanup_orphan_tenants_rows.py --write --only "Pranav Sonawane"
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import select
from src.database.db_manager import init_db, get_session
from src.database.models import Tenant, Tenancy, TenancyStatus
from src.integrations.gsheets import _get_worksheet_sync


def _normalize_phone(s: str) -> str:
    digits = "".join(c for c in (s or "") if c.isdigit())
    if len(digits) >= 10:
        return digits[-10:]
    return digits


async def _orphan_rows(only: str | None) -> list[dict]:
    """Read TENANTS tab, return rows that have no DB-backing (no active
    Tenancy AND no active DaywiseStay matching by phone or by name+room)."""
    ws = _get_worksheet_sync("TENANTS")
    all_values = ws.get_all_values()
    if not all_values:
        return []

    headers = [h.strip().lower() for h in all_values[0]]

    def col(name_lower: str) -> int:
        try:
            return headers.index(name_lower)
        except ValueError:
            return -1

    idx_room = col("room")
    idx_name = col("name")
    idx_phone = col("phone")
    idx_status = col("status")

    orphans: list[dict] = []
    async with get_session() as s:
        for ri, row in enumerate(all_values[1:], start=2):
            name = (row[idx_name] if idx_name >= 0 and idx_name < len(row) else "").strip()
            room = (row[idx_room] if idx_room >= 0 and idx_room < len(row) else "").strip()
            phone_raw = (row[idx_phone] if idx_phone >= 0 and idx_phone < len(row) else "").strip()
            status = (row[idx_status] if idx_status >= 0 and idx_status < len(row) else "").strip()

            if not name and not phone_raw:
                continue
            # Only target rows that CLAIM to be active. Anything already
            # marked Exited/Inactive/etc. is historical and must not be
            # erased (preserves room/rent for past stays).
            if status.upper() not in ("ACTIVE", "", "PENDING"):
                continue
            if only and only.lower() not in name.lower():
                continue

            phone = _normalize_phone(phone_raw)

            # Try to find any active tenancy for this person. Phone formats
            # vary across DB (`+919878817607`) and Sheet (`919878817607` or
            # `9878817607`); compare by the canonical last-10 digits to avoid
            # false-orphan flags like Jeewan-in-305.
            t_q = select(Tenancy).join(Tenant, Tenant.id == Tenancy.tenant_id).where(
                Tenancy.status == TenancyStatus.active,
            )
            if phone and len(phone) == 10:
                t_q = t_q.where(Tenant.phone.ilike(f"%{phone}"))
            elif name:
                t_q = t_q.where(Tenant.name.ilike(name))
            else:
                # No phone, no name → can't decide — skip rather than nuke.
                continue
            has_tenancy = (await s.execute(t_q.limit(1))).scalars().first() is not None

            # The TENANTS tab is the master for *monthly* tenants. A row is an
            # orphan whenever there is no matching active monthly Tenancy.
            # (Day-wise stays live in the DAY WISE tab — they don't belong
            # in TENANTS even if the person exists in DaywiseStay today.)
            if not has_tenancy:
                orphans.append({
                    "row": ri, "name": name, "phone": phone_raw,
                    "room": room, "status": status,
                })

    return orphans


def _apply_cleanup(orphans: list[dict]) -> None:
    """Apply the cleanup: clear Room/Agreed Rent/Deposit/Booking/Maintenance,
    set Status=INACTIVE, append a note. One Sheet update batch per row."""
    ws = _get_worksheet_sync("TENANTS")
    headers = [h.strip().lower() for h in ws.row_values(1)]

    def col(name_lower: str) -> int:
        try:
            return headers.index(name_lower)
        except ValueError:
            return -1

    targets = {
        "room": "",
        "agreed rent": "",
        "deposit": "",
        "booking": "",
        "maintenance": "",
        "status": "INACTIVE",
    }
    notes_idx = col("notes")
    today_iso = date.today().isoformat()

    for orphan in orphans:
        ri = orphan["row"]
        updates = []
        for hkey, val in targets.items():
            ci = col(hkey)
            if ci >= 0:
                a1 = gspread_a1(ri, ci + 1)
                updates.append({"range": a1, "values": [[val]]})
        if notes_idx >= 0:
            existing = ws.cell(ri, notes_idx + 1).value or ""
            note_msg = f"orphan-cleanup {today_iso}"
            new_note = (existing + " | " + note_msg).strip(" |") if existing else note_msg
            updates.append({"range": gspread_a1(ri, notes_idx + 1), "values": [[new_note]]})
        if updates:
            ws.batch_update(updates, value_input_option="USER_ENTERED")
            print(f"  [write] row {ri} {orphan['name']} (room {orphan['room']}) -> INACTIVE")


def gspread_a1(row: int, col: int) -> str:
    """1-indexed (row, col) -> A1 like 'C5'. Handles >Z columns."""
    letters = ""
    n = col
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return f"{letters}{row}"


async def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--write", action="store_true", help="Apply changes (default: dry-run)")
    p.add_argument("--only", type=str, default=None, help="Substring filter on name (e.g. 'Pranav')")
    args = p.parse_args()

    await init_db(os.getenv("DATABASE_URL"))

    print(f"[mode] {'WRITE' if args.write else 'DRY-RUN'}"
          + (f" | filter='{args.only}'" if args.only else ""))
    orphans = await _orphan_rows(args.only)
    print(f"[found] {len(orphans)} orphan rows in TENANTS tab")
    for o in orphans:
        print(f"  row {o['row']}: {o['name']!r} room={o['room']!r} phone={o['phone']!r} status={o['status']!r}")

    if not orphans:
        print("nothing to do.")
        return 0

    if not args.write:
        print("\n(dry-run) re-run with --write to apply.")
        return 0

    _apply_cleanup(orphans)
    print(f"\n[done] cleaned {len(orphans)} row(s).")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
