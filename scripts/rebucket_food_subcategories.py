"""Re-bucket Food & Groceries sub_categories for ALL months (Kiran 2026-09-01).

Applies the 8-bucket rules in src/rules/pnl_classify.py (Milk / Curd / Paneer /
Chicken / Eggs / Vegetables / Gas / Groceries) to every bank_transactions row
whose category is already Food & Groceries.

Guarantees:
  - sub_category ONLY. category is never changed here, so no P&L total moves
    (OPEX sums by category). Rows the new rules would move to a different
    category are reported, not touched — rule on those separately.
  - manual_category=true rows (owner-locked from the drill-down) are skipped.
  - Idempotent: re-running changes nothing once buckets match.

Usage:
    venv/Scripts/python scripts/rebucket_food_subcategories.py          # dry run
    venv/Scripts/python scripts/rebucket_food_subcategories.py --write
"""
import asyncio
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

import asyncpg  # noqa: E402

from src.database.db_manager import script_database_url  # noqa: E402
from src.rules.pnl_classify import classify_txn  # noqa: E402

FOOD = "Food & Groceries"


async def main(write: bool) -> None:
    url = script_database_url(os.environ["DATABASE_URL"]).replace("postgresql+asyncpg://", "postgresql://")
    url = url.split("?")[0]  # asyncpg takes statement_cache_size as a kwarg, not a URL param
    conn = await asyncpg.connect(url, statement_cache_size=0)
    rows = await conn.fetch(
        "select id, txn_date, amount, description, sub_category, manual_category "
        "from bank_transactions where txn_type='expense' and category=$1 order by txn_date, id",
        FOOD,
    )
    changes: list[tuple[int, str, str]] = []
    per_month_bucket: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    would_move_category: list[tuple] = []
    skipped_locked = 0
    unchanged = 0
    for r in rows:
        if r["manual_category"]:
            skipped_locked += 1
            continue
        cat, sub = classify_txn(r["description"], "expense")
        if cat != FOOD:
            would_move_category.append((r["id"], str(r["txn_date"]), float(r["amount"]), cat, sub, r["description"][-60:]))
            continue
        per_month_bucket[str(r["txn_date"])[:7]][sub] += float(r["amount"])
        if (r["sub_category"] or "") == sub:
            unchanged += 1
        else:
            changes.append((r["id"], r["sub_category"] or "", sub))

    print(f"Food & Groceries rows: {len(rows)} | to update: {len(changes)} | already correct: {unchanged} "
          f"| locked (skipped): {skipped_locked} | would change CATEGORY (not touched): {len(would_move_category)}")
    buckets = ["Milk", "Curd", "Paneer", "Chicken", "Eggs", "Vegetables", "Gas", "Groceries"]
    print(f"\n{'month':<9}" + "".join(f"{b:>11}" for b in buckets))
    for m in sorted(per_month_bucket):
        print(f"{m:<9}" + "".join(f"{per_month_bucket[m].get(b, 0):>11,.0f}" for b in buckets))
    if would_move_category:
        print("\nRows the new rules would move OUT of Food & Groceries (left as-is — rule on these):")
        for row in would_move_category:
            print("  ", *row)

    if write and changes:
        await conn.executemany(
            "update bank_transactions set sub_category=$2 where id=$1 and manual_category=false",
            [(i, new) for i, _old, new in changes],
        )
        print(f"\nWROTE {len(changes)} sub_category updates.")
    elif changes:
        print("\nDRY RUN — re-run with --write to apply.")
    await conn.close()


if __name__ == "__main__":
    asyncio.run(main("--write" in sys.argv))
