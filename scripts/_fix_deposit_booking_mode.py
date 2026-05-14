"""
Fix payment_mode for deposits and bookings wrongly imported as cash.

Rule: only cash entered in cash column = cash.
      deposits/bookings from Excel import = UPI (no payment mode was recorded).
      exception: notes containing 'cash' or 'pwa' = keep as cash.

Usage:
    python scripts/_fix_deposit_booking_mode.py          # dry run
    python scripts/_fix_deposit_booking_mode.py --write  # commit
"""
from __future__ import annotations
import asyncio, os, sys, argparse
sys.path.insert(0, ".")
from dotenv import load_dotenv; load_dotenv()
from src.database.db_manager import init_db, get_session
from sqlalchemy import text


async def run(write: bool):
    await init_db(os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL"))
    async with get_session() as s:
        rows = (await s.execute(text(
            "SELECT id, for_type::text, amount, payment_date::text, notes "
            "FROM payments "
            "WHERE is_void = false "
            "  AND payment_mode::text = 'cash' "
            "  AND for_type::text IN ('deposit', 'booking') "
            "  AND payment_date >= '2026-05-01' AND payment_date <= '2026-05-31'"
        ))).all()

        flip_ids = []
        print("=== DEPOSIT/BOOKING CASH PAYMENTS IN MAY 2026 ===\n")
        for r in rows:
            notes = (r.notes or "").lower()
            keep = "cash" in notes or "pwa" in notes
            action = "KEEP (explicit)" if keep else "FLIP -> upi"
            print(f"  {action:<20}  {r.for_type:<10}  {int(r.amount):>8,}  {r.notes}")
            if not keep:
                flip_ids.append(str(r.id))

        total_to_flip = sum(
            r.amount for r in rows
            if not ("cash" in (r.notes or "").lower() or "pwa" in (r.notes or "").lower())
        )
        print(f"\n  Will flip {len(flip_ids)} payments  total = {int(total_to_flip):,}")

        if not flip_ids:
            print("Nothing to flip.")
            return

        if write:
            id_list = ", ".join(f"'{i}'" for i in flip_ids)
            await s.execute(text(
                f"UPDATE payments SET payment_mode = 'upi'::paymentmode "
                f"WHERE id IN ({id_list})"
            ))
            await s.commit()
            print("\n** COMMITTED — flipped to UPI **")
        else:
            print("\n** DRY RUN — no changes saved **")

        # Verify final cash totals for May
        result = (await s.execute(text(
            "SELECT payment_mode::text, SUM(amount) "
            "FROM payments "
            "WHERE is_void = false "
            "  AND payment_date >= '2026-05-01' AND payment_date <= '2026-05-31' "
            "GROUP BY payment_mode ORDER BY 2 DESC"
        ))).all()
        print("\n=== MAY 2026 TOTALS AFTER FIX ===")
        for r in result:
            print(f"  {str(r[0]):<15}  {int(r[1]):>10,}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.write))
