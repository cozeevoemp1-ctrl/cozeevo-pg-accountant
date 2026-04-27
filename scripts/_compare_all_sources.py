"""
Quick comparison: DB vs Ops Sheet (monthly tabs) vs Source sheet (History tab).
Run as: python scripts/_compare_all_sources.py
"""
import asyncio, os, sys, re
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

import gspread
from google.oauth2.service_account import Credentials
from sqlalchemy import select, func
from src.database.db_manager import init_engine, get_session
from src.database.models import Payment, PaymentFor, PaymentMode

CREDENTIALS_PATH = "credentials/gsheets_service_account.json"
OPS_SHEET_ID    = os.getenv("GSHEETS_SHEET_ID", "1Hp5dTM7TcDEq75jgHEjvwtBjOolruGfQ7CVMzVqjdGw")
SOURCE_SHEET_ID = "1jOCVBkVurLNaht9HYKR6SFqGCciIoMWeOJkfKF9essk"

from datetime import date
MONTHS = [
    ("December 2025", "DECEMBER 2025", date(2025, 12, 1)),
    ("January 2026",  "JANUARY 2026",  date(2026,  1, 1)),
    ("February 2026", "FEBRUARY 2026", date(2026,  2, 1)),
    ("March 2026",    "MARCH 2026",    date(2026,  3, 1)),
    ("April 2026",    "APRIL 2026",    date(2026,  4, 1)),
]

def pn(val) -> int:
    if val is None or str(val).strip() in ("", "-"): return 0
    try: return int(float(str(val).replace(",", "").strip()))
    except: return 0

def _open(sheet_id):
    scopes = ["https://www.googleapis.com/auth/spreadsheets","https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=scopes)
    return gspread.authorize(creds).open_by_key(sheet_id)

def read_ops_tab(sh, tab_name):
    """Sum cash + upi columns from a monthly ops tab using header lookup."""
    try:
        ws = sh.worksheet(tab_name)
    except:
        return None, None
    rows = ws.get_all_values()
    col_cash = col_upi = data_start = None
    for idx, row in enumerate(rows):
        h = [str(c).strip().lower() for c in row]
        if h and h[0] == "room":
            col_cash = h.index("cash") if "cash" in h else None
            col_upi  = h.index("upi")  if "upi"  in h else None
            data_start = idx + 1
            break
    if col_cash is None: return None, None
    cash = upi = 0
    for row in rows[data_start:]:
        if len(row) > max(col_cash, col_upi):
            raw_room = str(row[0]).strip()
            raw_name = str(row[1]).strip() if len(row) > 1 else ""
            if not raw_room or not raw_name: continue
            cash += pn(row[col_cash])
            upi  += pn(row[col_upi])
    return cash, upi

def read_source_history(sh):
    """Read History tab of source sheet. Returns dict month_label -> (cash, upi)."""
    try:
        ws = sh.worksheet("History")
    except:
        try: ws = sh.get_worksheet(0)
        except: return {}
    rows = ws.get_all_values()
    if not rows: return {}

    # Find header row
    header = None
    header_idx = 0
    for i, row in enumerate(rows):
        low = [str(c).strip().lower() for c in row]
        # Look for a row that has recognizable month column names
        joined = " ".join(low)
        if "jan" in joined or "feb" in joined or "march" in joined or "cash" in joined:
            header = low
            header_idx = i
            break
    if header is None:
        return {}

    # Find column indices semantically
    result = {}
    def find_col(keywords):
        for i, h in enumerate(header):
            if all(k in h for k in keywords):
                return i
        return None

    # Source sheet columns: "until jan cash", "until jan upi", "feb cash", "feb upi", "march cash", "march upi"
    cols = {
        "jan_cash":  find_col(["jan", "cash"]),
        "jan_upi":   find_col(["jan", "upi"]),
        "feb_cash":  find_col(["feb", "cash"]),
        "feb_upi":   find_col(["feb", "upi"]),
        "mar_cash":  find_col(["march", "cash"]) or find_col(["mar", "cash"]),
        "mar_upi":   find_col(["march", "upi"])  or find_col(["mar", "upi"]),
        "apr_cash":  find_col(["apr", "cash"]),
        "apr_upi":   find_col(["apr", "upi"]),
        "dec_cash":  find_col(["dec", "cash"]),
        "dec_upi":   find_col(["dec", "upi"]),
    }
    print(f"  Source sheet columns found: {cols}")

    totals = {k: 0 for k in cols}
    for row in rows[header_idx+1:]:
        for k, ci in cols.items():
            if ci is not None and len(row) > ci:
                totals[k] += pn(row[ci])

    # "until jan" = Dec + Jan combined
    result = {
        "dec": (totals.get("dec_cash", 0), totals.get("dec_upi", 0)),
        "jan": (totals.get("jan_cash", 0), totals.get("jan_upi", 0)),
        "feb": (totals.get("feb_cash", 0), totals.get("feb_upi", 0)),
        "mar": (totals.get("mar_cash", 0), totals.get("mar_upi", 0)),
        "apr": (totals.get("apr_cash", 0), totals.get("apr_upi", 0)),
    }
    return result

async def main():
    init_engine(os.getenv("DATABASE_URL"))

    # 1. DB totals
    db = {}
    async with get_session() as s:
        rows = (await s.execute(
            select(Payment.period_month, Payment.payment_mode, func.sum(Payment.amount).label("t"))
            .where(Payment.is_void == False, Payment.for_type == PaymentFor.rent)
            .group_by(Payment.period_month, Payment.payment_mode)
        )).all()
    for r in rows:
        pm = r.period_month
        if pm is None: continue
        mode = r.payment_mode.value if hasattr(r.payment_mode,"value") else str(r.payment_mode)
        db.setdefault(pm, {"cash":0,"upi":0})
        db[pm][mode] = int(r[2] or 0)

    # 2. Ops sheet
    print("Reading Ops sheet tabs...")
    ops_sh = _open(OPS_SHEET_ID)
    ops = {}
    for label, tab_name, period in MONTHS:
        c, u = read_ops_tab(ops_sh, tab_name)
        ops[period] = (c, u)
        status = f"Cash {c:,}  UPI {u:,}" if c is not None else "TAB NOT FOUND"
        print(f"  {tab_name}: {status}")

    # 3. Source sheet
    print("\nReading Source sheet (History tab)...")
    src_sh = _open(SOURCE_SHEET_ID)
    src = read_source_history(src_sh)

    src_by_period = {
        date(2025,12,1): src.get("dec",(None,None)),
        date(2026, 1,1): src.get("jan",(None,None)),
        date(2026, 2,1): src.get("feb",(None,None)),
        date(2026, 3,1): src.get("mar",(None,None)),
        date(2026, 4,1): src.get("apr",(None,None)),
    }

    # Print comparison
    print()
    print(f"{'Month':<18} {'Source':<12} {'DB Cash':>10} {'DB UPI':>10} {'DB Total':>10} | {'OpsSheet Cash':>13} {'OpsSheet UPI':>12} {'OpsSheet Total':>14} | {'SrcSheet Cash':>13} {'SrcSheet UPI':>12}")
    print("-"*140)
    for label, tab_name, period in MONTHS:
        db_cash = db.get(period, {}).get("cash", 0)
        db_upi  = db.get(period, {}).get("upi", 0)
        db_tot  = db_cash + db_upi

        ops_cash, ops_upi = ops.get(period, (None, None))
        ops_tot = (ops_cash or 0) + (ops_upi or 0)

        src_cash, src_upi = src_by_period.get(period, (None, None))

        ops_str  = f"{ops_cash:>13,}  {ops_upi:>12,}  {ops_tot:>14,}" if ops_cash is not None else f"{'N/A':>13}  {'N/A':>12}  {'N/A':>14}"
        src_str  = f"{src_cash:>13,}  {src_upi:>12,}" if src_cash is not None else f"{'N/A':>13}  {'N/A':>12}"

        match_ops = "✓" if ops_cash is not None and ops_cash == db_cash and ops_upi == db_upi else "✗"
        match_src = "✓" if src_cash is not None and src_cash == db_cash and src_upi == db_upi else "?"

        print(f"{label:<18} {match_ops}  {match_src:<2}  {db_cash:>10,} {db_upi:>10,} {db_tot:>10,} | {ops_str} | {src_str}")

if __name__ == "__main__":
    asyncio.run(main())
