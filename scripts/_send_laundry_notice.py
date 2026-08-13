"""One-off: send laundry_rules_notice (approved, 0 params) to all active tenants.

Manual broadcast — triggered directly by Kiran, 2026-08-08. Not scheduled,
not repeatable via cron. See memory/rules_whatsapp_cc.md — CC's a one-line
summary to operators (Lokesh, Lakshmi, Kiran, Prabhakaran) after the run.

    python scripts/_send_laundry_notice.py            # dry run (default)
    python scripts/_send_laundry_notice.py --send      # actually sends
"""
from __future__ import annotations

import asyncio
import os
import sys

from dotenv import load_dotenv
from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from src.database.db_manager import get_session, init_engine  # noqa: E402
from src.whatsapp.reminder_sender import send_template  # noqa: E402

TEMPLATE = "laundry_rules_notice"
LANGUAGE = "en_US"  # Meta normalized this template to en_US on approval, not en

OPERATORS = [
    ("Lokesh", "7680814628"),
    ("Lakshmi Mam", "7358341775"),
    ("Kiran", "7845952289"),
    ("Prabhakaran", "9444296681"),
]

ACTIVE_TENANTS_SQL = """
    SELECT te.id AS tenant_id, te.name, te.phone
    FROM tenancies t
    JOIN tenants te ON te.id = t.tenant_id
    WHERE t.status = 'active' AND te.phone IS NOT NULL AND te.phone != ''
    ORDER BY te.name
"""


async def main() -> None:
    dry_run = "--send" not in sys.argv
    init_engine(os.environ["DATABASE_URL"])

    async with get_session() as session:
        rows = (await session.execute(text(ACTIVE_TENANTS_SQL))).fetchall()

    print(f"Template: {TEMPLATE}")
    print(f"Recipients: {len(rows)} active tenants")
    print(f"Mode: {'DRY RUN (no messages sent)' if dry_run else 'LIVE SEND'}")
    print()

    if dry_run:
        for r in rows[:10]:
            print(f"  would send -> {r.name} ({r.phone})")
        if len(rows) > 10:
            print(f"  ... and {len(rows) - 10} more")
        print("\nRe-run with --send to actually send.")
        return

    # Operator CC FIRST — TIER_250 cap (250 unique conversations/24h) silently
    # drops whoever sits past position 250; staff must never be at the end.
    # Same reliable template path as tenants (free-form text silently drops
    # outside the 24h session window; templates don't have that problem).
    cc_sent = 0
    for name, phone in OPERATORS:
        ok = await send_template(phone, TEMPLATE, language_code=LANGUAGE)
        if ok:
            cc_sent += 1
        else:
            print(f"  CC FAILED -> {name} ({phone})")
        await asyncio.sleep(0.3)
    print(f"CC sent to {cc_sent}/{len(OPERATORS)} operators.\n")

    sent, failed = 0, []
    for r in rows:
        ok = await send_template(r.phone, TEMPLATE, language_code=LANGUAGE)
        if ok:
            sent += 1
        else:
            failed.append((r.name, r.phone))
        await asyncio.sleep(0.3)  # gentle pacing, avoid rate-limit bursts

    print(f"Sent: {sent}/{len(rows)}")
    if failed:
        print(f"Failed ({len(failed)}):")
        for name, phone in failed:
            print(f"  {name} ({phone})")


if __name__ == "__main__":
    asyncio.run(main())
