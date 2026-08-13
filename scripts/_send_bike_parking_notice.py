# -*- coding: utf-8 -*-
"""One-off: send the bike parking notice via custom_broadcast_notice.

CANONICAL BROADCAST RECIPE (copy this for future notices):
  1. OPERATORS FIRST — the number is on TIER_250 (250 unique business-initiated
     conversations / 24h). Operators at the END of the queue fall past the cap
     and get silently dropped (happened 2026-08-10 and 2026-08-13).
  2. Collect wamids from send_template() (returns the Meta message id).
  3. After the run, send_delivery_report() waits for status webhooks and
     WhatsApps the operators a delivered/read/failed summary.

Manual broadcast — triggered directly by Kiran, 2026-08-13. Not scheduled.
See memory/rules_whatsapp_cc.md.

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

from src.whatsapp.broadcast_report import OPERATORS, send_delivery_report  # noqa: E402
from src.whatsapp.reminder_sender import send_template  # noqa: E402

TEMPLATE = "custom_broadcast_notice"
LANGUAGE = "en"

# {{1}} is baked into the template as "Hi {{1}},". General notice — generic
# salutation, not the tenant's name (Kiran 2026-08-10).
GREETING = "Tenants"

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

    from src.database.db_manager import get_session, init_engine

    init_engine(os.environ["DATABASE_URL"])

    rows = []
    if tenants_too:
        from sqlalchemy import text

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
    print(f"Recipients: {len(OPERATORS)} operators FIRST, then {len(rows)} active tenants (unique phones)")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE SEND'}\n")
    print("--- rendered preview ---")
    print(f"Hi {GREETING},\n\n{BODY}\n\nThanks & regards,\nTeam Cozeevo Coliving")
    print("--- end preview ---\n")

    if dry_run:
        for name, phone in OPERATORS:
            print(f"  would send -> {name} ({phone})  [operator, first]")
        for r in rows[:10]:
            print(f"  would send -> {r.name} ({r.phone})")
        if len(rows) > 10:
            print(f"  ... and {len(rows) - 10} more tenants")
        print("\nRe-run with --send to actually send.")
        return

    wamids: dict[str, tuple[str, str]] = {}   # wamid -> (name, phone)

    # ── Operators FIRST (TIER_250 — never let staff sit past the cap) ─────────
    for name, phone in OPERATORS:
        ok = await send_template(
            phone, TEMPLATE, language_code=LANGUAGE, body_params=[GREETING, BODY]
        )
        if isinstance(ok, str):
            wamids[ok] = (name, phone)
        print(f"  operator {'OK  ' if ok else 'FAIL'} -> {name} ({phone})")
        await asyncio.sleep(0.4)

    # ── Tenants ───────────────────────────────────────────────────────────────
    sent, failed = 0, []
    for r in rows:
        ok = await send_template(
            r.phone, TEMPLATE, language_code=LANGUAGE, body_params=[GREETING, BODY]
        )
        if ok:
            sent += 1
            if isinstance(ok, str):
                wamids[ok] = (r.name, r.phone)
        else:
            failed.append((r.name, r.phone))
        await asyncio.sleep(0.3)

    if rows:
        print(f"Tenants accepted by Meta: {sent}/{len(rows)}")
        if failed:
            print(f"Rejected at send time ({len(failed)}):")
            for name, phone in failed:
                print(f"  {name} ({phone})")

    # ── Delivery report — waits for status webhooks, then WhatsApps operators ──
    summary = await send_delivery_report(wamids, label="bike parking notice")
    print(f"\n{summary}")


if __name__ == "__main__":
    asyncio.run(main())
