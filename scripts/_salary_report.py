"""
Salary / staff payment report — per person per month pivot.

Sources:
  1. bank_transactions WHERE category = 'Staff & Labour' (bank CSV imports)
  2. expenses WHERE category name matches 'salary' or 'staff' (bot-logged)

Usage:
    python scripts/_salary_report.py           # prints to console
    python scripts/_salary_report.py --csv     # also writes salary_report.csv
"""
import asyncio, os, sys, re, argparse, csv
from collections import defaultdict
from datetime import date
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv; load_dotenv()

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

DATABASE_URL = os.environ["DATABASE_URL"]
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

engine = create_async_engine(DATABASE_URL, echo=False)
Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

# Known staff names — used to extract from free-text bank descriptions.
# Add more as needed. Matching is case-insensitive, partial.
KNOWN_STAFF = [
    "Lokesh", "Prabhakaran", "Volipi", "Chandra", "Muthu",
    "Kiran", "Pavan", "Manoj", "Raju", "Kumar", "Sekhar",
]

def extract_name(desc: str) -> str:
    """Try to extract a recognisable staff name from a bank txn description."""
    desc_l = desc.lower()
    for name in KNOWN_STAFF:
        if name.lower() in desc_l:
            return name
    # Fallback: grab first 40 chars as label
    return desc[:40].strip() if desc else "Unknown"

def month_label(d: date) -> str:
    return d.strftime("%b'%y")  # e.g. "Nov'25"

def sort_key(label: str) -> tuple:
    from datetime import datetime
    try:
        return (datetime.strptime(label, "%b'%y"),)
    except:
        return (date.max,)


async def main(write_csv: bool):
    rows_all = []  # list of (person, month_label, amount, source, description)

    async with Session() as session:

        # ── Source 1: bank_transactions (Staff & Labour) ──────────────────
        btxn = await session.execute(text("""
            SELECT txn_date, description, amount, account_name, sub_category
            FROM bank_transactions
            WHERE category = 'Staff & Labour'
              AND txn_type = 'expense'
            ORDER BY txn_date
        """))
        bank_rows = btxn.fetchall()
        print(f"\n[bank_transactions] Staff & Labour rows: {len(bank_rows)}")

        for r in bank_rows:
            person = extract_name(r.description)
            # sub_category may have the name if classified
            if r.sub_category and r.sub_category.strip():
                sc = r.sub_category.strip()
                # if it looks like a name (not a category word), prefer it
                if not any(w in sc.lower() for w in ['salary','advance','wage','labour','petty','misc']):
                    person = sc[:30]
            ml = month_label(r.txn_date)
            rows_all.append((person, ml, float(r.amount), "bank:" + r.account_name, r.description[:60]))

        # ── Source 2: expenses (salary / staff category) ──────────────────
        exp = await session.execute(text("""
            SELECT e.expense_date, e.amount, e.vendor_name, e.description,
                   e.payment_mode, ec.name AS cat_name
            FROM expenses e
            LEFT JOIN expense_categories ec ON ec.id = e.category_id
            WHERE e.is_void = false
              AND (
                LOWER(ec.name) LIKE '%salary%'
                OR LOWER(ec.name) LIKE '%staff%'
                OR LOWER(e.vendor_name) IN (
                    'lokesh','prabhakaran','volipi','chandra','muthu','pavan','raju'
                )
              )
            ORDER BY e.expense_date
        """))
        exp_rows = exp.fetchall()
        print(f"[expenses]         salary/staff rows: {len(exp_rows)}")

        for r in exp_rows:
            person = (r.vendor_name or "").strip() or extract_name(r.description or "")
            ml = month_label(r.expense_date)
            rows_all.append((person, ml, float(r.amount), "expense:" + r.cat_name, (r.description or "")[:60]))

    if not rows_all:
        print("\nNo salary/staff payment records found.")
        return

    # ── Build pivot ───────────────────────────────────────────────────────
    # pivot[person][month] = total_amount
    pivot = defaultdict(lambda: defaultdict(float))
    for person, ml, amount, source, desc in rows_all:
        pivot[person][ml] += amount

    # Sorted months (chronological)
    all_months = sorted({ml for _, ml, _, _, _ in rows_all}, key=lambda x: sort_key(x))
    all_persons = sorted(pivot.keys())

    # ── Print raw detail first ────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("RAW RECORDS — Staff & Labour / Salary payments")
    print("=" * 80)
    print(f"{'Date':<12} {'Person':<20} {'Amount':>10} {'Source':<20} {'Description'}")
    print("-" * 80)
    for person, ml, amount, source, desc in sorted(rows_all, key=lambda x: (x[0], x[1])):
        print(f"{ml:<12} {person:<20} {amount:>10,.0f} {source:<20} {desc}")

    # ── Print pivot table ─────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("SALARY PIVOT — Amount paid per person per month (Rs)")
    print("=" * 80)

    col_w = 10
    name_w = 22
    header = f"{'Name':<{name_w}}" + "".join(f"{m:>{col_w}}" for m in all_months) + f"{'TOTAL':>{col_w}}"
    print(header)
    print("-" * len(header))

    grand_total = 0.0
    month_totals = defaultdict(float)

    for person in all_persons:
        row_total = sum(pivot[person].values())
        grand_total += row_total
        line = f"{person:<{name_w}}"
        for m in all_months:
            amt = pivot[person].get(m, 0.0)
            month_totals[m] += amt
            line += f"{amt:>{col_w},.0f}" if amt else f"{'—':>{col_w}}"
        line += f"{row_total:>{col_w},.0f}"
        print(line)

    print("-" * len(header))
    total_line = f"{'TOTAL':<{name_w}}"
    for m in all_months:
        total_line += f"{month_totals[m]:>{col_w},.0f}"
    total_line += f"{grand_total:>{col_w},.0f}"
    print(total_line)

    # ── CSV export ────────────────────────────────────────────────────────
    if write_csv:
        out = "salary_report.csv"
        with open(out, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["Name"] + all_months + ["TOTAL"])
            for person in all_persons:
                row_total = sum(pivot[person].values())
                w.writerow([person] + [pivot[person].get(m, "") for m in all_months] + [row_total])
            w.writerow(["TOTAL"] + [month_totals[m] for m in all_months] + [grand_total])
        print(f"\nCSV written: {out}")

    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.csv))
