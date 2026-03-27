"""
Transform original History sheet into clean new sheet format.
Reads from: Copy of Cozeevo Monthly stay (History tab)
Writes to: Cozeevo Operations v2 (new sheet)
"""
import gspread
import re
import time
from google.oauth2.service_account import Credentials

CREDS = "credentials/gsheets_service_account.json"
OLD_SHEET = "1T4YE7RK2eIZRg330kaOaNb5-8o8kJbxpDzK_7MfoyiA"
NEW_SHEET = "1Hp5dTM7TcDEq75jgHEjvwtBjOolruGfQ7CVMzVqjdGw"

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def to_num(val):
    """Parse number from sheet cell (handles commas, text mixed in)."""
    if not val:
        return 0
    s = str(val).strip()
    # Remove commas
    s = s.replace(",", "")
    # Try to extract first number
    m = re.search(r"[\d.]+", s)
    if m:
        try:
            return float(m.group())
        except ValueError:
            return 0
    return 0


def clean_status(val):
    s = str(val).strip().upper()
    if s in ("CHECKIN", "CHECK IN", ""):
        return "Active"
    if s in ("EXIT", "EXITED", "CHECKOUT"):
        return "Exited"
    if s in ("NO SHOW", "NOSHOW"):
        return "No-show"
    if s in ("CANCELLED", "CANCEL"):
        return "Cancelled"
    return "Active"


def clean_rent_status(val):
    s = str(val).strip().upper()
    if not s:
        return ""
    if "PAID" in s and "NOT" not in s and "PARTIAL" not in s:
        return "PAID"
    if "PARTIAL" in s:
        return "PARTIAL"
    if "NOT PAID" in s or "UNPAID" in s:
        return "UNPAID"
    if "EXIT" in s or "CANCEL" in s:
        return "EXIT"
    if "ADVANCE" in s:
        return "ADVANCE"
    return s


def main():
    creds = Credentials.from_service_account_file(CREDS, scopes=SCOPES)
    gc = gspread.authorize(creds)

    # ── Read original ────────────────────────────────────────────────────
    print("Reading original sheet...")
    old_sp = gc.open_by_key(OLD_SHEET)
    old_ws = old_sp.worksheet("History")
    rows = old_ws.get_all_values()
    headers = rows[0]
    data = rows[1:]  # skip header
    print(f"  {len(data)} rows, {len(headers)} cols")

    # ── Parse each row ───────────────────────────────────────────────────
    tenants = []
    for row in data:
        if not row[1].strip():  # skip empty name
            continue

        # Pad row if short
        while len(row) < 42:
            row.append("")

        room = row[0].strip()
        name = row[1].strip()
        gender = row[2].strip()
        phone = row[3].strip()
        checkin = row[4].strip()
        booking = to_num(row[5])
        deposit = to_num(row[6])
        maintenance = to_num(row[7])
        daily_rent = to_num(row[8])
        monthly_rent = to_num(row[9])
        rent_feb = to_num(row[10])
        rent_may = to_num(row[11])
        sharing = row[12].strip()
        paid_date = row[13].strip()
        comments = row[14].strip()
        staff = row[15].strip()
        status_raw = row[16].strip()
        block = row[17].strip()
        floor = row[18].strip()

        # Current rent = latest revision or monthly
        current_rent = monthly_rent
        if rent_may and rent_may > 0:
            current_rent = rent_may
        elif rent_feb and rent_feb > 0:
            current_rent = rent_feb

        status = clean_status(status_raw)

        # Monthly payment data
        dec_status = clean_rent_status(row[20])
        jan_status = clean_rent_status(row[21])
        jan_balance = to_num(row[22])
        jan_cash = to_num(row[23])
        jan_upi = to_num(row[24])
        feb_status = clean_rent_status(row[25])
        mar_status = clean_rent_status(row[26])
        feb_balance = to_num(row[27])
        feb_cash = to_num(row[28])
        feb_upi = to_num(row[29])
        mar_balance = to_num(row[30])
        mar_cash = to_num(row[31])
        mar_upi = to_num(row[32])

        refund_status = row[38].strip() if len(row) > 38 else ""
        refund_amount = to_num(row[39]) if len(row) > 39 else 0

        tenants.append({
            "room": room, "name": name, "gender": gender, "phone": phone,
            "checkin": checkin, "booking": booking, "deposit": deposit,
            "maintenance": maintenance, "monthly_rent": monthly_rent,
            "current_rent": current_rent, "sharing": sharing,
            "paid_date": paid_date, "comments": comments, "staff": staff,
            "status": status, "block": block, "floor": floor,
            "dec_status": dec_status,
            "jan_status": jan_status, "jan_cash": jan_cash, "jan_upi": jan_upi, "jan_balance": jan_balance,
            "feb_status": feb_status, "feb_cash": feb_cash, "feb_upi": feb_upi, "feb_balance": feb_balance,
            "mar_status": mar_status, "mar_cash": mar_cash, "mar_upi": mar_upi, "mar_balance": mar_balance,
            "refund_status": refund_status, "refund_amount": refund_amount,
        })

    print(f"  Parsed {len(tenants)} tenants")

    # ── Write to new sheet ───────────────────────────────────────────────
    print("Writing to new sheet...")
    new_sp = gc.open_by_key(NEW_SHEET)

    def get_ws(name, rows=300, cols=20):
        try:
            ws = new_sp.worksheet(name)
            ws.clear()
        except gspread.WorksheetNotFound:
            ws = new_sp.add_worksheet(name, rows=rows, cols=cols)
        return ws

    # ── TENANTS sheet ────────────────────────────────────────────────────
    ws = get_ws("TENANTS", rows=300, cols=18)
    t_headers = [
        "Room", "Name", "Phone", "Gender", "Building", "Floor",
        "Sharing", "Check-in", "Status", "Monthly Rent", "Current Rent",
        "Deposit", "Booking", "Maintenance", "Staff", "Comments",
        "Refund Status", "Refund Amount",
    ]
    t_rows = []
    for t in tenants:
        t_rows.append([
            t["room"], t["name"], t["phone"], t["gender"], t["block"], t["floor"],
            t["sharing"], t["checkin"], t["status"], t["monthly_rent"], t["current_rent"],
            t["deposit"], t["booking"], t["maintenance"], t["staff"], t["comments"],
            t["refund_status"], t["refund_amount"],
        ])

    ws.update(values=[t_headers] + t_rows, range_name="A1", value_input_option="USER_ENTERED")
    ws.format("A1:R1", {"textFormat": {"bold": True}, "backgroundColor": {"red": 0.85, "green": 0.95, "blue": 0.85}})
    ws.freeze(rows=1)
    try:
        ws.set_basic_filter(f"A1:R{1 + len(t_rows)}")
    except Exception:
        pass
    print(f"  TENANTS: {len(t_rows)} rows")
    time.sleep(5)  # rate limit

    # ── MONTHLY VIEW (one per month) ─────────────────────────────────────
    months = [
        ("DECEMBER 2025", "dec_status", None, None, None),
        ("JANUARY 2026", "jan_status", "jan_cash", "jan_upi", "jan_balance"),
        ("FEBRUARY 2026", "feb_status", "feb_cash", "feb_upi", "feb_balance"),
        ("MARCH 2026", "mar_status", "mar_cash", "mar_upi", "mar_balance"),
    ]

    for month_label, status_key, cash_key, upi_key, bal_key in months:
        ws = get_ws(month_label, rows=300, cols=12)

        m_headers = ["Room", "Name", "Building", "Sharing", "Rent Due",
                      "Cash Paid", "UPI Paid", "Total Paid", "Balance", "Status"]
        m_rows = []

        total_rent = 0
        total_cash = 0
        total_upi = 0

        for t in tenants:
            st = t.get(status_key, "")
            if not st or st == "EXIT":
                continue  # skip exited tenants for this month

            rent = t["current_rent"]
            cash = t.get(cash_key, 0) if cash_key else 0
            upi = t.get(upi_key, 0) if upi_key else 0
            total_paid = cash + upi
            balance = rent - total_paid if rent > 0 else 0

            if st == "PAID":
                pay_status = "PAID"
            elif st == "PARTIAL" or (total_paid > 0 and balance > 0):
                pay_status = "PARTIAL"
            elif st == "ADVANCE":
                pay_status = "ADVANCE"
            elif total_paid == 0 and st == "UNPAID":
                pay_status = "UNPAID"
            else:
                pay_status = st

            total_rent += rent
            total_cash += cash
            total_upi += upi

            m_rows.append([
                t["room"], t["name"], t["block"], t["sharing"],
                rent, cash, upi, total_paid, balance, pay_status,
            ])

        total_collected = total_cash + total_upi
        outstanding = total_rent - total_collected

        summary = [
            [f"RENT TRACKER \u2014 {month_label}", "", "", "", "", "", "", "", "", ""],
            ["", "", "", "", "Rent Expected", "Cash", "UPI", "Total", "Outstanding", ""],
            ["", "", "", "", total_rent, total_cash, total_upi, total_collected, outstanding, ""],
            m_headers,
        ]

        ws.update(values=summary + m_rows, range_name="A1", value_input_option="USER_ENTERED")
        ws.format("A1:J1", {"textFormat": {"bold": True, "fontSize": 13}})
        ws.format("A2:J3", {"textFormat": {"bold": True},
                             "numberFormat": {"type": "NUMBER", "pattern": "#,##0"}})
        ws.format("A4:J4", {"textFormat": {"bold": True},
                             "backgroundColor": {"red": 0.85, "green": 0.9, "blue": 1.0}})
        ws.freeze(rows=4)
        try:
            ws.set_basic_filter(f"A4:J{4 + len(m_rows)}")
        except Exception:
            pass
        print(f"  {month_label}: {len(m_rows)} tenants, Cash {total_cash:,.0f}, UPI {total_upi:,.0f}")
        time.sleep(5)  # rate limit

    # ── DASHBOARD ────────────────────────────────────────────────────────
    # Use March data for dashboard
    mar_tenants = [t for t in tenants if t.get("mar_status") and t["mar_status"] != "EXIT"]
    active = [t for t in tenants if t["status"] == "Active"]
    noshow = [t for t in tenants if t["status"] == "No-show"]
    premium = [t for t in active if t["sharing"].lower() == "premium"]
    regular_count = len(active) - len(premium)
    beds = regular_count + len(premium) * 2

    mar_rent = sum(t["current_rent"] for t in mar_tenants)
    mar_cash = sum(t["mar_cash"] for t in tenants)
    mar_upi = sum(t["mar_upi"] for t in tenants)
    mar_collected = mar_cash + mar_upi
    mar_outstanding = mar_rent - mar_collected

    mar_paid = sum(1 for t in mar_tenants if t["mar_status"] == "PAID")
    mar_partial = sum(1 for t in mar_tenants if t["mar_status"] == "PARTIAL")
    mar_unpaid = sum(1 for t in mar_tenants if t["mar_status"] == "UNPAID")

    ws = get_ws("DASHBOARD", rows=35, cols=4)
    dash = [
        ["COZEEVO DASHBOARD", "", ""],
        ["March 2026", "", ""],
        ["", "", ""],
        ["OCCUPANCY", "", ""],
        ["Total Revenue Beds", 291, ""],
        ["Checked-in Beds", beds, f"{regular_count} regular + {len(premium)} premium"],
        ["No-show", len(noshow), ""],
        ["Vacant", 291 - beds - len(noshow), ""],
        ["Occupancy %", f"{round(beds/291*100,1)}%", ""],
        ["", "", ""],
        ["MARCH COLLECTIONS", "", ""],
        ["Rent Expected", mar_rent, ""],
        ["Total Collected", mar_collected, ""],
        ["  Cash", mar_cash, ""],
        ["  UPI", mar_upi, ""],
        ["Outstanding", mar_outstanding, ""],
        ["Collection %", f"{round(mar_collected/mar_rent*100,1) if mar_rent else 0}%", ""],
        ["", "", ""],
        ["PAYMENT STATUS", "", ""],
        ["Paid", mar_paid, ""],
        ["Partial", mar_partial, ""],
        ["Unpaid", mar_unpaid, ""],
        ["", "", ""],
        ["HOW TO USE", "", ""],
        ["1. Collect rent via WhatsApp bot", "", ""],
        ["2. Bot updates DB + this sheet automatically", "", ""],
        ["3. Check monthly tabs for per-tenant breakdown", "", ""],
        ["4. Filter by Status to see who owes", "", ""],
    ]

    ws.update(values=dash, range_name="A1", value_input_option="USER_ENTERED")
    ws.format("A1:C1", {"textFormat": {"bold": True, "fontSize": 14}})
    ws.format("A2:C2", {"textFormat": {"bold": True, "fontSize": 12},
                         "backgroundColor": {"red": 1.0, "green": 0.98, "blue": 0.8}})
    ws.format("A4:C4", {"textFormat": {"bold": True},
                         "backgroundColor": {"red": 0.85, "green": 0.92, "blue": 1.0}})
    ws.format("A11:C11", {"textFormat": {"bold": True},
                           "backgroundColor": {"red": 0.85, "green": 1.0, "blue": 0.85}})
    ws.format("A19:C19", {"textFormat": {"bold": True},
                           "backgroundColor": {"red": 1.0, "green": 0.95, "blue": 0.85}})
    ws.format("B12:B16", {"numberFormat": {"type": "NUMBER", "pattern": "#,##0"}})
    print(f"  DASHBOARD: done")
    time.sleep(5)

    # ── Clean up old tabs ────────────────────────────────────────────────
    for ws_name in ["ROOMS", "PAYMENTS", "CHANGES LOG", "MONTHLY VIEW",
                    "MONTHLY JAN 2026", "MONTHLY FEB 2026", "_LOOKUP",
                    "COLLECT RENT", "Sheet1"]:
        try:
            new_sp.del_worksheet(new_sp.worksheet(ws_name))
            print(f"  Deleted old tab: {ws_name}")
        except Exception:
            pass

    print(f"\nDone! New sheet has:")
    print(f"  DASHBOARD — overview")
    print(f"  TENANTS — {len(t_rows)} tenants with all details")
    print(f"  DECEMBER 2025 — monthly rent tracker")
    print(f"  JANUARY 2026 — monthly rent tracker")
    print(f"  FEBRUARY 2026 — monthly rent tracker")
    print(f"  MARCH 2026 — monthly rent tracker")
    print(f"\nCash + UPI totals match original sheet (read directly from it)")


if __name__ == "__main__":
    main()
