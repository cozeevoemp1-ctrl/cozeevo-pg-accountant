"""
Transform original History sheet into clean new sheet format (v2).
Properly filters tenants per month based on check-in/checkout dates.

Reads from: Copy of Cozeevo Monthly stay (History tab)
Writes to: Cozeevo Operations v2 (new sheet)
"""
import calendar
import gspread
import re
import time
from datetime import date, datetime
from google.oauth2.service_account import Credentials

OLD_SHEET = "1T4YE7RK2eIZRg330kaOaNb5-8o8kJbxpDzK_7MfoyiA"
NEW_SHEET = "1Hp5dTM7TcDEq75jgHEjvwtBjOolruGfQ7CVMzVqjdGw"
CREDS = "credentials/gsheets_service_account.json"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
TOTAL_BEDS = 291


# ── Helpers ──────────────────────────────────────────────────────────────────

def to_num(val):
    if not val:
        return 0.0
    s = str(val).strip().replace(",", "")
    m = re.search(r"[\d.]+", s)
    return float(m.group()) if m else 0.0


def parse_date(val):
    """Parse date from various formats: DD-MM-YYYY, DD-MM-YY, YYYY-MM-DD."""
    if not val or not val.strip():
        return None
    s = val.strip()
    for fmt in ("%d-%m-%Y", "%d-%m-%y", "%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def clean_status(val):
    s = str(val).strip().upper()
    if s in ("CHECKIN", "CHECK IN", ""):
        return "Active"
    if "EXIT" in s:
        return "Exited"
    if "NO SHOW" in s or "NOSHOW" in s:
        return "No-show"
    if "CANCEL" in s:
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


def was_active_in_month(tenant, month_start, month_end, cash_key=None, upi_key=None):
    """
    Should this tenant appear in this month's sheet?

    YES if:
    - They were physically present (checked in before month_end, not exited before month_start)
    - OR they have any payment for this month (booking advance, deposit, etc.)
    - OR they have a non-empty rent status for this month
    """
    # If they have any payment for this month, always include (booking advances)
    if cash_key and tenant.get(cash_key, 0) > 0:
        return True
    if upi_key and tenant.get(upi_key, 0) > 0:
        return True

    checkin = tenant["checkin_date"]
    if not checkin:
        return False

    # Must have checked in by end of month
    if checkin > month_end:
        return False

    status = tenant["status"]

    # No-show: they booked but never came. Show only if checkin was in this month.
    if status == "No-show":
        return checkin >= month_start and checkin <= month_end

    # Active: still here
    if status == "Active":
        return True

    # Exited: show if they left during or after this month
    if status == "Exited":
        checkout = tenant.get("checkout_date")
        if checkout:
            return checkout >= month_start
        # No checkout date recorded but status is exited -- assume they were there
        return True

    return False


def calc_prorated_rent(rent, checkin, month_start, month_end):
    """
    If tenant checked in mid-month, prorate.
    If checked in before month, full rent.
    """
    if not checkin or not rent:
        return rent
    if checkin <= month_start:
        return rent  # full month
    if checkin > month_end:
        return 0  # not yet checked in

    # Mid-month check-in: prorate
    days_in_month = (month_end - month_start).days + 1
    days_stayed = (month_end - checkin).days + 1
    return round(rent * days_stayed / days_in_month)


def get_ws(sp, name, rows=300, cols=20):
    try:
        ws = sp.worksheet(name)
        ws.clear()
    except gspread.WorksheetNotFound:
        ws = sp.add_worksheet(name, rows=rows, cols=cols)
    return ws


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    creds = Credentials.from_service_account_file(CREDS, scopes=SCOPES)
    gc = gspread.authorize(creds)

    # ── Read original ────────────────────────────────────────────────────
    print("Reading original sheet...")
    old_ws = gc.open_by_key(OLD_SHEET).worksheet("History")
    rows = old_ws.get_all_values()
    data = rows[1:]
    print(f"  {len(data)} rows")

    # ── Parse ────────────────────────────────────────────────────────────
    tenants = []
    for row in data:
        if not row[1].strip():
            continue
        while len(row) < 42:
            row.append("")

        checkin_date = parse_date(row[4])
        monthly_rent = to_num(row[9])
        rent_feb = to_num(row[10])
        rent_may = to_num(row[11])

        current_rent = monthly_rent
        if rent_may > 0:
            current_rent = rent_may
        elif rent_feb > 0:
            current_rent = rent_feb

        status = clean_status(row[16])

        # Try to infer checkout date from status + comments
        checkout_date = None
        if status == "Exited":
            # Check if there's a date in comments or we can infer from rent status
            # For now, use the last month they had a non-EXIT rent status
            if clean_rent_status(row[26]) == "EXIT":  # March = EXIT
                if clean_rent_status(row[25]) != "EXIT":  # Feb != EXIT
                    checkout_date = date(2026, 3, 1)  # left around March start
                elif clean_rent_status(row[21]) != "EXIT":  # Jan != EXIT
                    checkout_date = date(2026, 2, 1)
                elif clean_rent_status(row[20]) != "EXIT":  # Dec != EXIT
                    checkout_date = date(2026, 1, 1)
                else:
                    checkout_date = date(2025, 12, 1)

        tenants.append({
            "room": row[0].strip(),
            "name": row[1].strip(),
            "phone": row[3].strip(),
            "gender": row[2].strip(),
            "block": row[17].strip(),
            "floor": row[18].strip(),
            "sharing": row[12].strip(),
            "checkin": row[4].strip(),
            "checkin_date": checkin_date,
            "checkout_date": checkout_date,
            "status": status,
            "monthly_rent": monthly_rent,
            "current_rent": current_rent,
            "rent_feb": rent_feb,
            "rent_may": rent_may,
            "deposit": to_num(row[6]),
            "booking": to_num(row[5]),
            "maintenance": to_num(row[7]),
            "staff": row[15].strip(),
            "comments": row[14].strip(),
            "paid_date": row[13].strip(),
            "refund_status": row[38].strip() if len(row) > 38 else "",
            "refund_amount": to_num(row[39]) if len(row) > 39 else 0,
            # Monthly payment data (raw from sheet)
            "dec_status": clean_rent_status(row[20]),
            "jan_status": clean_rent_status(row[21]),
            "jan_cash": to_num(row[23]), "jan_upi": to_num(row[24]), "jan_balance": to_num(row[22]),
            "feb_status": clean_rent_status(row[25]),
            "feb_cash": to_num(row[28]), "feb_upi": to_num(row[29]), "feb_balance": to_num(row[27]),
            "mar_status": clean_rent_status(row[26]),
            "mar_cash": to_num(row[31]), "mar_upi": to_num(row[32]), "mar_balance": to_num(row[30]),
        })

    print(f"  Parsed {len(tenants)} tenants")
    print(f"  Active: {sum(1 for t in tenants if t['status'] == 'Active')}")
    print(f"  Exited: {sum(1 for t in tenants if t['status'] == 'Exited')}")
    print(f"  No-show: {sum(1 for t in tenants if t['status'] == 'No-show')}")

    # ── Write to new sheet ───────────────────────────────────────────────
    print("\nWriting to new sheet...")
    new_sp = gc.open_by_key(NEW_SHEET)

    # ── TENANTS ──────────────────────────────────────────────────────────
    ws = get_ws(new_sp, "TENANTS", rows=300, cols=18)
    t_headers = [
        "Room", "Name", "Phone", "Gender", "Building", "Floor",
        "Sharing", "Check-in", "Status", "Monthly Rent", "Current Rent",
        "Deposit", "Booking", "Maintenance", "Staff", "Comments",
        "Refund Status", "Refund Amount",
    ]
    t_rows = [[
        t["room"], t["name"], t["phone"], t["gender"], t["block"], t["floor"],
        t["sharing"], t["checkin"], t["status"], t["monthly_rent"], t["current_rent"],
        t["deposit"], t["booking"], t["maintenance"], t["staff"], t["comments"],
        t["refund_status"], t["refund_amount"],
    ] for t in tenants]

    ws.update(values=[t_headers] + t_rows, range_name="A1", value_input_option="USER_ENTERED")
    ws.format("A1:R1", {"textFormat": {"bold": True},
                         "backgroundColor": {"red": 0.85, "green": 0.95, "blue": 0.85}})
    ws.freeze(rows=1)
    try:
        ws.set_basic_filter(f"A1:R{1 + len(t_rows)}")
    except Exception:
        pass
    print(f"  TENANTS: {len(t_rows)} rows")
    time.sleep(8)

    # ── Monthly sheets ───────────────────────────────────────────────────
    months_config = [
        ("DECEMBER 2025", date(2025, 12, 1), date(2025, 12, 31),
         "dec_status", None, None, None, None),
        ("JANUARY 2026", date(2026, 1, 1), date(2026, 1, 31),
         "jan_status", "jan_cash", "jan_upi", "jan_balance", None),
        ("FEBRUARY 2026", date(2026, 2, 1), date(2026, 2, 28),
         "feb_status", "feb_cash", "feb_upi", "feb_balance", "rent_feb"),
        ("MARCH 2026", date(2026, 3, 1), date(2026, 3, 31),
         "mar_status", "mar_cash", "mar_upi", "mar_balance", None),
    ]

    for label, m_start, m_end, st_key, cash_key, upi_key, bal_key, rent_rev_key in months_config:
        ws = get_ws(new_sp, label, rows=300, cols=14)

        m_headers = [
            "Room", "Name", "Building", "Sharing", "Rent Due",
            "Cash Paid", "UPI Paid", "Total Paid", "Balance",
            "Status", "Check-in", "Event",
        ]
        m_rows = []
        total_rent = 0
        total_cash = 0
        total_upi = 0
        active_count = 0
        noshow_count = 0
        new_checkins = 0
        exits = 0
        premium_count = 0

        for t in tenants:
            if not was_active_in_month(t, m_start, m_end, cash_key, upi_key):
                continue

            # Determine rent for this month (use revision if applicable)
            if rent_rev_key and t.get(rent_rev_key, 0) > 0:
                rent = t[rent_rev_key]
            else:
                rent = t["current_rent"]

            # Prorate if mid-month check-in
            rent = calc_prorated_rent(rent, t["checkin_date"], m_start, m_end)

            cash = t.get(cash_key, 0) if cash_key else 0
            upi = t.get(upi_key, 0) if upi_key else 0
            total_paid = cash + upi
            balance = rent - total_paid if rent > 0 else 0

            # Determine display status
            raw_st = t.get(st_key, "")
            if raw_st == "PAID" or (total_paid >= rent and rent > 0):
                pay_status = "PAID"
            elif raw_st == "PARTIAL" or (total_paid > 0 and balance > 0):
                pay_status = "PARTIAL"
            elif raw_st in ("EXIT",):
                pay_status = "EXIT"
            elif raw_st == "ADVANCE":
                pay_status = "ADVANCE"
            elif total_paid == 0 and rent > 0:
                pay_status = "UNPAID"
            else:
                pay_status = raw_st or ""

            # Event: new check-in, exit, or ongoing
            event = ""
            if t["checkin_date"] and t["checkin_date"] >= m_start and t["checkin_date"] <= m_end:
                if t["status"] == "No-show":
                    event = "NO-SHOW"
                    noshow_count += 1
                else:
                    event = "NEW CHECK-IN"
                    new_checkins += 1
            if t["status"] == "Exited" and t["checkout_date"] and \
               t["checkout_date"] >= m_start and t["checkout_date"] <= m_end:
                event = "EXITED" if not event else event + " + EXITED"
                exits += 1

            if t["status"] == "Active":
                active_count += 1
                if t["sharing"].lower() == "premium":
                    premium_count += 1
            elif t["status"] == "No-show":
                noshow_count += 1

            total_rent += rent
            total_cash += cash
            total_upi += upi

            m_rows.append([
                t["room"], t["name"], t["block"], t["sharing"],
                rent, cash, upi, total_paid, balance,
                pay_status, t["checkin"], event,
            ])

        total_collected = total_cash + total_upi
        outstanding = total_rent - total_collected
        regular = active_count - premium_count
        beds = regular + premium_count * 2
        vacant = TOTAL_BEDS - beds - noshow_count
        occ_pct = round(beds / TOTAL_BEDS * 100, 1) if TOTAL_BEDS else 0
        coll_pct = round(total_collected / total_rent * 100, 1) if total_rent else 0

        summary = [
            [f"{label}", "", "", "", "", "", "", "", "", "", "", ""],
            ["Occupancy", f"{beds} beds ({regular}+{premium_count}P)",
             f"No-show: {noshow_count}", f"Vacant: {vacant}", f"Occ: {occ_pct}%",
             "", "", "", "", "", "", ""],
            ["New check-ins", new_checkins, "Exits", exits, "",
             "Rent Expected", total_rent, "Collected", total_collected,
             "Outstanding", outstanding, f"Coll: {coll_pct}%"],
            m_headers,
        ]

        ws.update(values=summary + m_rows, range_name="A1", value_input_option="USER_ENTERED")
        ws.format("A1:L1", {"textFormat": {"bold": True, "fontSize": 13}})
        ws.format("A2:L3", {"textFormat": {"bold": True, "fontSize": 10},
                             "numberFormat": {"type": "NUMBER", "pattern": "#,##0"}})
        ws.format("A4:L4", {"textFormat": {"bold": True},
                             "backgroundColor": {"red": 0.85, "green": 0.9, "blue": 1.0}})
        ws.freeze(rows=4)
        try:
            ws.set_basic_filter(f"A4:L{4 + len(m_rows)}")
        except Exception:
            pass

        print(f"  {label}: {len(m_rows)} tenants | "
              f"Beds:{beds} Vacant:{vacant} | "
              f"Cash:{total_cash:,.0f} UPI:{total_upi:,.0f} | "
              f"New:{new_checkins} Exit:{exits}")
        time.sleep(8)

    # ── DASHBOARD ────────────────────────────────────────────────────────
    # March numbers for dashboard
    mar = [t for t in tenants if was_active_in_month(t, date(2026, 3, 1), date(2026, 3, 31), "mar_cash", "mar_upi")]
    mar_active = [t for t in mar if t["status"] == "Active"]
    mar_premium = [t for t in mar_active if t["sharing"].lower() == "premium"]
    mar_noshow = [t for t in mar if t["status"] == "No-show"]
    mar_regular = len(mar_active) - len(mar_premium)
    mar_beds = mar_regular + len(mar_premium) * 2
    mar_vacant = TOTAL_BEDS - mar_beds - len(mar_noshow)
    mar_rent = sum(calc_prorated_rent(t["current_rent"], t["checkin_date"],
                                       date(2026, 3, 1), date(2026, 3, 31)) for t in mar)
    mar_cash = sum(t["mar_cash"] for t in tenants)
    mar_upi = sum(t["mar_upi"] for t in tenants)
    mar_collected = mar_cash + mar_upi
    mar_out = mar_rent - mar_collected
    mar_occ = round(mar_beds / TOTAL_BEDS * 100, 1)
    mar_coll = round(mar_collected / mar_rent * 100, 1) if mar_rent else 0

    mar_paid = sum(1 for t in mar if t["mar_status"] == "PAID")
    mar_partial = sum(1 for t in mar if t["mar_status"] == "PARTIAL")
    mar_unpaid = sum(1 for t in mar if t["mar_status"] in ("UNPAID", "") and t["status"] == "Active")

    # Also calc Jan and Feb summaries for dashboard
    def month_summary(tenants_list, m_start, m_end, cash_key, upi_key):
        active_m = [t for t in tenants_list if was_active_in_month(t, m_start, m_end)]
        c = sum(t.get(cash_key, 0) for t in tenants_list)
        u = sum(t.get(upi_key, 0) for t in tenants_list)
        return len(active_m), c, u, c + u

    jan_t, jan_c, jan_u, jan_tot = month_summary(tenants, date(2026,1,1), date(2026,1,31), "jan_cash", "jan_upi")
    feb_t, feb_c, feb_u, feb_tot = month_summary(tenants, date(2026,2,1), date(2026,2,28), "feb_cash", "feb_upi")

    ws = get_ws(new_sp, "DASHBOARD", rows=40, cols=6)
    dash = [
        ["COZEEVO DASHBOARD", "", "", "", "", ""],
        ["", "", "", "", "", ""],
        ["MARCH 2026 SNAPSHOT", "", "", "", "", ""],
        ["", "", "", "", "", ""],
        ["OCCUPANCY", "", "", "COLLECTIONS", "", ""],
        ["Revenue Beds", TOTAL_BEDS, "", "Rent Expected", mar_rent, ""],
        ["Checked-in", mar_beds, f"{mar_regular} regular + {len(mar_premium)} premium",
         "Collected", mar_collected, f"{mar_coll}%"],
        ["No-show", len(mar_noshow), "", "  Cash", mar_cash, ""],
        ["Vacant", mar_vacant, "", "  UPI", mar_upi, ""],
        ["Occupancy", f"{mar_occ}%", "", "Outstanding", mar_out, ""],
        ["", "", "", "", "", ""],
        ["PAYMENT STATUS", "", "", "MOVEMENT", "", ""],
        ["Paid", mar_paid, "", "New check-ins", sum(1 for t in mar if t["checkin_date"] and t["checkin_date"] >= date(2026,3,1) and t["checkin_date"] <= date(2026,3,31) and t["status"] != "No-show"), ""],
        ["Partial", mar_partial, "", "Exits", sum(1 for t in mar if t["status"] == "Exited" and t.get("checkout_date") and t["checkout_date"] >= date(2026,3,1)), ""],
        ["Unpaid", mar_unpaid, "", "No-show", len(mar_noshow), ""],
        ["", "", "", "", "", ""],
        ["MONTH-ON-MONTH", "Tenants", "Cash", "UPI", "Total", ""],
        ["January 2026", jan_t, jan_c, jan_u, jan_tot, ""],
        ["February 2026", feb_t, feb_c, feb_u, feb_tot, ""],
        ["March 2026", len(mar), mar_cash, mar_upi, mar_collected, ""],
        ["", "", "", "", "", ""],
        ["HOW IT WORKS", "", "", "", "", ""],
        ["1. Rent collected via WhatsApp bot", "", "", "", "", ""],
        ["2. Bot writes to DB + updates this sheet", "", "", "", "", ""],
        ["3. Monthly tabs show per-tenant breakdown", "", "", "", "", ""],
        ["4. Filter by Status or Event column", "", "", "", "", ""],
        ["5. New month tab auto-created on 1st", "", "", "", "", ""],
    ]

    ws.update(values=dash, range_name="A1", value_input_option="USER_ENTERED")
    ws.format("A1:F1", {"textFormat": {"bold": True, "fontSize": 14}})
    ws.format("A3:F3", {"textFormat": {"bold": True, "fontSize": 12},
                         "backgroundColor": {"red": 1.0, "green": 0.98, "blue": 0.8}})
    ws.format("A5:F5", {"textFormat": {"bold": True},
                         "backgroundColor": {"red": 0.85, "green": 0.92, "blue": 1.0}})
    ws.format("A12:F12", {"textFormat": {"bold": True},
                           "backgroundColor": {"red": 1.0, "green": 0.95, "blue": 0.85}})
    ws.format("A17:F17", {"textFormat": {"bold": True},
                           "backgroundColor": {"red": 0.9, "green": 0.9, "blue": 1.0}})
    ws.format("B6:B10", {"numberFormat": {"type": "NUMBER", "pattern": "#,##0"}})
    ws.format("E6:E10", {"numberFormat": {"type": "NUMBER", "pattern": "#,##0"}})
    ws.format("B18:E20", {"numberFormat": {"type": "NUMBER", "pattern": "#,##0"}})
    print(f"  DASHBOARD: done")
    time.sleep(5)

    # ── Clean up old tabs ────────────────────────────────────────────────
    for name in ["Sheet1", "ROOMS", "PAYMENTS", "CHANGES LOG", "MONTHLY VIEW",
                 "MONTHLY JAN 2026", "MONTHLY FEB 2026", "_LOOKUP", "COLLECT RENT"]:
        try:
            new_sp.del_worksheet(new_sp.worksheet(name))
        except Exception:
            pass

    print(f"\n{'='*60}")
    print(f"DONE! New sheet tabs:")
    print(f"  DASHBOARD — March snapshot + month-on-month")
    print(f"  TENANTS — {len(t_rows)} tenants (master list)")
    print(f"  DECEMBER 2025 — only tenants active in Dec")
    print(f"  JANUARY 2026 — only tenants active in Jan")
    print(f"  FEBRUARY 2026 — only tenants active in Feb")
    print(f"  MARCH 2026 — only tenants active in Mar")
    print(f"\nEvery month shows: occupancy + collections + per-tenant breakdown")
    print(f"Event column shows: NEW CHECK-IN / EXITED / NO-SHOW")


if __name__ == "__main__":
    main()
