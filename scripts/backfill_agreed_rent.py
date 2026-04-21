"""
scripts/backfill_agreed_rent.py
================================
Backfill Tenancy.agreed_rent for rows where it's 0/NULL (active + no_show only).

Source of truth for correct rent: Long term tab of the Cozeevo source sheet
(sheet id 1Vr_fSIOuuKBK4MWF-FVqgAIUPbqun3POszaXYfj-Ea0), column J (index 9).

Matching: (tenant name, room_number) — case/whitespace insensitive on name.

Usage:
    python scripts/backfill_agreed_rent.py           # dry run
    python scripts/backfill_agreed_rent.py --write   # commit to DB + audit_log

Writes one audit_log entry per updated tenancy:
    source='script', field='agreed_rent', old_value='0', new_value='<new>'
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from decimal import Decimal

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

import gspread
from google.oauth2.service_account import Credentials
from sqlalchemy import select, or_

from src.database.db_manager import init_engine, get_session
from src.database.models import Tenancy, TenancyStatus, Tenant, Room
from src.services.audit import write_audit_entry


SOURCE_SHEET_ID = "1Vr_fSIOuuKBK4MWF-FVqgAIUPbqun3POszaXYfj-Ea0"
CREDENTIALS_PATH = "credentials/gsheets_service_account.json"
TAB_NAME = "Long term"
COL_ROOM = 0
COL_NAME = 1
COL_MONTHLY_RENT = 9


def _norm_name(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _norm_room(s: str) -> str:
    return (s or "").strip().upper()


def _parse_money(v) -> Decimal:
    if v is None or v == "":
        return Decimal("0")
    s = str(v).replace(",", "").replace("\u20b9", "").strip()
    try:
        return Decimal(s)
    except Exception:
        return Decimal("0")


def fetch_source_rent_map() -> dict:
    """Return {(name_norm, room_norm): monthly_rent Decimal} from Long term tab."""
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SOURCE_SHEET_ID)
    ws = sh.worksheet(TAB_NAME)
    rows = ws.get_all_values()
    mapping: dict = {}
    for r in rows[1:]:
        if len(r) <= COL_MONTHLY_RENT:
            continue
        name = _norm_name(r[COL_NAME])
        room = _norm_room(r[COL_ROOM])
        rent = _parse_money(r[COL_MONTHLY_RENT])
        if not name:
            continue
        # Prefer the first non-zero rent seen for a (name, room) pair.
        key = (name, room)
        if key not in mapping or (mapping[key] == 0 and rent > 0):
            mapping[key] = rent
        # Also index by name-only fallback (last occurrence with a non-zero rent)
        name_key = (name, "")
        if rent > 0:
            mapping[name_key] = rent
    return mapping


async def run(write: bool) -> None:
    init_engine(os.environ["DATABASE_URL"])

    print(f"Mode: {'WRITE' if write else 'DRY RUN'}")
    rent_map = fetch_source_rent_map()
    print(f"Loaded {len(rent_map)} name/room rows from source sheet '{TAB_NAME}'")

    matches = []
    unmatched = []

    async with get_session() as s:
        q = (
            select(Tenancy, Tenant, Room)
            .join(Tenant, Tenant.id == Tenancy.tenant_id)
            .join(Room, Room.id == Tenancy.room_id)
            .where(
                Tenancy.status.in_([TenancyStatus.active, TenancyStatus.no_show]),
                or_(Tenancy.agreed_rent == 0, Tenancy.agreed_rent.is_(None)),
            )
        )
        rows = (await s.execute(q)).all()
        print(f"Found {len(rows)} tenancy rows with agreed_rent = 0/NULL (active/no_show)")
        print()
        print(f"{'ID':>5}  {'Name':<25}  {'Room':<8}  {'Sharing':<10}  {'Checkin':<12}  {'Source rent':>12}")
        print("-" * 90)

        for ten, tn, rm in rows:
            name_n = _norm_name(tn.name)
            room_n = _norm_room(rm.room_number)
            rent = rent_map.get((name_n, room_n)) or rent_map.get((name_n, ""))
            sharing = ten.sharing_type.value if ten.sharing_type else ""
            checkin = str(ten.checkin_date) if ten.checkin_date else ""
            rent_display = str(rent) if rent is not None else "NOT FOUND"
            print(f"{ten.id:>5}  {tn.name:<25.25}  {rm.room_number:<8}  {sharing:<10}  {checkin:<12}  {rent_display:>12}")
            if rent and rent > 0:
                matches.append((ten, tn, rm, rent))
            else:
                unmatched.append((ten, tn, rm))

        print()
        print(f"Matched with rent: {len(matches)}   Unmatched: {len(unmatched)}")

        if write:
            updated = 0
            for ten, tn, rm, rent in matches:
                old = str(ten.agreed_rent or 0)
                ten.agreed_rent = rent
                await write_audit_entry(
                    session=s,
                    changed_by="system",
                    entity_type="tenancy",
                    entity_id=ten.id,
                    entity_name=tn.name,
                    room_number=rm.room_number,
                    field="agreed_rent",
                    old_value=old,
                    new_value=str(rent),
                    source="script",
                    note="backfill_agreed_rent.py — from Long term sheet col J",
                )
                updated += 1
            print(f"WROTE {updated} tenancy rows + {updated} audit_log entries.")
        else:
            print("Dry run — no writes. Re-run with --write to apply.")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--write", action="store_true", help="commit changes (default: dry run)")
    args = p.parse_args()
    asyncio.run(run(args.write))
