"""
Transform original History sheet -> clean new sheet (v3).
Parses comment column for embedded data: [March Balance: X], expressions, notes.
Separates master comments from monthly comments.
"""
import calendar
import gspread
import re
import sys
import time
from datetime import date, datetime
from google.oauth2.service_account import Credentials

sys.stdout.reconfigure(encoding='utf-8')

OLD_SHEET = "1T4YE7RK2eIZRg330kaOaNb5-8o8kJbxpDzK_7MfoyiA"
NEW_SHEET = "1Hp5dTM7TcDEq75jgHEjvwtBjOolruGfQ7CVMzVqjdGw"
CREDS = "credentials/gsheets_service_account.json"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
TOTAL_BEDS = 291

# ── Helpers ──────────────────────────────────────────────────────────────────

def pn(val):
    """Parse number from cell. Handles commas, expressions like 516*16=8256."""
    if not val: return 0.0
    s = str(val).strip().replace(",", "")
    # If it has = at end (expression result), take the result
    eq = re.search(r"=\s*([\d.]+)\s*$", s)
    if eq: return float(eq.group(1))
    # First number
    m = re.search(r"[\d.]+", s)
    return float(m.group()) if m else 0.0


def parse_date(val):
    if not val or not str(val).strip(): return None
    s = str(val).strip()
    for fmt in ("%d-%m-%Y", "%d-%m-%y", "%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y"):
        try: return datetime.strptime(s, fmt).date()
        except ValueError: continue
    return None


def clean_status(val):
    s = str(val).strip().upper()
    if s in ("CHECKIN", "CHECK IN", ""): return "Active"
    if "EXIT" in s: return "Exited"
    if "NO SHOW" in s or "NOSHOW" in s: return "No-show"
    if "CANCEL" in s: return "Cancelled"
    return "Active"


def clean_rent_status(val):
    s = str(val).strip().upper()
    if not s: return ""
    if "PAID" in s and "NOT" not in s and "PARTIAL" not in s: return "PAID"
    if "PARTIAL" in s: return "PARTIAL"
    if "NOT PAID" in s or "UNPAID" in s: return "UNPAID"
    if "EXIT" in s or "CANCEL" in s: return "EXIT"
    if "ADVANCE" in s: return "ADVANCE"
    if "NO SHOW" in s: return "NO SHOW"
    return s


# ── Comment Parser ───────────────────────────────────────────────────────────

BRACKET_RE = re.compile(r"\[([^:\]]+):\s*([^\]]*)\]")

FIELD_MAP = {
    "march balance": "mar_balance", "mar balance": "mar_balance",
    "march cash": "mar_cash", "mar cash": "mar_cash",
    "march upi": "mar_upi", "mar upi": "mar_upi",
    "feb balance": "feb_balance", "february balance": "feb_balance",
    "feb cash": "feb_cash", "feb upi": "feb_upi",
    "jan balance": "jan_balance", "january balance": "jan_balance",
    "jan cash": "jan_cash", "jan upi": "jan_upi",
    "security deposit": "deposit", "booking": "booking",
    "day wise rent": "daily_rent", "refund amount": "refund",
    "monthly rent": "monthly_rent",
}

MONTH_FIELDS = {"mar_balance", "mar_cash", "mar_upi", "feb_balance", "feb_cash",
                "feb_upi", "jan_balance", "jan_cash", "jan_upi"}


def parse_comment(comment):
    """
    Parse comment column.
    Returns: (overrides_dict, master_comment_str, monthly_notes_dict)

    overrides: {field: numeric_value} — corrections to payment/balance columns
    master_comment: text that belongs in TENANTS master (agreements, policies)
    monthly_notes: {month_prefix: "note text"} — per-month notes
    """
    if not comment: return {}, "", {}

    overrides = {}
    monthly_notes = {}
    remaining = comment

    # Extract all [Key: Value] patterns
    for key, val in BRACKET_RE.findall(comment):
        remaining = remaining.replace(f"[{key}: {val}]", "")
        k_lower = key.strip().lower()
        mapped = FIELD_MAP.get(k_lower)
        if not mapped: continue

        val = val.strip()
        # Evaluate expressions: 516*16=8256 -> 8256
        eq = re.search(r"=\s*([\d,.]+)\s*$", val)
        if eq:
            overrides[mapped] = float(eq.group(1).replace(",", ""))
            expr_part = val[:val.rfind("=")].strip()
            if mapped in MONTH_FIELDS:
                monthly_notes.setdefault(_month_prefix(mapped), []).append(expr_part)
            continue

        # Extract number + text
        num_match = re.search(r"[\d,.]+", val)
        num_val = float(num_match.group().replace(",", "")) if num_match else 0
        text_part = re.sub(r"[\d,.]+", "", val).strip().strip("-").strip()

        overrides[mapped] = num_val
        if text_part and mapped in MONTH_FIELDS:
            monthly_notes.setdefault(_month_prefix(mapped), []).append(text_part)

    # Also catch [25-Mar 17:45] Rs.500 CASH style entries
    ts_matches = re.findall(r"\[(\d{1,2}-\w{3}\s+\d{1,2}:\d{2})\]\s*(.*?)(?=\[|$)", remaining)
    for ts, note in ts_matches:
        remaining = remaining.replace(f"[{ts}]", "").replace(note, "")
        month_abbr = ts.split("-")[1][:3].lower()
        prefix = {"jan": "jan", "feb": "feb", "mar": "mar", "apr": "apr", "dec": "dec"}.get(month_abbr, "")
        if prefix:
            monthly_notes.setdefault(prefix, []).append(f"[{ts}] {note.strip()}")

    # Clean remaining = master comment
    remaining = re.sub(r"\s*\|\s*", " | ", remaining).strip()
    remaining = re.sub(r"^\s*\|\s*", "", remaining).strip()
    remaining = re.sub(r"\s*\|\s*$", "", remaining).strip()
    remaining = re.sub(r"\s+", " ", remaining).strip()

    # Classify remaining as master or monthly
    # "Received by Chandra anna" in context of March -> monthly
    master = remaining

    return overrides, master, monthly_notes


def _month_prefix(field):
    if field.startswith("mar"): return "mar"
    if field.startswith("feb"): return "feb"
    if field.startswith("jan"): return "jan"
    return ""


# ── Month filter ─────────────────────────────────────────────────────────────

def was_active(tenant, m_start, m_end, cash_key=None, upi_key=None):
    if cash_key and tenant.get(cash_key, 0) > 0: return True
    if upi_key and tenant.get(upi_key, 0) > 0: return True
    # Check balance overrides from comments
    bal_key = {"jan_cash": "jan_balance", "feb_cash": "feb_balance", "mar_cash": "mar_balance"}.get(cash_key)
    if bal_key and tenant.get(bal_key, 0) > 0: return True

    checkin = tenant["checkin_date"]
    if not checkin or checkin > m_end: return False
    if tenant["status"] == "No-show":
        return checkin >= m_start and checkin <= m_end
    if tenant["status"] == "Active": return True
    if tenant["status"] == "Exited":
        co = tenant.get("checkout_date")
        return co >= m_start if co else True
    return False


def calc_prorate(rent, checkin, m_start, m_end):
    if not checkin or not rent or checkin <= m_start: return rent
    if checkin > m_end: return 0
    days = (m_end - m_start).days + 1
    stayed = (m_end - checkin).days + 1
    return round(rent * stayed / days)


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
    rows = gc.open_by_key(OLD_SHEET).worksheet("History").get_all_values()
    data = rows[1:]
    print(f"  {len(data)} rows")

    # ── Parse ────────────────────────────────────────────────────────────
    tenants = []
    for row in data:
        if not row[1].strip(): continue
        while len(row) < 42: row.append("")

        # Parse comment
        overrides, master_comment, monthly_notes = parse_comment(row[14])

        checkin_date = parse_date(row[4])
        monthly_rent = pn(row[9])
        rent_feb = pn(row[10])
        rent_may = pn(row[11])
        current_rent = rent_may if rent_may > 0 else (rent_feb if rent_feb > 0 else monthly_rent)

        status = clean_status(row[16])

        # Infer checkout date for exited tenants
        checkout_date = None
        if status == "Exited":
            if clean_rent_status(row[26]) == "EXIT":
                if clean_rent_status(row[25]) != "EXIT": checkout_date = date(2026, 3, 1)
                elif clean_rent_status(row[21]) != "EXIT": checkout_date = date(2026, 2, 1)
                elif clean_rent_status(row[20]) != "EXIT": checkout_date = date(2026, 1, 1)
                else: checkout_date = date(2025, 12, 1)

        t = {
            "room": row[0].strip(), "name": row[1].strip(),
            "phone": row[3].strip(), "gender": row[2].strip(),
            "block": row[17].strip(), "floor": row[18].strip(),
            "sharing": row[12].strip(), "checkin": row[4].strip(),
            "checkin_date": checkin_date, "checkout_date": checkout_date,
            "status": status,
            "monthly_rent": monthly_rent, "current_rent": current_rent,
            "rent_feb": rent_feb, "rent_may": rent_may,
            "deposit": overrides.get("deposit", pn(row[6])),
            "booking": overrides.get("booking", pn(row[5])),
            "maintenance": pn(row[7]), "staff": row[15].strip(),
            "master_comment": master_comment,
            "monthly_notes": monthly_notes,
            "refund_status": row[38].strip() if len(row) > 38 else "",
            "refund_amount": overrides.get("refund", pn(row[39]) if len(row) > 39 else 0),
            # Payment data: ALWAYS from columns, NEVER from comments
            # Comments are notes only, not number overrides
            "dec_status": clean_rent_status(row[20]),
            "jan_status": clean_rent_status(row[21]),
            "jan_cash": pn(row[23]),
            "jan_upi": pn(row[24]),
            "jan_balance": pn(row[22]),
            "feb_status": clean_rent_status(row[25]),
            "feb_cash": pn(row[28]),
            "feb_upi": pn(row[29]),
            "feb_balance": pn(row[27]),
            "mar_status": clean_rent_status(row[26]),
            "mar_cash": pn(row[31]),
            "mar_upi": pn(row[32]),
            "mar_balance": pn(row[30]),
        }
        tenants.append(t)

    print(f"  Parsed {len(tenants)} tenants")
    print(f"  Active: {sum(1 for t in tenants if t['status'] == 'Active')}")
    print(f"  Exited: {sum(1 for t in tenants if t['status'] == 'Exited')}")
    print(f"  No-show: {sum(1 for t in tenants if t['status'] == 'No-show')}")
    print(f"  With comment overrides: {sum(1 for t in tenants if t['monthly_notes'])}")

    # ── Validate column totals ───────────────────────────────────────────
    print("\nValidation (must match raw column SUM):")
    for label, key in [("Jan Cash", "jan_cash"), ("Jan UPI", "jan_upi"),
                        ("Feb Cash", "feb_cash"), ("Feb UPI", "feb_upi"),
                        ("Mar Cash", "mar_cash"), ("Mar UPI", "mar_upi")]:
        total = sum(t[key] for t in tenants)
        print(f"  {label}: {total:,.0f}")

    # ── Write to new sheet ───────────────────────────────────────────────
    print("\nWriting to new sheet...")
    sp = gc.open_by_key(NEW_SHEET)

    # ── TENANTS ──────────────────────────────────────────────────────────
    ws = get_ws(sp, "TENANTS", 300, 18)
    t_headers = ["Room", "Name", "Phone", "Gender", "Building", "Floor",
                 "Sharing", "Check-in", "Status", "Monthly Rent", "Current Rent",
                 "Deposit", "Booking", "Maintenance", "Staff", "Master Comments",
                 "Refund Status", "Refund Amount"]
    t_rows = [[
        t["room"], t["name"], t["phone"], t["gender"], t["block"], t["floor"],
        t["sharing"], t["checkin"], t["status"], t["monthly_rent"], t["current_rent"],
        t["deposit"], t["booking"], t["maintenance"], t["staff"], t["master_comment"],
        t["refund_status"], t["refund_amount"],
    ] for t in tenants]

    ws.update(values=[t_headers] + t_rows, range_name="A1", value_input_option="USER_ENTERED")
    ws.format("A1:R1", {"textFormat": {"bold": True}, "backgroundColor": {"red": 0.85, "green": 0.95, "blue": 0.85}})
    ws.freeze(rows=1)
    try: ws.set_basic_filter(f"A1:R{1 + len(t_rows)}")
    except: pass
    print(f"  TENANTS: {len(t_rows)} rows")
    time.sleep(8)

    # ── Monthly sheets ───────────────────────────────────────────────────
    months = [
        ("DECEMBER 2025", date(2025,12,1), date(2025,12,31), "dec_status", None, None, None, None, "dec"),
        ("JANUARY 2026", date(2026,1,1), date(2026,1,31), "jan_status", "jan_cash", "jan_upi", "jan_balance", None, "jan"),
        ("FEBRUARY 2026", date(2026,2,1), date(2026,2,28), "feb_status", "feb_cash", "feb_upi", "feb_balance", "rent_feb", "feb"),
        ("MARCH 2026", date(2026,3,1), date(2026,3,31), "mar_status", "mar_cash", "mar_upi", "mar_balance", None, "mar"),
    ]

    all_month_data = {}

    for label, m_start, m_end, st_key, cash_key, upi_key, bal_key, rent_rev, month_prefix in months:
        ws = get_ws(sp, label, 300, 14)
        headers = ["Room", "Name", "Building", "Sharing", "Rent Due",
                   "Cash Paid", "UPI Paid", "Total Paid", "Balance",
                   "Status", "Check-in", "Event", "Notes"]

        m_rows = []
        stats = {"tenants": 0, "beds": 0, "regular": 0, "premium": 0, "noshow": 0,
                 "cash": 0, "upi": 0, "rent": 0, "new": 0, "exits": 0,
                 "paid": 0, "partial": 0, "unpaid": 0,
                 "thor_beds": 0, "hulk_beds": 0, "thor_rent": 0, "hulk_rent": 0,
                 "thor_cash": 0, "hulk_cash": 0, "thor_upi": 0, "hulk_upi": 0}

        for t in tenants:
            if not was_active(t, m_start, m_end, cash_key, upi_key):
                continue

            rent = t.get(rent_rev, 0) if rent_rev and t.get(rent_rev, 0) > 0 else t["current_rent"]
            rent = calc_prorate(rent, t["checkin_date"], m_start, m_end)
            cash = t.get(cash_key, 0) if cash_key else 0
            upi = t.get(upi_key, 0) if upi_key else 0
            total_paid = cash + upi
            balance = rent - total_paid if rent > 0 else 0

            # Override balance from comment if exists
            if bal_key and t.get(bal_key, 0) > 0 and cash == 0 and upi == 0:
                balance = t[bal_key]

            raw_st = t.get(st_key, "")
            if raw_st == "PAID" or (total_paid >= rent and rent > 0): pay_st = "PAID"
            elif raw_st == "PARTIAL" or (total_paid > 0 and balance > 0): pay_st = "PARTIAL"
            elif raw_st == "EXIT": pay_st = "EXIT"
            elif raw_st == "NO SHOW": pay_st = "NO SHOW"
            elif raw_st == "ADVANCE": pay_st = "ADVANCE"
            elif total_paid == 0 and rent > 0: pay_st = "UNPAID"
            else: pay_st = raw_st or ""

            event = ""
            if t["checkin_date"] and m_start <= t["checkin_date"] <= m_end:
                event = "NO-SHOW" if t["status"] == "No-show" else "NEW CHECK-IN"
                stats["new"] += 1
            if t["status"] == "Exited" and t["checkout_date"] and m_start <= t["checkout_date"] <= m_end:
                event = ("EXITED" if not event else event + " + EXITED")
                stats["exits"] += 1

            # Monthly notes from comment parser
            notes_list = t["monthly_notes"].get(month_prefix, [])
            notes = "; ".join(notes_list) if notes_list else ""

            bld = t["block"]
            is_thor = bld.upper() == "THOR"

            stats["tenants"] += 1
            stats["cash"] += cash
            stats["upi"] += upi
            stats["rent"] += rent

            if is_thor: stats["thor_rent"] += rent; stats["thor_cash"] += cash; stats["thor_upi"] += upi
            else: stats["hulk_rent"] += rent; stats["hulk_cash"] += cash; stats["hulk_upi"] += upi

            if pay_st == "PAID": stats["paid"] += 1
            elif pay_st == "PARTIAL": stats["partial"] += 1
            elif pay_st == "UNPAID": stats["unpaid"] += 1

            if pay_st == "EXIT": pass
            elif pay_st == "NO SHOW" or event == "NO-SHOW":
                stats["noshow"] += 1
            else:
                bed_count = 2 if t["sharing"].lower() == "premium" else 1
                stats["beds"] += bed_count
                if t["sharing"].lower() == "premium": stats["premium"] += 1
                else: stats["regular"] += 1
                if is_thor: stats["thor_beds"] += bed_count
                else: stats["hulk_beds"] += bed_count

            m_rows.append([t["room"], t["name"], bld, t["sharing"],
                          rent, cash, upi, total_paid, balance,
                          pay_st, t["checkin"], event, notes])

        collected = stats["cash"] + stats["upi"]
        outstanding = stats["rent"] - collected
        vacant = TOTAL_BEDS - stats["beds"] - stats["noshow"]
        occ = round(stats["beds"] / TOTAL_BEDS * 100, 1) if TOTAL_BEDS else 0
        cpct = round(collected / stats["rent"] * 100, 1) if stats["rent"] else 0

        summary = [
            [label, "", "", "", "", "", "", "", "", "", "", "", ""],
            ["Occupancy", f"{stats['beds']} beds ({stats['regular']}+{stats['premium']}P)",
             f"No-show: {stats['noshow']}", f"Vacant: {vacant}", f"Occ: {occ}%",
             "Rent Expected", stats["rent"], "Collected", collected,
             "Outstanding", outstanding, f"Coll: {cpct}%", ""],
            ["New check-ins", stats["new"], "Exits", stats["exits"],
             "", "", "", "", "", "", "", "", ""],
            headers,
        ]

        ws.update(values=summary + m_rows, range_name="A1", value_input_option="USER_ENTERED")
        ws.format("A1:M1", {"textFormat": {"bold": True, "fontSize": 13}})
        ws.format("A2:M3", {"textFormat": {"bold": True}, "numberFormat": {"type": "NUMBER", "pattern": "#,##0"}})
        ws.format("A4:M4", {"textFormat": {"bold": True}, "backgroundColor": {"red": 0.85, "green": 0.9, "blue": 1.0}})
        ws.freeze(rows=4)
        try: ws.set_basic_filter(f"A4:M{4 + len(m_rows)}")
        except: pass

        all_month_data[label] = stats
        print(f"  {label}: {stats['tenants']} tenants | Beds:{stats['beds']} | "
              f"Cash:{stats['cash']:,.0f} UPI:{stats['upi']:,.0f} | "
              f"THOR:{stats['thor_beds']}beds HULK:{stats['hulk_beds']}beds")
        time.sleep(8)

    # ── DASHBOARD (built by Apps Script on refresh, but seed with data) ──
    # Just trigger a note — Apps Script will rebuild it properly
    ws = get_ws(sp, "DASHBOARD", 5, 3)
    ws.update(values=[
        ["Open Cozeevo menu > Refresh Dashboard"],
        ["Or edit any monthly tab to trigger auto-refresh"],
        ["Apps Script must be installed first (see gsheet_apps_script.js)"],
    ], range_name="A1", value_input_option="USER_ENTERED")
    print("  DASHBOARD: placeholder (Apps Script will rebuild)")
    time.sleep(5)

    # ── Cleanup ──────────────────────────────────────────────────────────
    for name in ["Sheet1", "ROOMS", "PAYMENTS", "CHANGES LOG", "MONTHLY VIEW",
                 "MONTHLY JAN 2026", "MONTHLY FEB 2026", "_LOOKUP", "COLLECT RENT"]:
        try: sp.del_worksheet(sp.worksheet(name))
        except: pass

    print(f"\n{'='*60}")
    print("DONE!")
    print(f"  TENANTS: {len(t_rows)} rows (master comments in col P)")
    for label, stats in all_month_data.items():
        c = stats["cash"] + stats["upi"]
        print(f"  {label}: {stats['tenants']}t {stats['beds']}beds Cash:{stats['cash']:,.0f} UPI:{stats['upi']:,.0f} Out:{stats['rent']-c:,.0f}")
    print(f"\nMonthly notes extracted from comments -> Notes column (M)")
    print(f"Master comments -> TENANTS col P (Master Comments)")
    print(f"\nPaste Apps Script + run setupTriggers for live dashboard")


if __name__ == "__main__":
    main()
