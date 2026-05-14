"""Check and void duplicate May 2026 rent payments.

Doubles are caused by _fix_db_to_match_sheet.py + _import_may_payments.py both
adding rent payments for the same tenant. Rule: keep the one from the source
sheet import (notes contain 'Z/AA import' or 'source sheet'). Void the older
'sheet fix' duplicate.

Usage:
    python scripts/_check_may_doubles.py          # dry run — show duplicates
    python scripts/_check_may_doubles.py --write  # void the duplicates
"""
from __future__ import annotations
import asyncio, os, sys, argparse
sys.path.insert(0, ".")
from dotenv import load_dotenv; load_dotenv()
from src.database.db_manager import init_db, get_session
from sqlalchemy import text
from collections import defaultdict


async def run(write: bool):
    db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL") or ""
    await init_db(db_url)
    async with get_session() as s:
        rows = (await s.execute(text(
            "SELECT p.id, t2.name, r.room_number::text, "
            "       p.payment_mode::text, p.amount, p.notes, p.payment_date::text "
            "FROM payments p "
            "JOIN tenancies t1 ON t1.id = p.tenancy_id "
            "JOIN tenants t2 ON t2.id = t1.tenant_id "
            "LEFT JOIN rooms r ON r.id = t1.room_id "
            "WHERE p.is_void = false "
            "  AND p.for_type::text = 'rent' "
            "  AND p.period_month = '2026-05-01'::date "
            "ORDER BY t2.name, p.id"
        ))).all()

        by_tenant = defaultdict(list)
        for r in rows:
            by_tenant[(r.name, r.room_number)].append(r)

        doubled = {k: v for k, v in by_tenant.items() if len(v) > 1}
        print(f"Tenants with multiple May rent payments: {len(doubled)}\n")

        void_ids = []
        for (name, room), pmts in sorted(doubled.items()):
            total = sum(int(p.amount) for p in pmts)
            print(f"  {name}  room {room}  total={total:,}")

            # Group by (mode, amount) — any group with >1 entry is a duplicate run
            from collections import defaultdict as dd2
            mode_amt_groups = dd2(list)
            for p in pmts:
                mode_amt_groups[(p.payment_mode, int(p.amount))].append(p)

            for p in pmts:
                notes = p.notes or ""
                group = mode_amt_groups[(p.payment_mode, int(p.amount))]
                # Rule 1: _fix_db_to_match_sheet.py entries are always void
                is_fix_script = "_fix_db_to_match_sheet" in notes or "sheet fix" in notes.lower()
                # Rule 2: _audit script duplicating a bot-logged entry
                has_bot_logged = any(
                    "Logged" in (q.notes or "") for q in mode_amt_groups[(p.payment_mode, int(p.amount))]
                )
                is_audit_dup = "_audit_" in notes and has_bot_logged
                # Rule 3: same mode+amount ran twice — void the higher IDs
                is_import_dup = (
                    len(group) > 1
                    and not is_fix_script
                    and not is_audit_dup
                    and p.id != min(q.id for q in group)
                )
                should_void = is_fix_script or is_audit_dup or is_import_dup
                action = "VOID" if should_void else "KEEP"
                print(f"    {action}  id={p.id}  {p.payment_mode:<8}  {int(p.amount):>8,}  {notes[:70]}")
                if should_void:
                    void_ids.append(str(p.id))

        print(f"\nTotal to void: {len(void_ids)}")

        if not void_ids:
            print("No duplicates to void.")
            return

        if write:
            id_list = ", ".join(f"'{i}'" for i in void_ids)
            await s.execute(text(
                f"UPDATE payments SET is_void = true WHERE id IN ({id_list})"
            ))
            await s.commit()
            print("** COMMITTED — duplicates voided **")
        else:
            print("** DRY RUN — no changes **")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.write))
