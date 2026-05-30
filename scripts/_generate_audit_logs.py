"""
Generate two permanent audit logs from bank_transactions:
  docs/DEPOSIT_REFUND_AUDIT.md  — all deposit refunds ever paid
  docs/SALARY_PAYMENT_AUDIT.md  — all staff/salary payments

Run after every bank statement import:
    python scripts/_generate_audit_logs.py
"""
import asyncio, os, sys
from collections import defaultdict
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

# ── Deposit refund name resolution ────────────────────────────────────────────
REFUND_DESC_MAP = [
    ("sanidhyasrivastava",    "Sanidhya Srivastava"),
    ("adithya3sri",           "Adithya (103)"),
    ("arunphilip",            "Arun Philip (booking cancel)"),
    ("majji divya",           "Majji Divya (day-wise)"),
    ("premstealer",           "Prem (day-wise)"),
    ("sethuraman",            "Sethuraman (101)"),
    ("chandrasekhar1996",     "Chandrasekhar"),
    ("t.srinivasa",           "T Srinivasa"),
    ("9518874547",            "Unknown-9518874547"),
    ("akshaybhagat",          "Akshay Bhagat (310)"),
    ("bharath",               "Bharath (cancelled)"),
    ("anurag.cerpa",          "Anurag (104)"),
    ("sameer and rishika",    "Sameer & Rishika (204)"),
    ("nitinkalburgi",         "Nitin (booking cancel)"),
    ("sreelakshmyaj",         "Sree Lakshmy AJ"),
    ("anwasha pal",           "Anwasha Pal (401)"),
    ("sourabhmahra",          "Sorabh Mahra"),
    ("omtpkjh456",            "Omkar"),
    ("yogeshwaran",           "Yogeshwaran (411)"),
    ("anandhu",               "Anandhu (208)"),
    ("gokul harish",          "Gokul Harish (104)"),
    ("7661991929",            "Unknown-7661991929"),
    ("sherlyin",              "Sherylin M Rajan (210)"),
    ("ankitdude",             "Ankit"),
    ("camprithiv",            "Rithiv"),
    ("anudeepbishtab",        "Anudeep"),
    ("akshaygupt",            "Akshay Gupta (219)"),
    ("ksshyamreddy",          "K S Shyam Reddy"),
    ("soham.mundhada",        "Soham Vijay (219)"),
    ("tejasjallapelli3-1",    "Tejas Jallapelli (516)"),
    ("tejasjallapelli3@",     "Tejas Jallapelli (516)"),
    ("swamivenkatesh",        "Swami Venkatesh"),
    ("6290322013",            "Subhadeep Sikdar (413)"),
    ("8816019354",            "Dhruv"),
    ("9947814505",            "Unknown-9947814505"),
    ("9904388966",            "Adithya Saraf (609)"),
    ("amalsreenimj",          "Amal (112)"),
    ("anumola yoga anil",     "Yogaanil Anumola (606)"),
    ("aahil rafiq",           "Aahil Rafiq (606)"),
    ("215 lakshmi priya",     "Lakshmi Priya (215)"),
    ("lakshmidaya",           "Lakshmi Priya (215)"),
    ("kuhanmohan",            "Kuhan Mohan (411)"),
    ("hafiz",                 "Hafiz Khan (308)"),
    ("7842266579",            "Siva Kumar (G07)"),
    ("9390933531",            "Vijay Kumar"),
    ("umar1256",              "Mohammed Umar (G09)"),
    ("gotham refund",         "Gotham"),
    ("rishwanth",             "Rishwanth"),
    ("snirmal",               "Nirmal Kumar (612)"),
    ("sakshi",                "Sakshi"),
    ("akshyarathna",          "Akshayaratna (610)"),
    ("satish",                "Satish Waghela (621)"),
    ("ramakanth",             "Yatam Ramakanth (520)"),
    ("shaurya shah",          "Shaurya Shah (624)"),
    ("p deepa",               "P Deepa"),
    ("nakul.gupta66",         "Nakul Gupta (521)"),
    ("shashank 521",          "Shashank (521)"),
    ("refund for booking",    "Booking Cancel"),
    ("sujalj906",             "Sujal Jaiswal (217)"),
    ("iamsoumyaagrawal",      "Soumya Agarwal (206)"),
    ("6391679333",            "Shubhi Vishnoi (304)"),
    ("7981501263",            "Bhanu Prakash"),
    ("nehabhanarkar",         "Neha Pramod (210)"),
    ("adnan doshi",           "Adnan Doshi (510)"),
    ("ssanjay2305",           "Sanjay (520)"),
    ("9482874334",            "Shashank B V"),
    ("8840068630",            "Shubham Mishra (514)"),
    ("radhika",               "Radhika"),
]

def refund_name(sub, desc):
    combined = (sub + " " + desc).lower()
    if sub and sub != "Other Refund / Exit":
        return sub
    for kw, name in REFUND_DESC_MAP:
        if kw.lower() in combined:
            return name
    return "UNKNOWN: " + desc[40:80]


# ── Salary name resolution ─────────────────────────────────────────────────────
SALARY_UPI_MAP = [
    ("7680814628",      "Lokesh (Receptionist)"),
    ("9444296681",      "Prabhakaran (Manager)"),
    ("volipi.l",        "Volipi (Cleaner)"),
    ("rockshield",      "Rock Shield (Security Contractor)"),
    ("bn895975",        "Bhukesh"),
    ("6202601070",      "Vivek"),
    ("6287677379",      "Vivek"),
    ("8905122862",      "Kshama (Staff)"),
    ("rampukarmandal",  "Rampukar (Labour)"),
    ("8837062479",      "Sreeraj (Housekeeping)"),
    ("salamtajamul",    "Salam Tajamul (Housekeeping)"),
    ("manishaspundir",  "Manisha Pundir (Housekeeping)"),
    ("9071242117",      "Housekeeping Staff"),
    ("9611622637",      "Housekeeping Staff"),
    ("9398545495",      "Housekeeping Staff"),
    ("sarojrout",       "Saroj Rout (Housekeeping)"),
    ("dilliprout",      "Dilli Rout (Housekeeping)"),
    ("imranaaazmi",     "Imran Azmi (Housekeeping)"),
    ("rabhasoma",       "Rabha Soma (Housekeeping)"),
    ("sanket.wankhede", "Sanket Wankhede"),
    ("biplab141",       "Biplab (Staff)"),
    ("bikeydey",        "Bikey Dey (Staff)"),
    ("kn.ravikumar",    "Ravi Kumar"),
    ("sachindivya",     "Sachin Divya"),
    ("sandeepgowda",    "Sandeep Gowda"),
    ("gudadesh",        "Gudadesh (Contractor)"),
    ("9102937483",      "Abhisek Mandal (Staff)"),
    ("9110460729",      "Ram Chandra (Cook/Staff)"),
    ("9342205440",      "Gas Pipeline Welding [RECLASSIFIED→Maintenance]"),
    ("9880401360",      "Staff-9880401360"),
    ("swamisarang",     "Swami Sarang"),
    ("akmalakmal",      "Akmal (Staff)"),
    ("vishal521",       "Vishal (Staff)"),
    ("kutubuddinku",    "Kutubuddin (Staff)"),
    ("8132966734",      "Staff-8132966734"),
    ("6362243208",      "Ambareesh (Cleaner)"),
    ("8409903591",      "Staff-8409903591"),
    ("xxxx5021",        "Joshi Arjunbhai (Cleaner)"),
    ("xxxx6948",        "Joshi Arjunbhai (Cleaner)"),
    ("joshi arjunbha",  "Joshi Arjunbhai (Cleaner)"),
]

def salary_name(sub, desc):
    combined = ((sub or "") + " " + (desc or "")).lower()
    for pattern, name in SALARY_UPI_MAP:
        if pattern.lower() in combined:
            return name
    if sub and len(sub) < 45 and not sub.startswith("UPI/"):
        return sub[:40]
    return (desc or "Unknown")[:40]


# ── Cash salary payments (not in bank — hardcoded in pnl_builder.py) ──────────
# These are petty cash / hand payments that were manually verified and added to
# the frozen P&L figures in src/reports/pnl_builder.py.
# Update this list whenever pnl_builder.py Staff & Labour figures are adjusted.
# Source comment in pnl_builder.py line 85.
CASH_SALARY_ROWS = [
    # (date_str, name, amount, note)
    ("2025-12-31", "Petty Wages (cash)",        500,    "Dec petty wages — pnl_builder hardcoded"),
    ("2026-01-31", "Petty Wages (cash)",         790,   "Jan petty wages — pnl_builder hardcoded"),
    ("2026-02-28", "Petty Wages (cash)",         580,   "Feb petty wages — pnl_builder hardcoded"),
    ("2026-03-31", "Lokesh + mother (Volipi) — cash salary", 29000, "Mar salary cash — Lokesh + his mother; pnl_builder hardcoded; confirmed Kiran 2026-05-30"),
    ("2026-03-31", "Vivek, Ravi, Saurav, Cook, helpers — cash labour", 32600, "Mar cash labour (no UPI — recorded from image; changelog v1.75.43)"),
]


def md_table_row(*cells):
    return "| " + " | ".join(str(c) for c in cells) + " |"


async def main():
    from datetime import date
    today = str(date.today())

    async with Session() as session:
        # ── Deposit refunds ───────────────────────────────────────────────────
        ref_rows = await session.execute(text("""
            SELECT txn_date, account_name, amount, sub_category, description
            FROM bank_transactions
            WHERE category = 'Tenant Deposit Refund' AND txn_type = 'expense'
            ORDER BY txn_date, amount DESC
        """))
        refunds = ref_rows.fetchall()

        # ── Salary payments ───────────────────────────────────────────────────
        sal_rows = await session.execute(text("""
            SELECT txn_date, account_name, amount, sub_category, description
            FROM bank_transactions
            WHERE category = 'Staff & Labour' AND txn_type = 'expense'
              AND txn_date >= '2025-10-01'
            ORDER BY txn_date, amount DESC
        """))
        salaries = sal_rows.fetchall()

    # ── Write DEPOSIT_REFUND_AUDIT.md ──────────────────────────────────────────
    lines = [
        "# Deposit Refund Audit Log",
        "",
        "**Source:** `bank_transactions` WHERE `category = 'Tenant Deposit Refund'`  ",
        "**Rule:** Re-run `python scripts/_generate_audit_logs.py` after every bank CSV import. This file is the single source of truth for all deposit refunds ever paid.",
        f"**Last updated:** {today}",
        "",
        "| # | Date | Account | Name | Amount |",
        "|---|------|---------|------|-------:|",
    ]
    ref_total = 0
    ref_monthly = defaultdict(float)
    for i, r in enumerate(refunds, 1):
        name = refund_name(r.sub_category or "", r.description or "")
        lines.append(f"| {i} | {r.txn_date} | {r.account_name} | {name} | {int(r.amount):,} |")
        ref_total += float(r.amount)
        ref_monthly[r.txn_date.strftime("%b %Y")] += float(r.amount)
    lines.append(f"| | | | **TOTAL** | **{int(ref_total):,}** |")
    lines += [
        "",
        "## Monthly Summary",
        "",
        "| Month | Total |",
        "|-------|------:|",
    ]
    for mo, amt in sorted(ref_monthly.items()):
        lines.append(f"| {mo} | {int(amt):,} |")
    lines.append(f"| **TOTAL** | **{int(ref_total):,}** |")

    with open("docs/DEPOSIT_REFUND_AUDIT.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"docs/DEPOSIT_REFUND_AUDIT.md — {len(refunds)} rows, total={int(ref_total):,}")

    # ── Write SALARY_PAYMENT_AUDIT.md ──────────────────────────────────────────
    # Merge bank rows + cash rows, sorted by date
    from datetime import datetime as dt
    all_salary_rows = []
    for r in salaries:
        all_salary_rows.append({
            "date": r.txn_date,
            "account": r.account_name,
            "name": salary_name(r.sub_category or "", r.description or ""),
            "amount": float(r.amount),
            "note": "",
        })
    for date_str, name, amount, note in CASH_SALARY_ROWS:
        all_salary_rows.append({
            "date": dt.strptime(date_str, "%Y-%m-%d").date(),
            "account": "CASH",
            "name": name,
            "amount": float(amount),
            "note": note,
        })
    all_salary_rows.sort(key=lambda x: (x["date"], -x["amount"]))

    lines2 = [
        "# Salary & Staff Payment Audit Log",
        "",
        "**Sources:**",
        "- `bank_transactions` WHERE `category = 'Staff & Labour'` (bank transfers)",
        "- `CASH_SALARY_ROWS` in this script (cash payments hardcoded from pnl_builder.py)",
        "",
        "**Rule:** Re-run `python scripts/_generate_audit_logs.py` after every bank CSV import or pnl_builder update.",
        f"**Last updated:** {today}",
        "",
        "| # | Date | Account | Name | Amount |",
        "|---|------|---------|------|-------:|",
    ]
    sal_total = 0
    sal_monthly = defaultdict(float)
    for i, r in enumerate(all_salary_rows, 1):
        lines2.append(f"| {i} | {r['date']} | {r['account']} | {r['name']} | {int(r['amount']):,} |")
        sal_total += r["amount"]
        sal_monthly[r["date"].strftime("%b %Y")] += r["amount"]
    lines2.append(f"| | | | **TOTAL** | **{int(sal_total):,}** |")
    lines2 += [
        "",
        "## Monthly Summary",
        "",
        "| Month | Total |",
        "|-------|------:|",
    ]
    for mo, amt in sorted(sal_monthly.items()):
        lines2.append(f"| {mo} | {int(amt):,} |")
    lines2.append(f"| **TOTAL** | **{int(sal_total):,}** |")

    with open("docs/SALARY_PAYMENT_AUDIT.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines2) + "\n")
    print(f"docs/SALARY_PAYMENT_AUDIT.md — {len(salaries)} rows, total={int(sal_total):,}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
