"""Read April Month Collection 'Long term' tab and parse the 'April Balance'
column (col X / index 23) for planned exit/move-out dates, then persist to
`Tenancy.expected_checkout` + `Tenancy.notice_date`.

The column is free text — it mixes numeric dues ("1500", "6500") with phrases
like "exit on april 30th", "exit may 30th", "exit on 26 th april",
"exit on april 30/31st" (→ earliest day).

Ambiguous year is fixed at 2026.
"""
import asyncio
import os
import re
import sys
from datetime import date

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

import gspread
from google.oauth2.service_account import Credentials

from sqlalchemy import select
from src.database.db_manager import init_engine, get_session
from src.database.models import Tenant, Tenancy, TenancyStatus


SOURCE_SHEET_ID = "1Vr_fSIOuuKBK4MWF-FVqgAIUPbqun3POszaXYfj-Ea0"
CREDENTIALS_PATH = "credentials/gsheets_service_account.json"
YEAR = 2026

COL = {"name": 1, "phone": 3, "inout": 16, "balance": 23}

MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "april": 4, "may": 5,
    "jun": 6, "june": 6, "jul": 7, "july": 7, "aug": 8, "sep": 9,
    "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}


def norm_phone(raw: str) -> str:
    d = re.sub(r"\D", "", str(raw or ""))
    if d.startswith("91") and len(d) == 12:
        d = d[2:]
    return f"+91{d}" if len(d) == 10 else ""


def parse_exit_date(text: str) -> date | None:
    """Return the earliest parseable exit date from a free-text cell, or None.

    Handles: 'exit on april 30th', 'exit may 30th', 'exit on 26 th april',
    'exit on april 30/31st' (picks 30), 'exit on 30/31st april'.
    Ignores cells without exit/leave/move/vacat keywords.
    """
    if not text:
        return None
    t = text.lower().strip()
    if not any(k in t for k in ("exit", "leave", "leaving", "move out", "moveout", "vacat")):
        return None

    # "april 30/31st" / "april 30 / 31"  → earliest day
    m = re.search(
        r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(\d{1,2})\s*(?:/|or|,)\s*(\d{1,2})",
        t,
    )
    if m:
        mon = MONTH_MAP[m.group(1)]
        day = min(int(m.group(2)), int(m.group(3)))
        try:
            return date(YEAR, mon, day)
        except ValueError:
            pass

    # month day — e.g. "april 30th", "may 23rd"
    m = re.search(
        r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(\d{1,2})",
        t,
    )
    if m:
        mon = MONTH_MAP[m.group(1)]
        day = int(m.group(2))
        try:
            return date(YEAR, mon, day)
        except ValueError:
            pass

    # day (th|st|nd|rd)? month — e.g. "26 th april", "30th april"
    m = re.search(
        r"(\d{1,2})\s*(?:th|st|nd|rd)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)",
        t,
    )
    if m:
        day = int(m.group(1))
        mon = MONTH_MAP[m.group(2)]
        try:
            return date(YEAR, mon, day)
        except ValueError:
            pass

    return None


async def main():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=scopes)
    ws = gspread.authorize(creds).open_by_key(SOURCE_SHEET_ID).worksheet("Long term")
    data = ws.get_all_values()
    print(f"Fetched {len(data)} rows from source")

    init_engine(os.environ["DATABASE_URL"])
    async with get_session() as s:
        tenant_rows = (await s.execute(select(Tenant))).scalars().all()
        # Index tenants by normalized phone (many DB phones are +91, a few are raw).
        by_phone: dict[str, list[Tenant]] = {}
        for t in tenant_rows:
            np = norm_phone(t.phone)
            if np:
                by_phone.setdefault(np, []).append(t)

        set_count = 0
        skipped_no_match = 0
        for row in data[1:]:
            if len(row) < 24 or not row[COL["name"]].strip():
                continue
            if row[COL["inout"]].strip().upper() != "CHECKIN":
                continue
            phone = norm_phone(row[COL["phone"]])
            if not phone:
                continue
            # April Balance column is the ONLY source for planned exits.
            # Comments often mention "may 1st" for rent changes or "vacation from"
            # for short trips — those are false positives.
            bal_text = row[COL["balance"]].strip() if len(row) > COL["balance"] else ""
            exit_d = parse_exit_date(bal_text)
            if not exit_d:
                continue

            name = row[COL["name"]].strip().title()
            cands = by_phone.get(phone, [])
            tenant = None
            for c in cands:
                if c.name.lower().strip() == name.lower().strip():
                    tenant = c
                    break
            if not tenant and cands:
                tenant = cands[0]  # phone unique enough
            if not tenant:
                skipped_no_match += 1
                continue

            tenancy = (await s.execute(
                select(Tenancy)
                .where(Tenancy.tenant_id == tenant.id,
                       Tenancy.status == TenancyStatus.active)
                .order_by(Tenancy.id.desc())
            )).scalar()
            if not tenancy:
                continue

            changed = False
            if tenancy.expected_checkout != exit_d:
                tenancy.expected_checkout = exit_d
                changed = True
            if not tenancy.notice_date:
                tenancy.notice_date = date(2026, 4, 23)
                changed = True
            if changed:
                set_count += 1
                print(f"  {name} (tid={tenancy.id}) → expected_checkout={exit_d}  src={bal_text!r}")

        await s.commit()
        print(f"\nUpdated {set_count} tenancies with planned exits.  Unmatched: {skipped_no_match}")


if __name__ == "__main__":
    asyncio.run(main())
