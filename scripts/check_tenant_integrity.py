"""Tenant identity integrity check — run before every commit / after any data load.

Catches the two failure modes that split one person across two `tenants` rows and
hide their payments in the PWA (Room 415 Rakesh, Room 615 Sheetal — Aug 2026):

  1. SPLIT      two tenant rows, same phone, similar name → payment history splits
  2. ORPHAN     tenant row with no tenancy at all → left behind when a pre-booked
                tenancy was re-pointed to a corrected tenant row

Rows with the same phone but clearly different names are reported separately as
SHARED — couples and siblings legitimately share a number, so this is never an
error and is exactly why a UNIQUE index on tenants.phone would be wrong.

    python scripts/check_tenant_integrity.py          # report
    python scripts/check_tenant_integrity.py --strict # exit 1 if SPLIT/ORPHAN found
"""
from __future__ import annotations

import asyncio
import difflib
import os
import sys

from dotenv import load_dotenv
from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

from src.database.db_manager import get_session, init_engine  # noqa: E402

# Two names count as the same person above this similarity.
NAME_MATCH = 0.55

SAME_PHONE = """
SELECT right(regexp_replace(t.phone, '[^0-9]', '', 'g'), 10) AS ph,
       t.id, t.name,
       (SELECT count(*) FROM tenancies tn WHERE tn.tenant_id = t.id) AS tenancies,
       (SELECT count(*) FROM payments p JOIN tenancies tn ON tn.id = p.tenancy_id
         WHERE tn.tenant_id = t.id AND p.is_void IS NOT TRUE)          AS payments
  FROM tenants t
 WHERE length(regexp_replace(t.phone, '[^0-9]', '', 'g')) >= 10
 ORDER BY ph, t.id
"""

ORPHANS = """
SELECT t.id, t.name, t.phone, t.created_at
  FROM tenants t
 WHERE NOT EXISTS (SELECT 1 FROM tenancies tn WHERE tn.tenant_id = t.id)
 ORDER BY t.created_at DESC
"""


def _similar(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, (a or "").lower(), (b or "").lower()).ratio()


def _same_person(a: str, b: str) -> bool:
    """Similar overall, or one name's words are a subset of the other's."""
    if _similar(a, b) >= NAME_MATCH:
        return True
    wa = {w for w in (a or "").lower().replace(".", " ").split() if len(w) > 2}
    wb = {w for w in (b or "").lower().replace(".", " ").split() if len(w) > 2}
    return bool(wa & wb)


async def main(strict: bool) -> int:
    init_engine(os.getenv("DATABASE_URL"))
    splits, shared, orphans = [], [], []

    async with get_session() as s:
        rows = (await s.execute(text(SAME_PHONE))).mappings().all()
    groups: dict[str, list] = {}
    for r in rows:
        groups.setdefault(r["ph"], []).append(r)

    for ph, members in groups.items():
        if len(members) < 2:
            continue
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                (splits if _same_person(a["name"], b["name"]) else shared).append((ph, a, b))

    async with get_session() as s:
        orphans = (await s.execute(text(ORPHANS))).mappings().all()

    if splits:
        print(f"SPLIT — {len(splits)} pair(s): same phone, same person, two tenant rows")
        for ph, a, b in splits:
            print(f"  +91{ph}  {a['id']}:{a['name']} ({a['payments']} pmts, {a['tenancies']} tncy)"
                  f"  <->  {b['id']}:{b['name']} ({b['payments']} pmts, {b['tenancies']} tncy)")
        print("  fix: keep the row with more payments, move the rest, then delete the duplicate")
    else:
        print("SPLIT — none")

    if orphans:
        print(f"\nORPHAN — {len(orphans)} tenant row(s) with no tenancy")
        for o in orphans:
            print(f"  {o['id']}:{o['name']} ({o['phone']}) created {o['created_at']}")
    else:
        print("\nORPHAN — none")

    if shared:
        print(f"\nSHARED — {len(shared)} pair(s) on one phone, different people (expected, not an error)")
        for ph, a, b in shared:
            print(f"  +91{ph}  {a['id']}:{a['name']}  |  {b['id']}:{b['name']}")

    problems = len(splits) + len(orphans)
    if strict and problems:
        print(f"\nFAIL — {problems} integrity problem(s)")
        return 1
    print(f"\nOK — {problems} problem(s)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main("--strict" in sys.argv)))
