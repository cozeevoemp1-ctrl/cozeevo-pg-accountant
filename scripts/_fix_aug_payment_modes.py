"""
One-off: correct payment_mode cash -> upi for four August-2026 payments that
were logged at the counter as cash but were actually paid by UPI.

Confirmed by Kiran 2026-08-11 during the August cash reconciliation
(see scripts/_reconcile_aug_cash.py). All four were app-only entries with no
matching receipt in the physical receipt book — consistent with no cash having
changed hands.

  22062  617 Abhinav A       5 Aug  Rs 13,500
  22077  214 Sanjana KP      6 Aug  Rs 13,500
  22103  510 Shirin          7 Aug  Rs 14,500
  22104  510 Thirumurugan    7 Aug  Rs 13,000

Never edits amount, date or tenancy — only payment_mode. Writes an audit_log
row per payment. Dry-run by default; pass --write to apply.

    python scripts/_fix_aug_payment_modes.py            # preview
    python scripts/_fix_aug_payment_modes.py --write    # apply
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
load_dotenv()

from src.database.db_manager import get_session, init_engine  # noqa: E402

CHANGED_BY = "Kiran"
NOTE = "Aug-2026 cash reconciliation: paid by UPI, logged as cash at counter"

TARGETS = [22062, 22077, 22103, 22104]


async def main(write: bool):
    init_engine(os.environ["DATABASE_URL"])
    async with get_session() as s:
        rows = (
            await s.execute(
                text(
                    """
                    SELECT p.id, r.room_number, t.name, p.payment_date, p.amount,
                           p.payment_mode::text AS mode, p.is_void
                    FROM payments p
                    JOIN tenancies tc ON tc.id = p.tenancy_id
                    JOIN tenants   t  ON t.id  = tc.tenant_id
                    LEFT JOIN rooms r ON r.id  = tc.room_id
                    WHERE p.id = ANY(:ids)
                    ORDER BY p.payment_date
                    """
                ),
                {"ids": TARGETS},
            )
        ).mappings().all()

        if len(rows) != len(TARGETS):
            found = {r["id"] for r in rows}
            sys.exit(f"ABORT: payment ids not found: {sorted(set(TARGETS) - found)}")

        todo = []
        for r in rows:
            flag = ""
            if r["is_void"]:
                flag = "  SKIP (voided)"
            elif r["mode"] != "cash":
                flag = f"  SKIP (already {r['mode']})"
            else:
                todo.append(r)
            print(
                f"  {r['id']}  {str(r['room_number']):>4} {str(r['name'])[:22]:<23}"
                f" {r['payment_date']}  Rs {float(r['amount']):>9,.0f}"
                f"  {r['mode']} -> upi{flag}"
            )

        if not todo:
            print("\nnothing to change.")
            return

        if not write:
            print(f"\nDRY RUN — {len(todo)} payment(s) would change. Re-run with --write.")
            return

        for r in todo:
            await s.execute(
                text("UPDATE payments SET payment_mode = 'upi' WHERE id = :id AND is_void = false"),
                {"id": r["id"]},
            )
            await s.execute(
                text(
                    """
                    INSERT INTO audit_log (created_at, changed_by, entity_type, entity_id,
                                           entity_name, field, old_value, new_value,
                                           room_number, source, note, org_id)
                    VALUES (now(), :by, 'payment', :id, :name, 'payment_mode',
                            'cash', 'upi', :room, 'script', :note, 1)
                    """
                ),
                {
                    "by": CHANGED_BY,
                    "id": r["id"],
                    "name": r["name"],
                    "room": str(r["room_number"] or ""),
                    "note": NOTE,
                },
            )
        await s.commit()
        print(f"\nupdated {len(todo)} payment(s) + wrote {len(todo)} audit_log row(s).")

        chk = (
            await s.execute(
                text(
                    """
                    SELECT payment_mode::text AS mode, count(*), sum(amount)
                    FROM payments
                    WHERE is_void = false AND period_month = '2026-08-01'
                    GROUP BY 1 ORDER BY 3 DESC
                    """
                )
            )
        ).all()
        print("\nAugust period totals after fix:")
        for mode, n, amt in chk:
            print(f"  {mode:<5} {n:>4} rows  Rs {float(amt):>12,.0f}")


if __name__ == "__main__":
    asyncio.run(main(write="--write" in sys.argv))
