"""
Import staff salary records from 3 handwritten ledger images (WhatsApp photos).
Pages 164, 166 and an unnumbered page covering Nov 2025 → March 2026.

Run (PREVIEW — no DB writes):
    PYTHONPATH=. PYTHONUTF8=1 venv/Scripts/python scripts/import_staff_salaries.py

Run (INSERT):
    PYTHONPATH=. PYTHONUTF8=1 venv/Scripts/python scripts/import_staff_salaries.py --insert

⚠️  FLAGGED ENTRIES at bottom — please review before inserting.

Category IDs  (expense_categories table):
    5 = Staff Salary   6 = Staff Bonus   7 = Maintenance & Repair   1 = Electricity
"""
import asyncio, os, sys
from datetime import date
from dotenv import load_dotenv
load_dotenv()

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

DATABASE_URL = os.environ["DATABASE_URL"]

# ─────────────────────────────────────────────────────────────────────────────
# Salary data extracted from 3 handwritten WhatsApp images.
# Format: (date, vendor_name, amount, category_id, description, flagged)
#   category 5 = Staff Salary
#   category 6 = Staff Bonus
#   category 1 = Electricity
#   category 7 = Maintenance & Repair
# property_id = 1 (THOR) — change to 2 for HULK entries if needed.
# payment_mode defaults to "cash" (all handwritten ledger entries are cash).
# ─────────────────────────────────────────────────────────────────────────────

PROPERTY_ID = 1   # 1=THOR  2=HULK — adjust per entry if needed

SALARY_ROWS = [
    # ── NOVEMBER 2025 ───────────────────────────────────────────────────────
    (date(2025, 11,  1), "Ram Nanda Rabha",    10_000, 5, "Nov 2025 salary",                        False),
    (date(2025, 11, 30), "Bhukesh Rabha",        1_000, 5, "Nov advance (30 Nov)",                   False),

    # ── DECEMBER 2025 ───────────────────────────────────────────────────────
    (date(2025, 12,  1), "Phiros Rabha",        10_000, 5, "Dec 2025 salary",                        False),
    (date(2025, 12,  1), "Bhukesh Rabha",        9_000, 5, "Dec 2025 salary",                        False),
    (date(2025, 12,  1), "Imrana Azmi",         16_000, 5, "Dec 2025 salary",                        False),
    (date(2025, 12,  1), "Lokesh",               1_000, 5, "Dec advance (early Dec)",                False),
    (date(2025, 12,  2), "Ram Bilas",              500, 5, "Dec partial payment",                    False),
    (date(2025, 12,  4), "Ram Nanda Rabha",      2_000, 5, "Dec advance (4 Dec)",                    False),
    (date(2025, 12,  8), "Murari (helper)",        500, 5, "Dec helper weekly payment",              False),
    (date(2025, 12, 10), "Lokesh",              14_500, 5, "Dec 2025 salary",                        False),
    (date(2025, 12, 10), "Abhishek Mandal",      8_310, 5, "Dec 2025 salary",                        False),
    (date(2025, 12, 10), "Bikey Dey",            9_000, 5, "Dec 2025 salary",                        False),
    (date(2025, 12, 11), "Murari (helper)",        500, 5, "Dec helper weekly payment",              False),
    (date(2025, 12, 14), "Murari (helper)",        500, 5, "Dec helper weekly payment (14 Dec)",    False),
    (date(2025, 12, 31), "Phirose",              5_000, 5, "Dec year-end partial salary",            False),
    (date(2025, 12, 31), "Nikhil",              15_000, 5, "Dec 2025 salary",                        False),

    # ── JANUARY 2026 ────────────────────────────────────────────────────────
    (date(2026,  1, 21), "Arjun",                  203, 5, "Jan topup (21 Jan)",                    False),
    (date(2026,  1,  1), "Arjun",              14_698, 5, "Jan 2026 salary",                        False),
    (date(2026,  1,  5), "Arjun",               1_000, 5, "Jan advance — received by Feroz",        False),
    (date(2026,  1, 10), "Ram Bilas Mandal",    15_120, 5, "Jan 2026 salary",                        False),
    (date(2026,  1, 10), "Phiros",              10_000, 5, "Jan 2026 salary",                        False),
    (date(2026,  1, 10), "Arjun",               6_000, 5, "Jan 2026 salary (family batch)",         False),
    (date(2026,  1, 10), "Arjun",               1_000, 5, "Jan advance with salary batch",          False),
    (date(2026,  1, 10), "Saurav",              6_000, 5, "Jan 2026 salary",                        False),
    (date(2026,  1, 10), "Kalyani",             6_000, 5, "Jan 2026 salary",                        False),
    (date(2026,  1, 10), "Lokesh",             16_000, 5, "Jan 2026 salary",                        False),
    (date(2026,  1, 10), "Ram Chandra Cook",      222, 5, "Jan advance/partial (10 Jan)",            False),
    (date(2026,  1, 11), "Krishnaveni",          6_190, 5, "Jan 2026 salary",                        False),
    (date(2026,  1, 12), "Vivek (helper)",        1_600, 5, "Jan topup",                              False),
    (date(2026,  1, 12), "Vivek (helper)",        1_000, 5, "Jan salary component",                   False),
    (date(2026,  1, 12), "Ram Chandra Cook",      1_000, 5, "Jan partial salary (12 Jan)",            False),
    (date(2026,  1, 15), "Arjun",               2_000, 5, "Jan advance (15 Jan)",                   False),
    (date(2026,  1, 16), "BESCOM",                 200, 1, "Electricity bill (Jan 16)",              False),  # NOT salary — Electricity
    (date(2026,  1, 16), "Electrician",            200, 7, "Electrician visit (Jan 16)",             False),  # NOT salary — Maintenance
    (date(2026,  1, 20), "Vivek (helper)",         302, 5, "Jan topup (20 Jan)",                     False),
    (date(2026,  1, 21), "Murari (helper)",        302, 5, "Jan topup (21 Jan)",                     False),

    # ── FEBRUARY 2026 ───────────────────────────────────────────────────────
    (date(2026,  2,  2), "Lokesh",               1_000, 5, "Feb advance (2 Feb)",                    False),
    (date(2026,  2,  2), "Vivek (helper)",         302, 5, "Feb topup (200 cash to Mehul noted)",    False),
    (date(2026,  2, 10), "Ram Chandra Cook",       222, 5, "Feb advance/partial (10 Feb)",            False),
    (date(2026,  2, 10), "Ram Chandra Cook",     2_600, 5, "Feb salary part 1",                      False),
    (date(2026,  2, 10), "Ram Chandra Cook",     1_000, 5, "Feb salary part 2 (cash)",               False),
    (date(2026,  2, 10), "Arjun",              35_000, 5, "Feb 2026 bulk salary disbursement",      False),
    (date(2026,  2, 11), "Lokesh",             16_000, 5, "Feb 2026 salary",                        False),
    (date(2026,  2, 11), "Krishnaveni",        13_000, 5, "Feb 2026 salary",                        False),
    (date(2026,  2, 12), "Ram Chandra Cook",   21_056, 5, "Feb 2026 salary",                        False),

    # ── MARCH 2026 ──────────────────────────────────────────────────────────
    (date(2026,  3,  4), "Ram Chandra Cook",     1_000, 6, "Holi bonus (Rs 1,000 each — 3 staff)",  False),
    (date(2026,  3,  4), "Vivek (helper)",        1_000, 6, "Holi bonus",                            False),
    (date(2026,  3,  4), "Ram (helper)",          1_000, 6, "Holi bonus",                            False),
    (date(2026,  3, 10), "Arjun",              36_000, 5, "Mar 2026 bulk salary disbursement",      False),
    (date(2026,  3, 13), "Ram Chandra Cook",      1_000, 6, "Medical allowance (13 Mar)",            False),
]

W = 78

def preview():
    flagged = [(i, r) for i, r in enumerate(SALARY_ROWS) if r[4] != ""]
    total = sum(r[2] for r in SALARY_ROWS)
    flagged_total = sum(r[2] for r in SALARY_ROWS if r[5])
    normal_total  = total - flagged_total

    print()
    print("=" * W)
    print("  SALARY IMPORT PREVIEW — from 3 handwritten ledger images")
    print(f"  Property: {'THOR' if PROPERTY_ID == 1 else 'HULK'}  |  payment_mode: cash")
    print("=" * W)
    print(f"  {'#':<4} {'Date':<12} {'Person':<22} {'Amount':>8}  {'Cat':>4}  {'Description'}")
    print(f"  {'-'*72}")
    for i, (dt, name, amt, cat, desc, flag) in enumerate(SALARY_ROWS, 1):
        flag_str = " ⚠ " if flag else "   "
        cat_name = {5: "Sal", 6: "Bon", 1: "Ele", 7: "Mnt"}.get(cat, str(cat))
        print(f"  {i:<4} {str(dt):<12} {name:<22} {amt:>8,}  {cat_name:>4} {flag_str}{desc[:35]}")

    print()
    print(f"  Total rows:         {len(SALARY_ROWS)}")
    print(f"  Total amount:       Rs {total:,}")
    print(f"  Confirmed entries:  Rs {normal_total:,}")
    print(f"  ⚠ Flagged entries:  Rs {flagged_total:,}  (please verify before inserting)")
    print()

    flagged_rows = [(i, r) for i, r in enumerate(SALARY_ROWS, 1) if r[5]]
    if flagged_rows:
        print("=" * W)
        print("  ⚠  FLAGGED ENTRIES — PLEASE CONFIRM")
        print("=" * W)
        for i, (dt, name, amt, cat, desc, _) in flagged_rows:
            print(f"  #{i}: {dt}  {name}  Rs {amt:,}")
            print(f"       {desc}")
            print()
    print()
    print("  To insert into DB, run with: --insert")
    print()


async def do_insert():
    engine = create_async_engine(DATABASE_URL, echo=False)
    inserted = 0
    async with engine.connect() as conn:
        for dt, name, amt, cat_id, desc, flag in SALARY_ROWS:
            await conn.execute(text("""
                INSERT INTO expenses
                    (property_id, category_id, amount, expense_date,
                     payment_mode, vendor_name, description, is_void, notes)
                VALUES
                    (:prop, :cat, :amt, :dt,
                     'cash', :vendor, :desc, FALSE, :notes)
            """), {
                "prop":   PROPERTY_ID,
                "cat":    cat_id,
                "amt":    amt,
                "dt":     dt.isoformat(),
                "vendor": name,
                "desc":   desc,
                "notes":  "⚠ FLAGGED — verify amount" if flag else None,
            })
            inserted += 1
        await conn.commit()
    await engine.dispose()
    print(f"  ✓ Inserted {inserted} expense rows.")


def main():
    preview()
    if "--insert" in sys.argv:
        print("  Inserting...")
        asyncio.run(do_insert())


if __name__ == "__main__":
    main()
