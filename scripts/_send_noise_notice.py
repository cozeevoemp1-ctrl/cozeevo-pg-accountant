# -*- coding: utf-8 -*-
"""One-off: send the noise / late-night activity notice via custom_broadcast_notice.

Stage 1 (this run): operators only (Kiran + staff) for review.
    python send_noise_notice.py            # dry run
    python send_noise_notice.py --send     # live send to operators
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

# {{1}} is baked into the template as "Hi {{1}},". Kiran wants a general notice,
# not personalised — so param 1 is a generic salutation, not the tenant's name.
GREETING = "Tenants"

OPERATORS = [
    ("Kiran", "7845952289"),
    ("Lokesh", "7680814628"),
    ("Lakshmi Mam", "7358341775"),
    ("Prabhakaran", "9444296681"),
]

# Body param = {{2}}. Template already supplies "Hi {name}," and the sign-off,
# so the greeting and "Thank you, Cozeevo Coliving Management" are stripped.
# NOTE: Meta rejects template params containing newline/tab chars (error #132018).
# The notice therefore has to be one flowing paragraph \u2014 no line breaks possible
# unless a dedicated template with the text baked into the BODY is approved.
BODY = (
    "\u26a0\ufe0f IMPORTANT NOTICE \u2013 NOISE & LATE-NIGHT ACTIVITIES. "
    "We have received repeated complaints regarding loud music, shouting and "
    "late-night gaming activities, especially during night hours. These activities "
    "are causing serious disturbance to other tenants and affecting their sleep and rest. "
    "Please be strictly informed that gaming is permitted only until 10:30 PM. "
    "After 10:30 PM, all tenants must maintain complete silence and avoid loud music, "
    "shouting, gaming or any other activity that may disturb others. "
    "This is a shared living environment, and everyone is expected to respect the "
    "comfort and privacy of fellow tenants. "
    "Please treat this notice seriously \u2014 repeated violations may lead to strict "
    "action as per the PG rules and management policy. "
    "We expect everyone's full cooperation in maintaining a peaceful and disciplined environment."
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
