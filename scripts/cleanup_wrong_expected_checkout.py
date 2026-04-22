"""Clean up tenants where the source-sync wrongly stamped a lock-in
end-date as expected_checkout + notice_date.

Pattern: notes contain "lockin until …" and notice_date == today
(the auto-set value when the importer ran). Real exit-intent notes say
"exit on …", "checkout …", or "leaving …" — those stay untouched.

Action per matching row:
  - lock_in_months  ← inferred from notes (default 2 if "2 month" / "@ month")
  - expected_checkout ← None
  - notice_date     ← None

Run:  venv/Scripts/python scripts/cleanup_wrong_expected_checkout.py --write
"""
import argparse
import asyncio
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import select
from src.database.db_manager import init_engine, get_session
from src.database.models import Tenancy, Tenant, Room, TenancyStatus


# `@` was a corruption of `2` in the source spreadsheet (some non-Latin
# digit got mangled during paste). No `\b` before `@` because `@` is not
# a word char — `\b` would never match.
LOCKIN_PAT = re.compile(r"(?:^|\s)(\d|@)\s*months?\s+lock(?:in|-in)?\b", re.I)
EXIT_PAT = re.compile(r"\b(?:exit|checkout|check\s*out|leaving|leave\s+on|vacat)\b", re.I)


async def main(write: bool):
    init_engine(os.environ["DATABASE_URL"])
    async with get_session() as s:
        rows = (await s.execute(
            select(Tenancy).where(
                Tenancy.status == TenancyStatus.active,
                Tenancy.expected_checkout.isnot(None),
            )
        )).scalars().all()
        print(f"Active tenancies with expected_checkout: {len(rows)}\n")

        cleaned = kept = 0
        for t in rows:
            notes = (t.notes or "")
            is_lockin = bool(LOCKIN_PAT.search(notes))
            has_exit = bool(EXIT_PAT.search(notes))
            if not is_lockin or has_exit:
                kept += 1
                continue

            tn = await s.get(Tenant, t.tenant_id)
            rm = await s.get(Room, t.room_id)

            # Try to read the lock-in months from the notes; "@" was a corruption
            # of "2" in the source spreadsheet, so treat it as 2.
            m = LOCKIN_PAT.search(notes)
            raw = m.group(1) if m else "2"
            lock_months = 2 if raw == "@" else int(raw)

            print(f"  [{t.id}] {tn.name:<28} room={rm.room_number}")
            print(f"     was: exp={t.expected_checkout} notice={t.notice_date} lockin={t.lock_in_months}")
            print(f"     now: exp=None notice=None lockin={lock_months}")
            if write:
                t.expected_checkout = None
                t.notice_date = None
                t.lock_in_months = lock_months
            cleaned += 1

        if write:
            await s.commit()
        print(f"\nCleaned: {cleaned}  Kept (real exits or no lockin): {kept}")
        if not write:
            print("[DRY RUN]")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    asyncio.run(main(ap.parse_args().write))
