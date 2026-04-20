"""
scripts/run_monthly_rollover.py
Atomic monthly rollover — runs on the 2nd-to-last calendar day of each month.

Sequence:
  1. Pull source sheet → DB (catches anything webhook missed)
  2. Generate RentSchedule rows in DB for NEXT month
  3. Create NEXT month's tab in Operations sheet (carry-forward dues, first-month logic)
  4. Refresh summary stats

Usage:
  python scripts/run_monthly_rollover.py               # auto-detect next month
  python scripts/run_monthly_rollover.py MAY 2026      # specific target
  python scripts/run_monthly_rollover.py --skip-source # skip step 1 (for testing)
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from datetime import date

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

MONTHS = ["JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY",
          "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER"]


def _next_month(today: date) -> tuple[int, int, str]:
    """Return (year, month_num, month_name) for the month AFTER today."""
    if today.month == 12:
        return today.year + 1, 1, MONTHS[0]
    return today.year, today.month + 1, MONTHS[today.month]


async def _generate_rs(year: int, month: int) -> dict:
    from src.database.db_manager import init_engine
    await init_engine()
    from src.services.monthly_rollover import generate_rent_schedule_for_month
    return await generate_rent_schedule_for_month(year, month)


def _run_source_sync() -> bool:
    print("[1/4] Pulling source sheet → DB...")
    py = "venv/Scripts/python" if os.name == "nt" else "venv/bin/python"
    result = subprocess.run(
        [py, "scripts/sync_from_source_sheet.py", "--write"],
        capture_output=True, text=True, timeout=600,
    )
    if result.returncode != 0:
        print("  ✗ Source sync failed:", result.stderr[-400:])
        return False
    print("  ✓ Source sync complete")
    return True


def _create_sheet_tab(month_name: str, year: int) -> bool:
    print(f"[3/4] Creating sheet tab {month_name} {year}...")
    py = "venv/Scripts/python" if os.name == "nt" else "venv/bin/python"
    result = subprocess.run(
        [py, "scripts/create_month.py", month_name, str(year)],
        capture_output=True, text=True, timeout=300,
    )
    print(result.stdout)
    if result.returncode != 0:
        print("  ✗ Sheet tab creation failed:", result.stderr[-400:])
        return False
    print("  ✓ Sheet tab created")
    return True


def _refresh_dashboard(year: int, month: int) -> None:
    """Re-sync the new month's sheet from DB (ensures rent_due matches RentSchedule)."""
    print(f"[4/4] Refreshing sheet from DB for {year}-{month:02d}...")
    py = "venv/Scripts/python" if os.name == "nt" else "venv/bin/python"
    result = subprocess.run(
        [py, "scripts/sync_sheet_from_db.py",
         "--month", str(month), "--year", str(year), "--write"],
        capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        print("  ✗ Sheet refresh failed:", result.stderr[-400:])
    else:
        print("  ✓ Sheet reconciled with DB")


async def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    skip_source = "--skip-source" in sys.argv

    if len(args) >= 2:
        month_name = args[0].upper()
        year = int(args[1])
        month_num = MONTHS.index(month_name) + 1
    else:
        year, month_num, month_name = _next_month(date.today())

    print(f"Monthly rollover: {month_name} {year}")
    print("=" * 50)

    # 1. Source sync
    if not skip_source:
        if not _run_source_sync():
            print("Aborting — source sync failed.")
            return 1
    else:
        print("[1/4] Source sync skipped (--skip-source)")

    # 2. Generate RentSchedule rows in DB
    print(f"[2/4] Generating RentSchedule rows for {month_name} {year}...")
    try:
        stats = await _generate_rs(year, month_num)
        print(f"  ✓ DB: created={stats['created']} existing={stats['skipped_existing']}"
              f" noshow={stats['noshow']} first_month={stats['first_month']}")
    except Exception as e:
        print(f"  ✗ RentSchedule generation failed: {e}")
        return 2

    # 3. Create sheet tab
    if not _create_sheet_tab(month_name, year):
        return 3

    # 4. Reconcile sheet ↔ DB
    _refresh_dashboard(year, month_num)

    print("=" * 50)
    print(f"Rollover complete: {month_name} {year}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
