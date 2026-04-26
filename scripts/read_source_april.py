"""Read April Balance from source sheet and print comparison."""
import sys, os
sys.stdout.reconfigure(encoding="utf-8")
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv; load_dotenv()
import gspread
from google.oauth2.service_account import Credentials

CREDS_PATH = "credentials/gsheets_service_account.json"
SOURCE_ID  = os.environ["SOURCE_SHEET_ID"]
scopes = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = Credentials.from_service_account_file(CREDS_PATH, scopes=scopes)
gc    = gspread.authorize(creds)
ss    = gc.open_by_key(SOURCE_ID)
ws    = ss.worksheet("Long term")
rows  = ws.get_all_values()

def pn(v):
    try: return float(str(v).replace(",", "").strip() or 0)
    except: return 0.0

# Col indices (0-based):
# Room=0  Name=1  Checkin/out=16(Q)  April_status=19(T)
# March_bal=20(U)  April_cash=21(V)  April_upi=22(W)  April_balance=23(X)

total_bal = 0
partial_count = paid_count = noshow_count = exit_count = 0

HDR = f"{'Room':<6} {'Name':<24} {'Apr Status':<12} {'Cash':>7} {'UPI':>7} {'Balance':>8}"
print(HDR)
print("-" * 70)

for row in rows[1:]:
    if len(row) < 24:
        continue
    room       = row[0].strip()
    name       = row[1].strip()
    apr_status = row[19].strip().upper()
    apr_cash   = pn(row[21])
    apr_upi    = pn(row[22])
    apr_bal    = pn(row[23])

    if not room or not name:
        continue

    total_bal += apr_bal
    if apr_status == "PAID":
        paid_count += 1
    elif apr_status in ("PARTIAL", "PART"):
        partial_count += 1
    elif "NO" in apr_status and "SHOW" in apr_status:
        noshow_count += 1
    elif apr_status == "EXIT":
        exit_count += 1

    if apr_bal > 0 or "NO" in apr_status:
        print(f"{room:<6} {name[:24]:<24} {apr_status:<12} {int(apr_cash):>7,} {int(apr_upi):>7,} {int(apr_bal):>8,}")

print("-" * 70)
print(f"PAID:{paid_count}  PARTIAL:{partial_count}  NO-SHOW:{noshow_count}  EXIT:{exit_count}")
print(f"Total April Balance (source sheet): Rs.{int(total_bal):,}")
