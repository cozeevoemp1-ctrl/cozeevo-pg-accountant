"""
scripts/import_notice_dates.py
===============================
One-off: read "exit on <date>" text from the April Month Collection
Google Sheet (SOURCE_SHEET_ID, column X = April Balance) and backfill
tenancy.expected_checkout (and tenancy.notice_date if not set) in DB.

Also calls gsheets.record_notice() so the Cozeevo Operations v2 sheet
gets the notice date + expected exit columns filled in too.

Usage:
    python scripts/import_notice_dates.py           # dry run — shows what would change
    python scripts/import_notice_dates.py --write   # commit to DB + update ops sheet
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()

import gspread
from google.oauth2.service_account import Credentials

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from src.database.models import Tenancy, Tenant, Room, TenancyStatus

DATABASE_URL = os.environ["DATABASE_URL"]
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

SOURCE_SHEET_ID  = os.environ["SOURCE_SHEET_ID"]
CREDENTIALS_PATH = os.path.join(
    Path(__file__).parent.parent, "credentials", "gsheets_service_account.json"
)

# April Month Collection column indices (1-based, as in the sheet)
COL_ROOM    = 1   # A
COL_NAME    = 2   # B
COL_BALANCE = 24  # X — "April Balance", contains "exit on april 30th" etc.

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

# Patterns:  "exit on april 30th"  /  "exit on april 30/31"  /  "exit may 23rd"
_EXIT_RE = re.compile(
    r"exit(?:\s+on)?\s+"
    r"(?P<month>jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*"
    r"\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?(?:/\d+)?",
    re.I,
)


def _parse_exit_date(text: str) -> date | None:
    """Return the exit date parsed from a balance-column note, or None."""
    m = _EXIT_RE.search(str(text))
    if not m:
        return None
    month = MONTHS.get(m.group("month")[:3].lower())
    day   = int(m.group("day"))
    if not month:
        return None
    year = 2026  # all entries in this sheet are April 2026
    # If the exit month has already passed relative to today, push to 2027 — shouldn't
    # happen for April 2026 data, but be safe.
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _normalize_name(s: str) -> str:
    return " ".join(s.strip().lower().split())


def _normalize_room(s: str) -> str:
    return str(s).strip().upper().lstrip("0") if s else ""


def _open_source_sheet():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=scopes)
    gc    = gspread.authorize(creds)
    return gc.open_by_key(SOURCE_SHEET_ID)


async def main(write: bool):
    print("=== Import notice dates from April Month Collection ===\n")

    # ── 1. Read source sheet ────────────────────────────────────────────────
    print("Reading April Month Collection sheet …")
    ss   = _open_source_sheet()
    ws   = ss.sheet1  # first tab = April Month Collection
    rows = ws.get_all_values()
    print(f"  {len(rows)} rows total")

    # Skip header row (row 1 in sheet = index 0 in list)
    header = rows[0] if rows else []
    data   = rows[1:]

    # Build lookup: (room, name) -> exit_date from the sheet
    sheet_exits: list[dict] = []
    for i, row in enumerate(data, start=2):  # start=2 = sheet row number
        room_raw    = row[COL_ROOM - 1]    if len(row) >= COL_ROOM    else ""
        name_raw    = row[COL_NAME - 1]    if len(row) >= COL_NAME    else ""
        balance_raw = row[COL_BALANCE - 1] if len(row) >= COL_BALANCE else ""

        if not name_raw.strip():
            continue

        exit_date = _parse_exit_date(balance_raw)
        if not exit_date:
            continue

        sheet_exits.append({
            "row":        i,
            "room":       _normalize_room(room_raw),
            "name":       _normalize_name(name_raw),
            "name_raw":   name_raw.strip(),
            "exit_date":  exit_date,
            "balance_raw": balance_raw.strip(),
        })

    print(f"  Parsed {len(sheet_exits)} rows with 'exit on …' text\n")

    # ── 2. Load all active tenancies from DB ───────────────────────────────
    engine  = create_async_engine(DATABASE_URL, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as session:
        db_rows = (await session.execute(
            select(Tenancy, Tenant, Room)
            .join(Tenant, Tenant.id == Tenancy.tenant_id)
            .join(Room, Room.id == Tenancy.room_id)
            .where(Tenancy.status.in_([TenancyStatus.active, TenancyStatus.no_show]))
        )).all()

        # Build lookup: room -> list[(tenancy, tenant, room_obj)]
        by_room: dict[str, list] = {}
        by_name: dict[str, list] = {}
        for tenancy, tenant, room_obj in db_rows:
            rkey = _normalize_room(room_obj.room_number)
            nkey = _normalize_name(tenant.name)
            by_room.setdefault(rkey, []).append((tenancy, tenant, room_obj))
            by_name.setdefault(nkey, []).append((tenancy, tenant, room_obj))

        # ── 3. Match and update ────────────────────────────────────────────
        updated   = []
        skipped   = []
        not_found = []

        for entry in sheet_exits:
            room      = entry["room"]
            name      = entry["name"]
            exit_date = entry["exit_date"]

            # Try room match first (most reliable), then name match
            candidates = by_room.get(room, [])
            if not candidates:
                candidates = by_name.get(name, [])

            if not candidates:
                not_found.append(entry)
                continue

            # If multiple tenants in same room, prefer name match
            match = None
            if len(candidates) == 1:
                match = candidates[0]
            else:
                for c in candidates:
                    if _normalize_name(c[1].name) == name:
                        match = c
                        break
                if not match:
                    match = candidates[0]  # best guess

            tenancy, tenant, room_obj = match

            already_set = tenancy.expected_checkout is not None
            if already_set and tenancy.expected_checkout == exit_date:
                skipped.append({**entry, "reason": "already correct"})
                continue

            print(
                f"  {'UPDATE' if write else 'DRY-RUN'}: {tenant.name} (Room {room_obj.room_number})"
                f"  exit {exit_date.strftime('%d %b %Y')}"
                + (f"  [was: {tenancy.expected_checkout}]" if already_set else "  [new]")
            )

            if write:
                tenancy.expected_checkout = exit_date
                # Set notice_date to April 1 if not already set (we know they gave notice in April)
                if not tenancy.notice_date:
                    tenancy.notice_date = date(2026, 4, 1)

            updated.append({**entry, "tenant": tenant.name, "room_obj": room_obj})

        if write:
            await session.commit()
            print(f"\nCommitted {len(updated)} updates to DB.")

        # ── 4. Update Cozeevo Operations v2 sheet ─────────────────────────
        if write and updated:
            from src.integrations.gsheets import record_notice
            print("\nUpdating Cozeevo Operations v2 …")
            for entry in updated:
                tenant_name = entry["tenant"]
                room_number = entry["room_obj"].room_number
                exit_date   = entry["exit_date"]
                notice_date = date(2026, 4, 1)  # assumed April 1
                try:
                    result = await record_notice(
                        room_number,
                        tenant_name,
                        notice_date.strftime("%d/%m/%Y"),
                        exit_date.strftime("%d/%m/%Y"),
                    )
                    status = "ok" if result.get("success") else f"warn: {result}"
                except Exception as e:
                    status = f"error: {e}"
                print(f"  Sheet {tenant_name} ({room_number}) → {status}")

        # ── 5. Summary ─────────────────────────────────────────────────────
        print(f"\n{'='*50}")
        print(f"Parsed from sheet : {len(sheet_exits)}")
        print(f"{'Updated' if write else 'Would update'}: {len(updated)}")
        print(f"Already correct   : {sum(1 for s in skipped if s['reason'] == 'already correct')}")
        print(f"Not found in DB   : {len(not_found)}")

        if not_found:
            print("\nNot found in DB (check name/room):")
            for e in not_found:
                print(f"  Row {e['row']:3d}: Room={e['room']!r:6s} Name={e['name_raw']!r} → exit {e['exit_date']}")

        if not write:
            print("\nRun with --write to apply changes.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="Commit changes to DB and Sheet")
    args = parser.parse_args()
    asyncio.run(main(args.write))
