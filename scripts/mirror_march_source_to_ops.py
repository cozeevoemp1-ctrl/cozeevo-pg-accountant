"""
scripts/mirror_march_source_to_ops.py
======================================
Copy March data from Cozeevo Monthly stay source sheet into Ops v2
'MARCH 2026' tab 1:1. Bypasses DB so 100% match with source is guaranteed.

Rationale
---------
March is a frozen month. The authoritative record is the Cozeevo Monthly
stay sheet (not DB, not Ops sheet). This script ensures the Ops v2
MARCH 2026 tab mirrors the source exactly. After running, MARCH is
expected to be left untouched — no further sync_sheet_from_db for March.

Usage:
    venv/Scripts/python scripts/mirror_march_source_to_ops.py          # dry
    venv/Scripts/python scripts/mirror_march_source_to_ops.py --write  # commit
"""
import os
import re
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import dotenv_values
env = dotenv_values(".env")
os.environ.update({k: v for k, v in env.items() if v is not None and k not in os.environ})

import gspread
from google.oauth2.service_account import Credentials
from src.integrations.gsheets import CREDENTIALS_PATH, SHEET_ID, MONTHLY_HEADERS

SOURCE_ID = "1jOCVBkVurLNaht9HYKR6SFqGCciIoMWeOJkfKF9essk"

# Source column indices (0-based) from Cozeevo Monthly stay -> History
S = {
    "room": 0, "name": 1, "gender": 2, "phone": 3, "checkin": 4,
    "booking": 5, "deposit": 6, "maintenance": 7, "day_rent": 8,
    "monthly_rent": 9, "from_feb": 10, "from_may": 11, "sharing": 12,
    "paid_date": 13, "comments": 14, "staff": 15, "inout": 16,
    "block": 17, "floor": 18,
    "mar_rent": 26, "mar_balance": 31, "mar_cash": 32, "mar_upi": 33,
}


def pn(s):
    if s is None or s == "":
        return 0.0
    try:
        return float(str(s).replace(",", "").strip())
    except Exception:
        return 0.0


def ph_fmt(raw):
    d = re.sub(r"\D", "", str(raw or ""))
    if d.startswith("91") and len(d) == 12:
        d = d[2:]
    return f"+91{d}" if len(d) == 10 else str(raw or "")


def building_from_room(room_num):
    r = str(room_num or "").strip().upper()
    # THOR = 1xx-3xx, G/S floors; HULK = 4xx-6xx per project master data
    if not r:
        return ""
    try:
        n = int(re.sub(r"\D", "", r) or 0)
    except Exception:
        n = 0
    if r.startswith("G") or r.startswith("S") or (100 <= n <= 399):
        return "Cozeevo THOR"
    if 400 <= n <= 699:
        return "Cozeevo HULK"
    return ""


def main(write: bool):
    scopes = ["https://www.googleapis.com/auth/spreadsheets",
              "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=scopes)
    gc = gspread.authorize(creds)

    # Source
    src_ss = gc.open_by_key(SOURCE_ID)
    src_ws = src_ss.worksheet("History")
    src_rows = src_ws.get_all_values()

    # Build data rows (skip empty)
    out_rows = []
    cash_total = upi_total = bal_total = rent_total = 0.0
    active = exited = 0
    for r in src_rows[1:]:
        if not r or not (r[S["name"]] if len(r) > S["name"] else "").strip():
            continue
        name = r[S["name"]].strip()
        room = r[S["room"]].strip()
        phone = ph_fmt(r[S["phone"]] if len(r) > S["phone"] else "")
        sharing = (r[S["sharing"]] if len(r) > S["sharing"] else "").strip().lower()
        checkin = (r[S["checkin"]] if len(r) > S["checkin"] else "").strip()
        deposit = pn(r[S["deposit"]] if len(r) > S["deposit"] else 0)
        rent = pn(r[S["mar_rent"]] if len(r) > S["mar_rent"] else 0)
        cash = pn(r[S["mar_cash"]] if len(r) > S["mar_cash"] else 0)
        upi = pn(r[S["mar_upi"]] if len(r) > S["mar_upi"] else 0)
        balance = pn(r[S["mar_balance"]] if len(r) > S["mar_balance"] else 0)
        inout = (r[S["inout"]] if len(r) > S["inout"] else "").strip().upper()
        comments = r[S["comments"]] if len(r) > S["comments"] else ""

        total_paid = cash + upi
        rent_due = rent if rent else (cash + upi + balance)
        status = "PAID" if balance <= 0 and total_paid > 0 else ("PARTIAL" if total_paid > 0 else "UNPAID")
        is_exit = "EXIT" in inout or "OUT" in inout
        if is_exit:
            status = "EXIT"
            exited += 1
        elif total_paid > 0 or rent > 0:
            active += 1

        building = building_from_room(room)

        # Build row per MONTHLY_HEADERS
        row_map = {
            "Room": room,
            "Name": name,
            "Phone": phone,
            "Building": building,
            "Sharing": sharing,
            "Rent": int(rent) if rent else "",
            "Deposit": int(deposit) if deposit else "",
            "Rent Due": int(rent_due) if rent_due else "",
            "Cash": int(cash) if cash else "",
            "UPI": int(upi) if upi else "",
            "Total Paid": int(total_paid) if total_paid else "",
            "Balance": int(balance) if balance else 0,
            "Status": status,
            "Check-in": checkin,
            "Notice Date": "",
            "Event": "EXIT" if is_exit else "",
            "Notes": comments,
            "Prev Due": 0,
            "Entered By": "source_mirror_2026_04_23",
        }
        out_row = [row_map.get(h, "") for h in MONTHLY_HEADERS]
        out_rows.append(out_row)
        cash_total += cash
        upi_total += upi
        bal_total += balance
        rent_total += rent

    print(f"Rows to mirror: {len(out_rows)}")
    print(f"  Cash: Rs.{cash_total:,.0f}")
    print(f"  UPI:  Rs.{upi_total:,.0f}")
    print(f"  Bal:  Rs.{bal_total:,.0f}")
    print(f"  Rent: Rs.{rent_total:,.0f}")
    print(f"  Active: {active}  Exited: {exited}")

    if not write:
        print("\n[DRY RUN] Pass --write to apply.")
        return

    # Target
    tgt_ss = gc.open_by_key(SHEET_ID)
    tgt_ws = tgt_ss.worksheet("MARCH 2026")

    # Read first 7 rows (summary + header) so we preserve format
    header_block = tgt_ws.get("A1:Z7")
    num_cols = len(MONTHLY_HEADERS)
    last_col_letter = chr(ord("A") + num_cols - 1) if num_cols <= 26 else (
        "A" + chr(ord("A") + num_cols - 27)
    )

    # Clear rows 8 onward
    total_needed_rows = 7 + len(out_rows) + 10  # buffer
    cur_rows = tgt_ws.row_count
    if cur_rows < total_needed_rows:
        tgt_ws.add_rows(total_needed_rows - cur_rows)
    # Clear old data region
    clear_range = f"A8:{last_col_letter}{cur_rows}"
    tgt_ws.batch_clear([clear_range])

    # Write new rows at A8
    tgt_ws.update(
        values=out_rows,
        range_name=f"A8",
        value_input_option="USER_ENTERED",
    )

    # Rewrite summary block with correct March numbers
    summary = [
        ["", "", "", "", "", "March 2026", "", "", "", "", "", "", "", ""],
        ["OCCUPANCY", f"Active: {active}", "", f"No-show: 0", f"Exits: {exited}", "SOURCE MIRROR", "", "", "", "", "", "", "", ""],
        ["BUILDINGS", "", "", "", "", "", "", "", "", "", "", "", "", ""],
        ["COLLECTION", f"Cash: Rs.{cash_total:,.0f}", f"UPI: Rs.{upi_total:,.0f}",
         f"Collected: Rs.{cash_total+upi_total:,.0f}", f"Rent Billed: Rs.{rent_total:,.0f}",
         f"Prev Due: Rs.0", "", "", "", "", "", "", "", ""],
        ["STATUS", f"Balance Pending: Rs.{bal_total:,.0f}", "", "", "", "", "", "", "", "", "", "", "", ""],
        ["NOTICE", "Frozen month — mirror of Cozeevo Monthly stay source sheet (2026-04-23)", "", "", "", "", "", "", "", "", "", "", "", ""],
    ]
    tgt_ws.update(values=summary, range_name="A1:N6", value_input_option="USER_ENTERED")
    tgt_ws.update(values=[MONTHLY_HEADERS], range_name=f"A7:{last_col_letter}7", value_input_option="USER_ENTERED")

    print(f"\n[ok] Wrote {len(out_rows)} rows to 'MARCH 2026' — mirror of source sheet.")


if __name__ == "__main__":
    main("--write" in sys.argv)
