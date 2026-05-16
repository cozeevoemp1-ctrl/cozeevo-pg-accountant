"""Show sheet columns for mismatching tenants to understand April Balance formula."""
import os, re, sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv; load_dotenv()

import gspread
from google.oauth2.service_account import Credentials

SOURCE_SHEET_ID = "1Vr_fSIOuuKBK4MWF-FVqgAIUPbqun3POszaXYfj-Ea0"
CREDS_FILE = "credentials/gsheets_service_account.json"

def pn(v):
    if not v: return 0
    try: return max(0, int(float(str(v).replace(",", ""))))
    except: return 0

names_to_check = [
    "Claudin", "Arun dharshini", "Abhiram", "Sai Shankar", "Prashanth",
    "Ajay Mohan", "Chandraprakash", "Akshay Kothari", "Delvin Raj",
    "Omkar deodher", "Sachin kumar", "Veena", "Tanishka", "Preesha",
    "Shivam Nath", "Aldrin", "Abhishek Charan", "Abhishek Vishwakarma",
    "Swarup", "Sachin"
]

scopes = ["https://www.googleapis.com/auth/spreadsheets",
          "https://www.googleapis.com/auth/drive"]
creds = Credentials.from_service_account_file(CREDS_FILE, scopes=scopes)
gc = gspread.authorize(creds)
ws = gc.open_by_key(SOURCE_SHEET_ID).worksheet("Long term")
all_rows = ws.get_all_values()
header = all_rows[0]
col = {h.strip().lower(): i for i, h in enumerate(header)}

print(f"{'Name':<30} {'MarBal':>8} {'Apr':>8} {'AprCsh':>8} {'AprUPI':>8} {'AprBal':>8} {'JunBal':>8}  calc_check")
print("-" * 100)
for row in all_rows[1:]:
    name = row[col["name"]].strip()
    if not name: continue
    if not any(n.lower() in name.lower() for n in names_to_check): continue
    mar_bal  = pn(row[col.get("march balance", 99)])
    apr_tot  = pn(row[col.get("april", 99)])
    apr_cash = pn(row[col.get("april cash", 99)])
    apr_upi  = pn(row[col.get("april upi", 99)])
    apr_bal  = pn(row[col.get("april balance", 99)])
    jun_bal  = pn(row[col.get("june balance", 99)])
    calc = apr_tot - apr_cash - apr_upi  # expected apr_bal if April = cumulative
    print(f"{name:<30} {mar_bal:>8,} {apr_tot:>8,} {apr_cash:>8,} {apr_upi:>8,} {apr_bal:>8,} {jun_bal:>8,}  calc={calc:,}")
