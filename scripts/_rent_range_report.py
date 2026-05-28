"""
UPI transaction range report from Google Sheets.
For each UPI column (FEB UPI, March UPI, etc.), reads every individual cell value
and buckets the payment amount: <15k, 15k-20k, >20k.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dotenv import load_dotenv
load_dotenv()

import gspread
from google.oauth2.service_account import Credentials
from collections import defaultdict

CREDENTIALS_PATH = os.path.join("credentials", "gsheets_service_account.json")
scopes = ["https://www.googleapis.com/auth/spreadsheets"]
creds = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=scopes)
gc = gspread.authorize(creds)

shA = gc.open_by_key("1jOCVBkVurLNaht9HYKR6SFqGCciIoMWeOJkfKF9essk")
shB = gc.open_by_key("1Vr_fSIOuuKBK4MWF-FVqgAIUPbqun3POszaXYfj-Ea0")

def parse_num(v):
    try: return float(str(v).replace(",", "").strip())
    except: return 0.0

def bucket(amt):
    if amt <= 0:       return None
    if amt < 15000:    return "below_15k"
    if amt <= 20000:   return "15k_to_20k"
    return "above_20k"

# Only match UPI columns by exact header name
UPI_HEADER_MAP = {
    "until jan upi": "2025-11",
    "feb upi":       "2026-02",
    "march upi":     "2026-03",
    "april upi":     "2026-04",
    "may upi":       "2026-05",
    "june upi":      "2026-06",
}

# month -> {bucket: [amounts]}
monthly = defaultdict(lambda: defaultdict(list))

def process_sheet(ws, label):
    rows = ws.get_all_values()
    if not rows:
        return
    headers = rows[0]
    upi_cols = {}
    for i, h in enumerate(headers):
        h_low = h.strip().lower()
        if h_low in UPI_HEADER_MAP:
            upi_cols[i] = UPI_HEADER_MAP[h_low]

    if not upi_cols:
        return
    print(f"  {label}: UPI cols = {[(i+1, headers[i], mk) for i,mk in upi_cols.items()]}")

    for row in rows[1:]:
        name = row[1].strip() if len(row) > 1 else ""
        if not name or name.lower() in ("name", ""):
            continue
        for col_idx, month_key in upi_cols.items():
            if col_idx >= len(row):
                continue
            amt = parse_num(row[col_idx])
            bkt = bucket(amt)
            if bkt:
                monthly[month_key][bkt].append(amt)

process_sheet(shA.worksheet("History"),   "Sheet-A/History")
process_sheet(shB.worksheet("Long term"), "Sheet-B/Long term")

MONTH_LABELS = {
    "2025-11": "Nov-Jan*", "2026-02": "Feb 2026", "2026-03": "Mar 2026",
    "2026-04": "Apr 2026", "2026-05": "May 2026",  "2026-06": "Jun 2026",
}
FY_MAP = {
    "2025-11": "FY25-26", "2026-02": "FY25-26", "2026-03": "FY25-26",
    "2026-04": "FY26-27", "2026-05": "FY26-27",  "2026-06": "FY26-27",
}

months_ordered = sorted(monthly.keys())

print()
print(f"{'Month':<12}  {'<15k':>5}  {'15k-20k':>8}  {'>20k':>5}  {'Total':>6}  {'UPI Total':>12}")
print("-" * 60)

fy_data = defaultdict(lambda: defaultdict(list))

for m in months_ordered:
    d = monthly[m]
    b1 = d.get("below_15k",   [])
    b2 = d.get("15k_to_20k",  [])
    b3 = d.get("above_20k",   [])
    total_amt = sum(b1) + sum(b2) + sum(b3)
    lbl = MONTH_LABELS.get(m, m)
    print(f"{lbl:<12}  {len(b1):>5}  {len(b2):>8}  {len(b3):>5}  {len(b1)+len(b2)+len(b3):>6}  {int(total_amt):>12,}")
    fy = FY_MAP.get(m, "Other")
    for bk in ["below_15k", "15k_to_20k", "above_20k"]:
        fy_data[fy][bk].extend(d.get(bk, []))

print()
print("Financial Year:")
print(f"{'FY':<12}  {'<15k':>5}  {'15k-20k':>8}  {'>20k':>5}  {'Total':>6}  {'UPI Total':>12}")
print("-" * 60)
for fy in ["FY25-26", "FY26-27"]:
    d = fy_data[fy]
    b1 = d.get("below_15k",  [])
    b2 = d.get("15k_to_20k", [])
    b3 = d.get("above_20k",  [])
    total_amt = sum(b1) + sum(b2) + sum(b3)
    print(f"{fy:<12}  {len(b1):>5}  {len(b2):>8}  {len(b3):>5}  {len(b1)+len(b2)+len(b3):>6}  {int(total_amt):>12,}")

print()
print("* Nov-Jan UPI is a combined column in the sheet (not split per month)")
