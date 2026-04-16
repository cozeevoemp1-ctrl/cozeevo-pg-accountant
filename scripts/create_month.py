"""
Create next month's tab in Google Sheet.
Reads active tenants from TENANTS, carries forward balance from previous month.

First month check-in: Rent Due = rent + deposit (deposit includes maintenance)
Month 2+: Rent Due = agreed rent only
Prev Due = previous month's unpaid balance

Usage:
  python scripts/create_month.py              # next month
  python scripts/create_month.py MAY 2026     # specific month
"""
import sys, math, calendar
sys.stdout.reconfigure(encoding='utf-8')
from datetime import date, datetime

# Use the project's gsheets module for consistent access
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv()

from src.integrations.gsheets import (
    _get_worksheet_sync, MONTHLY_HEADERS, _safe_parse_numeric
)
import gspread

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


def _header_map(headers):
    """Build lowercase header → column index mapping."""
    return {h.strip().lower(): i for i, h in enumerate(headers)}


def _col(hmap, name, default=-1):
    """Get column index by header name (case-insensitive)."""
    return hmap.get(name.strip().lower(), default)


def create_month(month_name, year):
    tab = f"{month_name} {year}"

    # Check if tab already exists
    try:
        _get_worksheet_sync(tab)
        print(f"{tab} already exists!")
        return
    except gspread.WorksheetNotFound:
        pass

    # ── Read TENANTS (header-based) ─────────────────────────────────────────
    tenants_ws = _get_worksheet_sync("TENANTS")
    t_data = tenants_ws.get_all_values()
    t_headers = t_data[0] if t_data else []
    th = _header_map(t_headers)

    mi = MONTHS.index(month_name)
    month_num = mi + 1
    days = calendar.monthrange(year, month_num)[1]
    m_start = date(year, month_num, 1)
    m_end = date(year, month_num, days)

    # ── Read previous month's balance for carry-forward ─────────────────────
    prev_balances = {}  # key: (room, name) → balance
    prev_mi = mi - 1
    prev_year = year
    if prev_mi < 0:
        prev_mi = 11
        prev_year -= 1
    prev_tab_name = f"{MONTHS[prev_mi]} {prev_year}"
    try:
        prev_ws = _get_worksheet_sync(prev_tab_name)
        prev_data = prev_ws.get_all_values()
        if len(prev_data) > 4:
            prev_headers = prev_data[3]  # row 4 = headers
            ph = _header_map(prev_headers)
            for row in prev_data[4:]:
                if not row[0]:
                    continue
                room = str(row[0]).strip()
                name = str(row[_col(ph, "name", 1)]).strip() if _col(ph, "name") >= 0 else ""
                bal = _safe_parse_numeric(row[_col(ph, "balance", 9)] if _col(ph, "balance") >= 0 and _col(ph, "balance") < len(row) else "0")
                status = str(row[_col(ph, "status", 10)] if _col(ph, "status") >= 0 and _col(ph, "status") < len(row) else "").upper().strip()
                if status in ("EXIT", "CANCELLED"):
                    continue
                if bal > 0:
                    prev_balances[(room, name)] = bal
        print(f"Loaded {len(prev_balances)} carry-forward balances from {prev_tab_name}")
    except gspread.WorksheetNotFound:
        print(f"No previous month tab '{prev_tab_name}' — prev dues = 0 for all")

    # ── Build rows from TENANTS ─────────────────────────────────────────────
    rows = []
    for t in t_data[1:]:
        if not t[0]:
            continue

        status = str(t[_col(th, "status", 8)]).strip().lower()
        if status not in ("active", "no-show", "no_show"):
            continue

        room = str(t[_col(th, "room", 0)]).strip()
        name = str(t[_col(th, "name", 1)]).strip()
        phone = str(t[_col(th, "phone", 2)]).strip()
        building = str(t[_col(th, "building", 4)]).strip()
        sharing = str(t[_col(th, "sharing", 6)]).strip()
        checkin_str = str(t[_col(th, "check-in", 7)]).strip()
        agreed_rent = pn(t[_col(th, "agreed rent", 9)])
        deposit = pn(t[_col(th, "deposit", 10)])

        checkin = parse_date(checkin_str)
        event = ""
        rent_due = agreed_rent
        deposit_due = 0  # only first month

        # First month check-in: deposit in separate column
        is_first_month = checkin and m_start <= checkin <= m_end
        if is_first_month:
            if status in ("no-show", "no_show"):
                event = "NO SHOW"
            else:
                event = "CHECKIN"
                # Prorate rent for mid-month check-in
                rent_due = math.floor(agreed_rent * (days - checkin.day + 1) / days)
            deposit_due = deposit  # separate column

        # Skip no-shows whose check-in is after this month
        if status in ("no-show", "no_show") and (not checkin or checkin > m_end):
            continue

        # Carry forward previous month's balance
        prev_due = prev_balances.get((room, name), 0)

        # Phone with apostrophe prefix (text format)
        phone_txt = f"'{phone}" if phone else ""

        rows.append({
            "room": room,
            "name": name,
            "phone": phone_txt,
            "building": building,
            "sharing": sharing,
            "rent due": rent_due,
            "deposit due": deposit_due,
            "cash": "",
            "upi": "",
            "total paid": 0,
            "balance": rent_due + deposit_due + prev_due,
            "status": "UNPAID",
            "check-in": checkin_str,
            "notice date": "",
            "event": event,
            "notes": "",
            "prev due": prev_due if prev_due > 0 else 0,
            "entered by": "",
        })

    print(f"Creating {tab}: {len(rows)} tenants...")

    # ── Create worksheet ────────────────────────────────────────────────────
    from src.integrations.gsheets import _get_spreadsheet_sync
    sp = _get_spreadsheet_sync()
    ws = sp.add_worksheet(tab, rows=len(rows) + 10, cols=len(MONTHLY_HEADERS))

    # Use MONTHLY_HEADERS as canonical source (row 4)
    headers_lower = [h.strip().lower() for h in MONTHLY_HEADERS]

    # Summary rows 1-3 (placeholders — will be calculated by _refresh_summary_sync)
    ws.update(values=[
        [f"{month_name} {year}"],
        ["Checked-in", "", "No-show: 0", "Vacant: 0", "Occ: 0%", "Cash", "0", "UPI", "0", "Total", "0"],
        ["THOR:", "HULK:", "New: 0", "Exit: 0", "", "PAID:0", "PARTIAL:0", "UNPAID:0"],
    ], range_name="A1")

    # Headers at row 4
    ws.update(values=[MONTHLY_HEADERS], range_name="A4")
    ws.format(f"A4:{chr(64 + len(MONTHLY_HEADERS))}4", {
        "textFormat": {"bold": True},
        "backgroundColor": {"red": 0.84, "green": 0.92, "blue": 0.98}
    })

    # Data rows starting at row 5
    if rows:
        data_rows = []
        for r in rows:
            row = []
            for h in headers_lower:
                row.append(r.get(h, ""))
            data_rows.append(row)

        ws.update(values=data_rows, range_name=f"A5:{chr(64 + len(MONTHLY_HEADERS))}{4 + len(rows)}",
                  value_input_option="USER_ENTERED")

    ws.freeze(rows=4)

    # Number format for financial columns
    rent_col = headers_lower.index("rent due")
    bal_col = headers_lower.index("balance")
    col_range = f"{chr(65 + rent_col)}5:{chr(65 + bal_col)}{4 + len(rows)}"
    ws.format(col_range, {"numberFormat": {"type": "NUMBER", "pattern": "#,##0"}})

    try:
        ws.set_basic_filter(f"A4:{chr(64 + len(MONTHLY_HEADERS))}{4 + len(rows)}")
    except:
        pass

    # Refresh summary stats
    try:
        from src.integrations.gsheets import _refresh_summary_sync
        _refresh_summary_sync(tab)
        print("Summary stats refreshed.")
    except Exception as e:
        print(f"Summary refresh failed (non-fatal): {e}")

    print(f"Done! {len(rows)} tenants.")
    prev_count = sum(1 for r in rows if r["prev due"] > 0)
    first_month_count = sum(1 for r in rows if r["event"] in ("CHECKIN", "NO SHOW"))
    print(f"  {prev_count} with carry-forward dues from {prev_tab_name}")
    print(f"  {first_month_count} first-month check-ins (rent + deposit)")


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        m, y = sys.argv[1].upper(), int(sys.argv[2])
    else:
        today = date.today()
        m = MONTHS[today.month % 12]
        y = today.year + (1 if today.month == 12 else 0)

    create_month(m, y)
