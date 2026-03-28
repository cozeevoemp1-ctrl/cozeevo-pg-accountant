"""
Create next month's tab in Google Sheet from TENANTS.
Receptionist enters Cash/UPI — rest auto-calculates via formulas.
Bot will also write to same columns (F=Cash, G=UPI) to stay in sync with DB.

Usage:
  python scripts/create_month.py              # next month
  python scripts/create_month.py APRIL 2026   # specific month
"""
import sys, math, calendar
sys.stdout.reconfigure(encoding='utf-8')
from datetime import date, datetime
import gspread
from google.oauth2.service_account import Credentials

SHEET_ID = "1Hp5dTM7TcDEq75jgHEjvwtBjOolruGfQ7CVMzVqjdGw"
CREDS = "credentials/gsheets_service_account.json"
MONTHS = ["JANUARY","FEBRUARY","MARCH","APRIL","MAY","JUNE","JULY",
          "AUGUST","SEPTEMBER","OCTOBER","NOVEMBER","DECEMBER"]


def pn(v):
    try: return float(str(v).replace(',', '').strip())
    except: return 0


def parse_date(v):
    if not v: return None
    s = str(v).strip()
    for fmt in ('%d-%m-%Y', '%Y-%m-%d', '%d/%m/%Y', '%Y-%m-%d %H:%M:%S'):
        try: return datetime.strptime(s, fmt).date()
        except: continue
    return None


def create_month(month_name, year):
    creds = Credentials.from_service_account_file(CREDS,
        scopes=['https://www.googleapis.com/auth/spreadsheets'])
    sp = gspread.authorize(creds).open_by_key(SHEET_ID)
    tab = f"{month_name} {year}"

    try:
        sp.worksheet(tab)
        print(f"{tab} already exists!")
        return
    except gspread.WorksheetNotFound:
        pass

    # Read TENANTS: 0=Room,1=Name,4=Building,6=Sharing,7=Checkin,8=Status,9=MonthlyRent,10=CurrentRent
    data = sp.worksheet("TENANTS").get_all_values()
    mi = MONTHS.index(month_name)
    days = calendar.monthrange(year, mi + 1)[1]
    m_start = date(year, mi + 1, 1)
    m_end = date(year, mi + 1, days)

    rows = []
    for t in data[1:]:
        status = str(t[8]).strip()
        if status not in ("Active", "No-show"):
            continue

        rent = pn(t[10]) or pn(t[9])
        checkin = parse_date(t[7])
        event = ""
        rent_due = rent

        if checkin and m_start <= checkin <= m_end:
            if status == "No-show":
                event = "NO-SHOW"
            else:
                event = "NEW CHECK-IN"
                rent_due = math.floor(rent * (days - checkin.day + 1) / days)

        if status == "No-show" and (not checkin or checkin > m_end):
            continue

        rows.append([t[0], t[1], t[4], t[6], rent_due, 0, 0, "", "", "", str(t[7]), event, "", 0, 0])

    print(f"Creating {tab}: {len(rows)} tenants...")
    ws = sp.add_worksheet(tab, rows=len(rows) + 10, cols=15)

    # Headers (row 1)
    headers = ["Room", "Name", "Building", "Sharing", "Rent Due",
               "Cash Paid", "UPI Paid", "Total Paid", "Balance",
               "Status", "Check-in", "Event", "Notes", "Chandra", "Lakshmi"]
    ws.update(values=[headers], range_name="A1")
    ws.format("A1:O1", {"textFormat": {"bold": True},
                         "backgroundColor": {"red": 0.84, "green": 0.92, "blue": 0.98}})

    # Data (row 2+)
    if rows:
        ws.update(values=rows, range_name=f"A2:O{1 + len(rows)}")

        # Formulas: H=Cash+UPI, I=Rent-Paid, J=Status
        formulas = []
        for i in range(len(rows)):
            r = i + 2
            formulas.append([
                f"=F{r}+G{r}",
                f"=E{r}-H{r}",
                f'=IF(I{r}<=0,"PAID",IF(H{r}>0,"PARTIAL","UNPAID"))',
            ])
        ws.update(values=formulas, range_name=f"H2:J{1 + len(rows)}",
                  value_input_option="USER_ENTERED")

    ws.freeze(rows=1)
    ws.format(f"E2:I{1 + len(rows)}", {"numberFormat": {"type": "NUMBER", "pattern": "#,##0"}})
    try: ws.set_basic_filter(f"A1:O{1 + len(rows)}")
    except: pass

    print(f"Done! {len(rows)} tenants with auto-formulas.")
    print("Enter Cash (F) or UPI (G) — Total/Balance/Status auto-calculate.")


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        m, y = sys.argv[1].upper(), int(sys.argv[2])
    else:
        today = date.today()
        m = MONTHS[today.month % 12]
        y = today.year + (1 if today.month == 12 else 0)

    create_month(m, y)
