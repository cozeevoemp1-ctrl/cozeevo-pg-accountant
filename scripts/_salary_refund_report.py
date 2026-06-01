"""
Two reports in one:

A) SALARY PIVOT — per staff member per month (Oct 2025 → now)
   Source: bank_transactions WHERE category = 'Staff & Labour'
   UPI handles mapped to real names using known mappings.

B) TENANT REFUNDS — per tenant total refund ever paid (Oct 2025 → now)
   Source: refunds table + checkout_records.deposit_refunded_amount

Usage:
    python scripts/_salary_refund_report.py
"""
import asyncio, os, sys, re
from collections import defaultdict
from datetime import date
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv; load_dotenv()

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

DATABASE_URL = os.environ["DATABASE_URL"]
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

engine = create_async_engine(DATABASE_URL, echo=False)
Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

# ── UPI handle / keyword → staff name ─────────────────────────────────────────
# Checked against pnl_classifications.md and sub_category values in DB.
# Order matters — first match wins. More specific patterns before generic.
UPI_TO_NAME = [
    # Named sub_categories from bank classifier
    ("7680814628",          "Lokesh (Receptionist)"),
    ("9444296681",          "Prabhakaran (Manager)"),
    ("volipi.l",            "Volipi (Cleaner)"),
    ("rockshield",          "Rock Shield (Security Contractor)"),
    ("bn895975",            "Bhukesh"),
    ("6202601070",          "Vivek"),
    ("6287677379",          "Vivek"),
    ("8905122862",          "kshama (Staff)"),          # Mar 23K transfer
    ("rampukarmandal",      "Rampukar (Labour)"),
    ("8837062479",          "Sreeraj (Housekeeping)"),
    ("salamtajamul",        "Salam Tajamul (Housekeeping)"),
    ("manishaspundir",      "Manisha Pundir (Housekeeping)"),
    ("9071242117",          "Housekeeping Staff"),
    ("9611622637",          "Housekeeping Staff"),
    ("9398545495",          "Housekeeping Staff"),
    ("sarojrout",           "Saroj Rout (Housekeeping)"),
    ("dilliprout",          "Dilli Rout (Housekeeping)"),
    ("imranaaazmi",         "Imran Azmi (Housekeeping)"),
    ("rabhasoma",           "Rabha Soma (Housekeeping)"),
    ("sanket.wankhede",     "Sanket Wankhede"),
    ("biplab141",           "Biplab (Staff)"),
    ("bikeydey",            "Bikey Dey (Staff)"),
    ("kn.ravikumar",        "Ravi Kumar"),
    ("sachindivya",         "Sachin Divya"),
    ("sandeepgowda",        "Sandeep Gowda"),
    ("gudadesh",            "Gudadesh (Contractor)"),
    ("9102937483",          "Staff - 9102937483"),
    ("9110460729",          "Ram Chandra (Cook/Staff)"),  # Mar: "ramchandra" in memo
    ("9342205440",          "Vendor - 9342205440"),
    ("9880401360",          "Elemental Staff (9880401360)"),
    ("swamisarang",         "Swami Sarang"),
    ("akmalakmal",          "Akmal (Staff)"),
    ("vishal521",           "Vishal (Staff)"),
    ("kutubuddinku",        "Kutubuddin (Staff)"),
    ("8132966734",          "Staff - 8132966734"),
    ("6362243208",          "Staff - 6362243208"),
    ("8409903591",          "Staff - 8409903591"),
    ("8409903591",          "Staff - 8409903591"),
    ("jioinappdirect",      "Jio Recharge (Lokesh)"),
    ("viinapp",             "Vi Recharge (Staff)"),
    ("urbancompany",        "Urban Company (Cleaning Svc)"),
    ("workindia",           "WorkIndia (Recruitment)"),
    # NEFT/IMPS patterns — large salary transfers
    ("xxxx5021",            "NEFT to SBI-5021 (Staff)"),   # likely Prabhakaran bank salary
    ("xxxx6948",            "NEFT to SBI-6948 (Staff)"),
    ("joshi arjunbha",      "Joshi Arjunbhai (Contractor)"),
]

def person_from_sub(sub: str, desc: str) -> str:
    combined = (sub or "").lower() + " " + (desc or "").lower()
    for pattern, name in UPI_TO_NAME:
        if pattern.lower() in combined:
            return name
    # Fallback: first 35 chars of sub_category if it looks human
    if sub and len(sub) < 45 and not sub.startswith("UPI/"):
        return sub[:35]
    # Last fallback: truncated description
    return (desc or "Unknown")[:35]

def month_label(d: date) -> str:
    return d.strftime("%b'%y")

def sort_ml(label: str):
    from datetime import datetime
    try:
        return datetime.strptime(label, "%b'%y")
    except:
        return datetime.max


async def main():
    async with Session() as session:

        # ═══════════════════════════════════════════════════════════════
        # A) SALARY REPORT
        # ═══════════════════════════════════════════════════════════════

        btxn = await session.execute(text("""
            SELECT txn_date, description, amount, account_name, sub_category
            FROM bank_transactions
            WHERE category = 'Staff & Labour'
              AND txn_type = 'expense'
              AND txn_date >= '2025-10-01'
            ORDER BY txn_date
        """))
        bank_rows = btxn.fetchall()

        # Aggregate into pivot
        pivot = defaultdict(lambda: defaultdict(float))
        all_months_set = set()

        for r in bank_rows:
            person = person_from_sub(r.sub_category or "", r.description or "")
            ml = month_label(r.txn_date)
            pivot[person][ml] += float(r.amount)
            all_months_set.add(ml)

        all_months = sorted(all_months_set, key=sort_ml)
        all_persons = sorted(pivot.keys())

        print("\n" + "=" * 100)
        print("A) SALARY & STAFF PAYMENTS PIVOT (Oct 2025 → now) — bank_transactions, category=Staff & Labour")
        print("=" * 100)

        col_w = 11
        name_w = 32
        header = f"{'Staff Name':<{name_w}}" + "".join(f"{m:>{col_w}}" for m in all_months) + f"{'TOTAL':>{col_w}}"
        print(header)
        print("-" * len(header))

        month_totals = defaultdict(float)
        grand_total = 0.0

        for person in all_persons:
            row_total = sum(pivot[person].values())
            grand_total += row_total
            line = f"{person:<{name_w}}"
            for m in all_months:
                amt = pivot[person].get(m, 0.0)
                month_totals[m] += amt
                line += f"{int(amt):>{col_w},}" if amt else f"{'—':>{col_w}}"
            line += f"{int(row_total):>{col_w},}"
            print(line)

        print("-" * len(header))
        total_line = f"{'TOTAL':<{name_w}}"
        for m in all_months:
            total_line += f"{int(month_totals[m]):>{col_w},}"
        total_line += f"{int(grand_total):>{col_w},}"
        print(total_line)

        print(f"\nNote: May 2026 bank statements not yet imported → May column absent.")
        print(f"      Rows tagged 'Staff - XXXXXXXXXX' = phone number not yet mapped to a name.")

        # ═══════════════════════════════════════════════════════════════
        # B) TENANT REFUND REPORT
        # ═══════════════════════════════════════════════════════════════

        # Source 1: refunds table
        ref_rows = await session.execute(text("""
            SELECT t.name, r.amount, r.refund_date, r.payment_mode, r.reason, r.status,
                   rm.room_number
            FROM refunds r
            JOIN tenancies tn ON tn.id = r.tenancy_id
            JOIN tenants t ON t.id = tn.tenant_id
            JOIN rooms rm ON rm.id = tn.room_id
            WHERE r.refund_date >= '2025-10-01'
              AND r.status != 'cancelled'
            ORDER BY t.name, r.refund_date
        """))
        ref_data = ref_rows.fetchall()

        # Source 2: checkout_records with deposit_refunded_amount
        cr_rows = await session.execute(text("""
            SELECT t.name, cr.deposit_refunded_amount, cr.deposit_refund_date,
                   cr.actual_exit_date, rm.room_number
            FROM checkout_records cr
            JOIN tenancies tn ON tn.id = cr.tenancy_id
            JOIN tenants t ON t.id = tn.tenant_id
            JOIN rooms rm ON rm.id = tn.room_id
            WHERE cr.deposit_refunded_amount > 0
              AND (cr.deposit_refund_date >= '2025-10-01'
                   OR cr.actual_exit_date >= '2025-10-01')
            ORDER BY t.name, cr.actual_exit_date
        """))
        cr_data = cr_rows.fetchall()

        print("\n\n" + "=" * 90)
        print("B) TENANT DEPOSIT & REFUNDS — All refunds Oct 2025 → now")
        print("=" * 90)

        # Merge both sources by tenant name
        all_refunds = {}  # name -> {room, total, details}

        for r in ref_data:
            name = r.name
            if name not in all_refunds:
                all_refunds[name] = {"room": r.room_number, "total": 0.0, "rows": []}
            all_refunds[name]["total"] += float(r.amount)
            all_refunds[name]["rows"].append({
                "date": str(r.refund_date),
                "amount": float(r.amount),
                "mode": r.payment_mode or "—",
                "reason": (r.reason or "")[:40],
                "source": "refunds",
                "status": r.status,
            })

        # checkout_records — only add if not already counted via refunds table
        # (to avoid double-count — refunds table is authoritative)
        co_names_in_refunds = set(all_refunds.keys())
        for r in cr_data:
            name = r.name
            if name in co_names_in_refunds:
                # Skip — already have from refunds table
                continue
            if name not in all_refunds:
                all_refunds[name] = {"room": r.room_number, "total": 0.0, "rows": []}
            all_refunds[name]["total"] += float(r.deposit_refunded_amount)
            all_refunds[name]["rows"].append({
                "date": str(r.deposit_refund_date or r.actual_exit_date),
                "amount": float(r.deposit_refunded_amount),
                "mode": "—",
                "reason": "deposit refund (checkout_records)",
                "source": "checkout_records",
                "status": "processed",
            })

        if not all_refunds:
            print("  No refund records found in this period.")
        else:
            print(f"\n  {'Tenant Name':<30} {'Room':<8} {'Total Refunded':>16}")
            print(f"  {'-'*30} {'-'*8} {'-'*16}")
            grand = 0.0
            for name in sorted(all_refunds.keys()):
                d = all_refunds[name]
                print(f"  {name:<30} {d['room']:<8} {int(d['total']):>16,}")
                for row in d["rows"]:
                    print(f"    {row['date']:12s}  {int(row['amount']):>10,}  {str(row['mode']):8s}  {row['reason']}")
                grand += d["total"]
            print(f"\n  {'TOTAL':<30} {'':8} {int(grand):>16,}")

        print()

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
