"""
Fix April RentSchedule to use source sheet data exactly (no auto-calculation).

Filter: People with April balance ≠ 0 AND check-in date < May 1.

Steps:
1. Query source sheet for matching rows
2. Delete all current April RentSchedule from DB
3. Create new April RentSchedule for filtered rows only, using source balance
4. Verify total matches 140299 (user's verified source number)

Usage:
    python scripts/fix_april_rentschedule.py          # dry run
    python scripts/fix_april_rentschedule.py --write  # commit to DB
"""
import asyncio
import os
import re
import sys
from datetime import date
from decimal import Decimal

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

import gspread
from google.oauth2.service_account import Credentials

from sqlalchemy import select
from src.database.db_manager import init_engine, get_session
from src.database.models import (
    Tenant, Tenancy, Room, RentSchedule,
    TenancyStatus, RentStatus,
)

SOURCE_SHEET_ID = "1Vr_fSIOuuKBK4MWF-FVqgAIUPbqun3POszaXYfj-Ea0"
CREDENTIALS_PATH = "credentials/gsheets_service_account.json"

APRIL = date(2026, 4, 1)

# Column indices (0-based) — matches April Month Collection schema
COL = {
    "room": 0, "name": 1, "phone": 3, "checkin": 4,
    "inout": 16, "apr_balance": 23,
}


def pn(val):
    """Parse numeric — empty/text → 0.0, number/numeric-string → float."""
    if val is None or val == "":
        return 0.0
    s = str(val).replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


def norm_phone(raw):
    d = re.sub(r"\D", "", str(raw or ""))
    if d.startswith("91") and len(d) == 12:
        d = d[2:]
    return f"+91{d}" if len(d) == 10 else ""


def parse_checkin(raw):
    if not raw:
        return None
    from datetime import datetime as _dt
    if isinstance(raw, _dt):
        return raw.date()
    s = str(raw).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y"):
        try:
            return _dt.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


async def fetch_sheet():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SOURCE_SHEET_ID)
    ws = sh.worksheet("Long term")
    data = ws.get_all_values()
    return data


async def main(write: bool):
    print(f"Mode: {'WRITE' if write else 'DRY RUN'}")
    print(f"Source: Google Sheet {SOURCE_SHEET_ID}")

    rows = await fetch_sheet()
    print(f"Fetched {len(rows)} rows from Long term tab\n")

    # Filter rows: inout in (CHECKIN, NO SHOW) AND checkin < May 1 AND april_balance != 0
    filtered_rows = []
    for ri, row in enumerate(rows[1:], start=2):
        if len(row) < 24 or not row[COL["name"]].strip():
            continue

        inout = row[COL["inout"]].strip().upper()
        if inout not in ("CHECKIN", "NO SHOW"):
            continue

        checkin = parse_checkin(row[COL["checkin"]])
        if not checkin or checkin >= date(2026, 5, 1):
            continue

        april_balance = pn(row[COL["apr_balance"]])
        if april_balance == 0:
            continue

        filtered_rows.append({
            "row_num": ri,
            "name": row[COL["name"]].strip(),
            "phone": norm_phone(row[COL["phone"]]),
            "checkin": checkin,
            "inout": inout,
            "april_balance": Decimal(str(april_balance)),
        })

    print(f"Filtered: {len(filtered_rows)} rows with april_balance != 0 and checkin < 2026-05-01")
    print(f"Expected total: Rs.{sum(r['april_balance'] for r in filtered_rows):,.0f}\n")

    # Show sample
    for row in filtered_rows[:5]:
        print(f"  {row['name']:25s} | Phone: {row['phone']} | Balance: Rs.{row['april_balance']:,.0f}")
    if len(filtered_rows) > 5:
        print(f"  ... and {len(filtered_rows) - 5} more")
    print()

    init_engine(os.getenv("DATABASE_URL"))
    async with get_session() as s:
        # Index tenants + tenancies
        tenant_rows = (await s.execute(select(Tenant))).scalars().all()
        tenant_map = {}
        for t in tenant_rows:
            tenant_map[(t.phone, t.name.lower().strip())] = t

        tenancy_rows = (await s.execute(select(Tenancy))).scalars().all()
        tenancy_map = {}
        for t in tenancy_rows:
            if t.tenant_id in [x.id for x in tenant_rows]:
                key = (next((tn.phone for tn in tenant_rows if tn.id == t.tenant_id), None),
                       next((tn.name.lower().strip() for tn in tenant_rows if tn.id == t.tenant_id), None))
                tenancy_map[key] = t

        print(f"DB: {len(tenant_rows)} tenants, {len(tenancy_rows)} tenancies\n")

        # Delete all April RentSchedule first
        old_rs = (await s.execute(
            select(RentSchedule).where(RentSchedule.period_month == APRIL)
        )).scalars().all()

        if not write:
            print(f"Would delete {len(old_rs)} old April RentSchedule rows (total: Rs.{sum(r.rent_due for r in old_rs):,.0f})\n")
        else:
            for r in old_rs:
                await s.delete(r)
            await s.flush()
            print(f"Deleted {len(old_rs)} old April RentSchedule rows\n")

        # Create new April RentSchedule from filtered rows
        created = 0
        matched = 0
        no_match = []
        total_balance = Decimal("0")

        for row_data in filtered_rows:
            key = (row_data["phone"], row_data["name"].lower().strip())
            tenant = tenant_map.get(key)
            if not tenant:
                no_match.append(row_data["name"])
                continue

            # Get latest tenancy for this tenant
            tenancy = next((t for t in tenancy_rows if t.tenant_id == tenant.id), None)
            if not tenancy:
                no_match.append(row_data["name"])
                continue

            matched += 1
            total_balance += row_data["april_balance"]

            if write:
                # Create April RentSchedule with source balance as rent_due
                s.add(RentSchedule(
                    tenancy_id=tenancy.id,
                    period_month=APRIL,
                    rent_due=row_data["april_balance"],
                    maintenance_due=Decimal("0"),
                    status=RentStatus.pending,
                    due_date=APRIL,
                ))
                created += 1

        if write:
            await s.flush()
            print(f"Created {created} new April RentSchedule rows")
        else:
            print(f"Would create {len(filtered_rows)} new April RentSchedule rows")

        print(f"Matched {matched}/{len(filtered_rows)} filtered rows to DB tenancies")
        print(f"Total April dues: Rs.{total_balance:,.0f}")
        print(f"Expected:         Rs.140299")
        print(f"Match: {'✓' if abs(float(total_balance) - 140299) < 1 else '✗'}")

        if no_match:
            print(f"\nNot found in DB ({len(no_match)}):")
            for name in no_match[:10]:
                print(f"  - {name}")
            if len(no_match) > 10:
                print(f"  ... and {len(no_match) - 10} more")

        if not write:
            print(f"\nDry run complete. Run with --write to apply changes.")


if __name__ == "__main__":
    write = "--write" in sys.argv
    asyncio.run(main(write))
