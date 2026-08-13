# -*- coding: utf-8 -*-
"""One-off: send the bike parking notice via custom_broadcast_notice.

Manual broadcast — triggered directly by Kiran, 2026-08-13. Not scheduled.
See memory/rules_whatsapp_cc.md — operators always CC'd in the same run.

    python scripts/_send_bike_parking_notice.py                      # dry run (operators only)
    python scripts/_send_bike_parking_notice.py --tenants            # dry run incl. tenants
    python scripts/_send_bike_parking_notice.py --tenants --send     # LIVE full broadcast
"""
from __future__ import annotations

import asyncio
import os
import sys

from dotenv import load_dotenv

ROOT = r"d:\Work\Claude Projects\AI Watsapp PG Accountant"
sys.path.insert(0, ROOT)
load_dotenv(os.path.join(ROOT, ".env"))

from src.whatsapp.reminder_sender import send_template  # noqa: E402

TEMPLATE = "custom_broadcast_notice"
LANGUAGE = "en"

# {{1}} is baked into the template as "Hi {{1}},". General notice — generic
# salutation, not the tenant's name (Kiran 2026-08-10).
GREETING = "Tenants"

OPERATORS = [
    ("Kiran", "7845952289"),
    ("Lokesh", "7680814628"),
    ("Lakshmi Mam", "7358341775"),
    ("Prabhakaran", "9444296681"),
]

# Body param = {{2}}. Template supplies "Hi {{1}}," and the sign-off, so the
# "Dear Tenants," greeting and "Thank you" are stripped from Kiran's draft.
# Meta rejects params containing newline/tab chars (error #132018) — one
# flowing paragraph only.
BODY = (
    "It has been noticed that some bikes are not being parked properly, "
    "which is causing difficulty for others to move and park their vehicles. "
    "Some bikes are also being parked at the entrance, blocking access. "
    "Kindly ensure that you park your bike properly in the designated parking "
    "area and keep the parking space organized at all times. "
    "Your cooperation is highly appreciated."
)


ACTIVE_TENANTS_SQL = """
    SELECT te.id AS tenant_id, te.name, te.phone
    FROM tenancies t
    JOIN tenants te ON te.id = t.tenant_id
    WHERE t.status = 'active' AND te.phone IS NOT NULL AND te.phone != ''
    ORDER BY te.name
"""


async def main() -> None:
    dry_run = "--send" not in sys.argv
    tenants_too = "--tenants" in sys.argv

    rows = []
    if tenants_too:
        from sqlalchemy import text

        from src.database.db_manager import get_session, init_engine

        init_engine(os.environ["DATABASE_URL"])
        async with get_session() as session:
            rows = (await session.execute(text(ACTIVE_TENANTS_SQL))).fetchall()
        # one message per unique phone — shared numbers (couples/siblings) exist
        seen, uniq = set(), []
        for r in rows:
            p = (r.phone or "").strip()
            if p and p not in seen:
                seen.add(p)
                uniq.append(r)
        rows = uniq

    print(f"Template: {TEMPLATE} ({LANGUAGE})")
    print(f"Body length: {len(BODY)} chars (limit 1024)")
    print(f"Recipients: {len(rows)} active tenants (unique phones) + {len(OPERATORS)} operators")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE SEND'}\n")
    print("--- rendered preview ---")
    print(f"Hi {GREETING},\n\n{BODY}\n\nThanks & regards,\nTeam Cozeevo Coliving")
    print("--- end preview ---\n")

    if dry_run:
        for r in rows[:10]:
            print(f"  would send -> {r.name} ({r.phone})")
        if len(rows) > 10:
            print(f"  ... and {len(rows) - 10} more tenants")
        for name, phone in OPERATORS:
            print(f"  would CC   -> {name} ({phone})")
        print("\nRe-run with --send to actually send.")
        return

    sent, failed = 0, []
    for r in rows:
        ok = await send_template(
            r.phone, TEMPLATE, language_code=LANGUAGE, body_params=[GREETING, BODY]
        )
        if ok:
            sent += 1
        else:
            failed.append((r.name, r.phone))
        await asyncio.sleep(0.3)

    if rows:
        print(f"Tenants sent: {sent}/{len(rows)}")
        if failed:
            print(f"Failed ({len(failed)}):")
            for name, phone in failed:
                print(f"  {name} ({phone})")

    # Operator CC — same template path, ALWAYS included in every broadcast (Kiran's rule).
    for name, phone in OPERATORS:
        ok = await send_template(
            phone, TEMPLATE, language_code=LANGUAGE, body_params=[GREETING, BODY]
        )
        print(f"  CC {'OK  ' if ok else 'FAIL'} -> {name} ({phone})")
        await asyncio.sleep(0.4)


if __name__ == "__main__":
    asyncio.run(main())
