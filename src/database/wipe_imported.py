"""
Safe wipe script — removes only L1 + L2 data.

WHAT IS WIPED (re-importable from Excel):
  L1: tenants, tenancies
  L2: payments, rent_schedule, refunds, expenses

WHAT IS PRESERVED (L0 — never touch):
  authorized_users    — admin + partner access
  properties          — building records
  rooms               — physical room layout
  rate_cards          — pricing history
  staff               — employee records
  food_plans          — meal options
  expense_categories  — expense taxonomy
  whatsapp_log        — full message audit trail
  conversation_memory — bot training / semantic memory
  documents           — file registry

WHAT IS PRESERVED (L3 — operational, harmless to keep):
  leads               — room enquiries
  vacations           — absence records
  reminders           — scheduled alerts
  rate_limit_log      — spam counters
  pending_actions     — disambiguation state

Run:
  python -m src.database.wipe_imported            (dry-run preview)
  python -m src.database.wipe_imported --confirm  (actually wipes)
"""
from __future__ import annotations

import asyncio
import os
import sys

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]

# ── Tables wiped (order matters — FK children first) ──────────────────────────

L2_TABLES = [
    "refunds",          # child of tenancies
    "payments",         # child of tenancies
    "rent_schedule",    # child of tenancies
    "expenses",         # child of properties (safe to clear without tenancy deps)
]

L1_TABLES = [
    "tenancies",        # child of tenants + rooms
    "tenants",          # root
]

WIPE_ORDER = L2_TABLES + L1_TABLES

# ── Tables explicitly NEVER touched ───────────────────────────────────────────

PRESERVED = [
    "authorized_users",
    "properties",
    "rooms",
    "rate_cards",
    "staff",
    "food_plans",
    "expense_categories",
    "whatsapp_log",
    "conversation_memory",
    "documents",
]


async def run(confirm: bool):
    if DATABASE_URL.startswith("postgresql://"):
        url = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
    else:
        url = DATABASE_URL

    engine = create_async_engine(url, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as session:
        # ── Preview counts ────────────────────────────────────────────────────
        print("\n" + "="*60)
        print("WIPE PREVIEW — L1 + L2 data (re-importable from Excel)")
        print("="*60)
        print(f"  {'TABLE':<25} {'ROWS':>8}  {'ACTION'}")
        print(f"  {'-'*55}")

        for table in WIPE_ORDER:
            count = await session.scalar(text(f"SELECT COUNT(*) FROM {table}"))
            action = "WILL WIPE" if confirm else "will wipe (dry run)"
            print(f"  {table:<25} {count:>8,}  {action}")

        print(f"\n  {'PRESERVED (L0 — never touched)'}")
        for table in PRESERVED:
            count = await session.scalar(text(f"SELECT COUNT(*) FROM {table}"))
            print(f"  {table:<25} {count:>8,}  PROTECTED")

        if not confirm:
            print("\n  ⚠  DRY RUN — nothing changed.")
            print("  Re-run with --confirm to actually wipe L1 + L2 data.\n")
            await engine.dispose()
            return

        # ── Actual wipe ───────────────────────────────────────────────────────
        print("\n  Wiping...")
        for table in WIPE_ORDER:
            await session.execute(text(f"TRUNCATE {table} RESTART IDENTITY CASCADE"))
            print(f"  ✓  {table} cleared")

        await session.commit()

    await engine.dispose()

    print("\n" + "="*60)
    print("WIPE COMPLETE — L1 + L2 cleared.")
    print("L0 data (rooms, staff, authorized_users, etc.) preserved.")
    print("Run:  python -m src.database.excel_import  to re-import.\n")
    print("="*60 + "\n")


if __name__ == "__main__":
    confirm = "--confirm" in sys.argv
    asyncio.run(run(confirm))
