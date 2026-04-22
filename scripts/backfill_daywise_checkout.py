"""Backfill checkout_date for legacy DaywiseStay rows missing it.

Strategy:
1. If stay_period parses to a clean range (e.g. "feb 15-19", "27-31"),
   derive end day in the same month.
2. Else default to checkin + 1 day (single-night stay) — these are all
   EXIT, the safest fallback.
3. Also clear noisy stay_period strings like '2026-02-01 00:00:00' that
   are echoed checkin timestamps, not human-readable ranges.

Run:  venv/Scripts/python scripts/backfill_daywise_checkout.py --write
"""
import argparse
import asyncio
import os
import re
import sys
from datetime import date, timedelta

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import select
from src.database.db_manager import init_engine, get_session
from src.database.models import DaywiseStay


MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def parse_period(text: str, checkin: date):
    """Try to extract checkout date from stay_period text.

    Returns date or None if can't parse.
    Handles: "27-31", "feb 15-19", "23rd, 29 - feb 3rd", "jan-30-feb3st".
    """
    if not text:
        return None
    s = text.lower().strip()
    # Drop any timestamp echo like "2026-02-01 00:00:00"
    if re.match(r"^\d{4}-\d{2}-\d{2}", s):
        return None

    # Find month names; map to month number
    months_found = []
    for nm, mi in MONTHS.items():
        for m in re.finditer(r"\b" + nm + r"\w*\b", s):
            months_found.append((m.start(), mi))
    months_found.sort()

    # Find last day-number followed by ordinal suffix or near end
    # Look for the LAST occurrence of (\d+)(st|nd|rd|th)? before end
    nums = [(m.start(), int(m.group(1))) for m in re.finditer(r"\b(\d{1,2})(?:st|nd|rd|th)?\b", s)]
    if not nums:
        return None
    last_num_pos, last_day = nums[-1]
    if last_day < 1 or last_day > 31:
        return None

    # Determine month for the last day: latest month-token before/at last_num_pos
    end_month = None
    end_year = checkin.year
    for pos, mi in months_found:
        if pos <= last_num_pos:
            end_month = mi
    if end_month is None:
        end_month = checkin.month  # same month as checkin

    # If end_month < checkin.month, year wraps forward
    if end_month < checkin.month:
        end_year += 1

    try:
        return date(end_year, end_month, last_day)
    except ValueError:
        return None


async def main(write: bool):
    init_engine(os.environ["DATABASE_URL"])
    async with get_session() as s:
        rows = (await s.execute(
            select(DaywiseStay).where(DaywiseStay.checkout_date.is_(None))
        )).scalars().all()
        print(f"Rows missing checkout: {len(rows)}\n")

        parsed = default = skipped = 0
        for r in rows:
            new_checkout = parse_period(r.stay_period or "", r.checkin_date)
            source = "parsed"
            if not new_checkout:
                # Fallback: 1-night stay
                new_checkout = r.checkin_date + timedelta(days=1)
                source = "default+1d"

            # Clear noisy stay_period if it's just an echoed timestamp
            new_stay_period = r.stay_period
            if r.stay_period and re.match(r"^\d{4}-\d{2}-\d{2}\s*\d{2}:\d{2}", r.stay_period):
                new_stay_period = ""

            num_days = max(1, (new_checkout - r.checkin_date).days)

            print(f"[{source:<10}] [{r.id}] {r.guest_name:<25} chk={r.checkin_date} -> out={new_checkout}  days={num_days}  period={r.stay_period!r} -> {new_stay_period!r}")

            if write:
                r.checkout_date = new_checkout
                r.num_days = num_days
                r.stay_period = new_stay_period

            if source == "parsed":
                parsed += 1
            else:
                default += 1

        if write:
            await s.commit()
            print(f"\nCommitted. parsed={parsed} default={default}")
        else:
            print(f"\n[DRY RUN] parsed={parsed} default={default}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    asyncio.run(main(args.write))
