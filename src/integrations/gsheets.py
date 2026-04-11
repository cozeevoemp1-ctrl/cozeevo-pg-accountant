"""
src/integrations/gsheets.py
============================
Google Sheets integration for Cozeevo PG — NEW sheet format (v2).

Sheet ID: 1Hp5dTM7TcDEq75jgHEjvwtBjOolruGfQ7CVMzVqjdGw

TENANTS tab (master data) columns (0-indexed):
  [0] Room, [1] Name, [2] Phone, [3] Gender, [4] Building, [5] Floor,
  [6] Sharing, [7] Check-in, [8] Status, [9] Agreed Rent, [10] Deposit,
  [11] Booking, [12] Maintenance, [13] Notice Date, [14] Expected Exit,
  [15] Checkout Date, [16] Refund Status, [17] Refund Amount,
  [18] DOB, [19] Father Name, [20] Father Phone, [21] Address,
  [22] Emergency Contact, [23] Emergency Relationship, [24] Email,
  [25] Occupation, [26] Education, [27] Office Address, [28] Office Phone,
  [29] ID Type, [30] ID Number, [31] Food Pref, [32] Notes

Monthly tab (e.g. "APRIL 2026") columns (0-indexed):
  [0] Room, [1] Name, [2] Phone, [3] Building, [4] Sharing, [5] Rent Due,
  [6] Cash, [7] UPI, [8] Total Paid, [9] Balance, [10] Status,
  [11] Check-in, [12] Notice Date, [13] Event, [14] Notes, [15] Prev Due,
  [16] Entered By

Monthly tab row layout:
  Row 1: Month title (merged)
  Row 2: Summary (auto-updated by Apps Script)
  Row 3: Summary continued
  Row 4: Headers
  Row 5+: Tenant data

Design:
  - gspread (sync) wrapped in asyncio.to_thread for async compat
  - Worksheet handles cached for 5 minutes
  - Row lookup: room_number (col 0) exact match + tenant_name (col 1) fuzzy
  - Payments: ADD to existing value, never replace
  - Batch updates via worksheet.batch_update() to minimize API calls
  - Fire-and-forget from bot (errors logged, not raised to user)
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from datetime import datetime, date
from typing import Any, Optional

import gspread
from google.oauth2.service_account import Credentials

logger = logging.getLogger(__name__)

# -- Configuration ------------------------------------------------------------

SHEET_ID = os.getenv(
    "GSHEETS_SHEET_ID",
    "1Hp5dTM7TcDEq75jgHEjvwtBjOolruGfQ7CVMzVqjdGw",
)
CREDENTIALS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "credentials",
    "gsheets_service_account.json",
)

MONTH_NAMES = [
    "JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE",
    "JULY", "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER",
]

# -- Monthly tab column indices (0-indexed) ------------------------------------

M_ROOM = 0
M_NAME = 1
M_PHONE = 2
M_BUILDING = 3
M_SHARING = 4
M_RENT_DUE = 5
M_CASH = 6
M_UPI = 7
M_TOTAL_PAID = 8
M_BALANCE = 9
M_STATUS = 10
M_CHECKIN = 11
M_NOTICE_DATE = 12
M_EVENT = 13
M_NOTES = 14
M_PREV_DUE = 15
M_ENTERED_BY = 16

# -- TENANTS tab column indices (0-indexed) ------------------------------------

T_ROOM = 0
T_NAME = 1
T_PHONE = 2
T_GENDER = 3
T_BUILDING = 4
T_FLOOR = 5
T_SHARING = 6
T_CHECKIN = 7
T_STATUS = 8
T_AGREED_RENT = 9
T_DEPOSIT = 10
T_BOOKING = 11
T_MAINTENANCE = 12
T_NOTICE_DATE = 13
T_EXPECTED_EXIT = 14
T_CHECKOUT_DATE = 15
T_REFUND_STATUS = 16
T_REFUND_AMOUNT = 17
T_DOB = 18
T_FATHER_NAME = 19
T_FATHER_PHONE = 20
T_ADDRESS = 21
T_EMERGENCY_CONTACT = 22
T_EMERGENCY_RELATIONSHIP = 23
T_EMAIL = 24
T_OCCUPATION = 25
T_EDUCATION = 26
T_OFFICE_ADDRESS = 27
T_OFFICE_PHONE = 28
T_ID_TYPE = 29
T_ID_NUMBER = 30
T_FOOD_PREF = 31
T_NOTES = 32

MONTHLY_DATA_START_ROW = 5  # 1-based: rows 1-4 are title/summary/headers
TOTAL_BEDS = 291

# -- Spreadsheet + worksheet cache --------------------------------------------

_spreadsheet_cache: Optional[gspread.Spreadsheet] = None
_spreadsheet_cache_time: float = 0
_ws_cache: dict[str, tuple[gspread.Worksheet, float]] = {}
_CACHE_TTL = 300  # 5 minutes


def _get_spreadsheet_sync() -> gspread.Spreadsheet:
    """Return authorized gspread Spreadsheet handle, cached for 5 min."""
    global _spreadsheet_cache, _spreadsheet_cache_time

    now = time.time()
    if _spreadsheet_cache is not None and (now - _spreadsheet_cache_time) < _CACHE_TTL:
        return _spreadsheet_cache

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=scopes)
    gc = gspread.authorize(creds)
    ss = gc.open_by_key(SHEET_ID)

    _spreadsheet_cache = ss
    _spreadsheet_cache_time = now
    # Clear worksheet cache — old ws objects belong to the previous spreadsheet handle
    _ws_cache.clear()
    logger.info("GSheets: authorized and cached spreadsheet (ws cache cleared)")
    return ss


def _get_worksheet_sync(tab_name: str) -> gspread.Worksheet:
    """Return a worksheet by tab name, cached for 5 min. Retries once on auth failure."""
    global _spreadsheet_cache, _spreadsheet_cache_time
    now = time.time()
    if tab_name in _ws_cache:
        ws, cached_at = _ws_cache[tab_name]
        if (now - cached_at) < _CACHE_TTL:
            return ws

    ss = _get_spreadsheet_sync()
    try:
        ws = ss.worksheet(tab_name)
    except gspread.exceptions.APIError:
        # Auth may have expired mid-cache — force re-auth and retry
        logger.warning("GSheets: API error for '%s', forcing re-auth", tab_name)
        _spreadsheet_cache = None
        _spreadsheet_cache_time = 0
        _ws_cache.clear()
        ss = _get_spreadsheet_sync()
        ws = ss.worksheet(tab_name)  # let this raise if still failing

    _ws_cache[tab_name] = (ws, now)
    logger.info("GSheets: cached worksheet '%s'", tab_name)
    return ws


def _current_month_tab() -> str:
    """Return the tab name for the current month, e.g. 'APRIL 2026'."""
    today = date.today()
    return f"{MONTH_NAMES[today.month - 1]} {today.year}"


def _month_tab_for(month: int, year: int) -> str:
    """Return tab name for a specific month/year."""
    return f"{MONTH_NAMES[month - 1]} {year}"


# -- Helpers -------------------------------------------------------------------

_NUMERIC_RE = re.compile(r"^[\d,.\s]*$")


def _parse_numeric(cell_value: str) -> float:
    """Parse a numeric cell. Returns 0.0 for empty/blank. Raises ValueError for text."""
    val = cell_value.strip()
    if not val:
        return 0.0
    if _NUMERIC_RE.match(val):
        cleaned = val.replace(",", "").replace(" ", "")
        return float(cleaned) if cleaned else 0.0
    raise ValueError(f"Non-numeric cell: '{val}'")


def _safe_parse_numeric(cell_value: str) -> float:
    """Like _parse_numeric but returns 0.0 instead of raising."""
    try:
        return _parse_numeric(cell_value)
    except ValueError:
        return 0.0


def _find_tenant_tab(room_number: str, tenant_name: str) -> Optional[tuple[gspread.Worksheet, str, int, list[str]]]:
    """Find tenant across current + adjacent month tabs. Returns (ws, tab_name, row, row_data) or None."""
    from datetime import date as _d
    t = _d.today()
    # Search order: current month, next month, prev month
    months_to_try = []
    for offset in [0, 1, -1, 2]:
        m = t.month + offset
        y = t.year
        if m > 12: m, y = m - 12, y + 1
        if m < 1: m, y = m + 12, y - 1
        months_to_try.append(_month_tab_for(m, y))

    for tab_name in months_to_try:
        try:
            ws = _get_worksheet_sync(tab_name)
            found = _find_row_in_monthly(ws, room_number, tenant_name)
            if found:
                return (ws, tab_name, found[0], found[1])
        except Exception:
            continue
    return None


def _get_prev_month_info(room_number: str, tenant_name: str) -> dict:
    """Check previous month tab for tenant's balance + notes. Returns {balance, notes, tab}."""
    from datetime import date as _d
    t = _d.today()
    prev_m = t.month - 1
    prev_y = t.year
    if prev_m < 1:
        prev_m, prev_y = 12, prev_y - 1

    prev_tab = _month_tab_for(prev_m, prev_y)
    try:
        ws = _get_worksheet_sync(prev_tab)
        found = _find_row_in_monthly(ws, room_number, tenant_name)
        if found:
            _, row_data = found
            # Detect format
            all_vals = ws.get_all_values()
            hdr = all_vals[3] if len(all_vals) > 3 else []
            is_new = "phone" in str(hdr[2] if len(hdr) > 2 else "").lower()
            bal_col = 9 if is_new else 8
            notes_col = 14 if is_new else 12
            return {
                "balance": _safe_parse_numeric(_cell(row_data, bal_col)),
                "notes": _cell(row_data, notes_col),
                "tab": prev_tab,
            }
    except Exception:
        pass
    return {"balance": 0, "notes": "", "tab": ""}


def _cell(row_data: list[str], col: int) -> str:
    """Safe access to a row's column value."""
    return row_data[col].strip() if col < len(row_data) else ""


def _find_row_in_monthly(
    ws: gspread.Worksheet,
    room_number: str,
    tenant_name: str,
) -> Optional[tuple[int, list[str]]]:
    """
    Find tenant row in a monthly tab.
    Returns (1-based row index, row data list) or None.
    Skips rows 1-4 (title/summary/headers). Data starts at row 5.
    """
    all_values = ws.get_all_values()
    room_clean = room_number.strip().upper()
    name_lower = tenant_name.strip().lower()

    for i, row in enumerate(all_values):
        if i < 4:  # skip rows 1-4 (0-indexed: 0-3)
            continue
        cell_room = _cell(row, M_ROOM).upper()
        cell_name = _cell(row, M_NAME).lower()

        if cell_room != room_clean:
            continue

        # Fuzzy name match: substring in either direction
        if name_lower in cell_name or cell_name in name_lower:
            return (i + 1, row)  # gspread uses 1-based rows

    return None


def _find_row_in_tenants(
    ws: gspread.Worksheet,
    room_number: str,
    tenant_name: str,
) -> Optional[tuple[int, list[str]]]:
    """
    Find tenant row in the TENANTS master tab.
    Returns (1-based row index, row data list) or None.
    """
    all_values = ws.get_all_values()
    room_clean = room_number.strip().upper()
    name_lower = tenant_name.strip().lower()

    for i, row in enumerate(all_values):
        if i == 0:
            continue  # skip header
        cell_room = _cell(row, T_ROOM).upper()
        cell_name = _cell(row, T_NAME).lower()

        if cell_room != room_clean:
            continue

        if name_lower in cell_name or cell_name in name_lower:
            return (i + 1, row)

    return None


# -- Summary refresh (mirrors Apps Script updateMonthSummary) ------------------

def _refresh_summary_sync(tab_name: str) -> None:
    """
    Recalculate per-row metrics AND summary rows 2-3 for a monthly tab.
    Mirrors the Apps Script updateMonthSummary function so that
    API writes (which don't trigger onEdit) still refresh the dashboard.

    Per-row recalculation (for non-EXIT/NO-SHOW rows):
      Total Paid = Cash + UPI
      Balance = Rent Due + Prev Due - Total Paid
      Status = UNPAID / PARTIAL / PAID
    """
    try:
        ws = _get_worksheet_sync(tab_name)
        all_vals = ws.get_all_values()
        if len(all_vals) < 5:
            return

        # Detect column layout
        hdr = all_vals[3] if len(all_vals) > 3 else []
        is_new = "phone" in str(hdr[2] if len(hdr) > 2 else "").lower()
        if is_new:
            ci = {"rent": 5, "cash": 6, "upi": 7, "tp": 8, "bal": 9, "st": 10,
                  "building": 3, "sharing": 4, "event": 13, "prev": 15}
        else:
            ci = {"rent": 4, "cash": 5, "upi": 6, "tp": 7, "bal": 8, "st": 9,
                  "building": 2, "sharing": 3, "event": 11, "prev": 15}

        # ── Per-row recalculation ──
        row_updates = []  # list of batch update dicts
        for i in range(4, len(all_vals)):
            row = all_vals[i]
            if not row[0]:
                continue
            status = str(row[ci["st"]] if ci["st"] < len(row) else "").upper().strip()
            if status in ("EXIT", "NO SHOW", "ADVANCE", "CANCELLED"):
                continue

            cash = _safe_parse_numeric(_cell(row, ci["cash"]))
            upi = _safe_parse_numeric(_cell(row, ci["upi"]))
            rent = _safe_parse_numeric(_cell(row, ci["rent"]))
            prev_due = _safe_parse_numeric(_cell(row, ci["prev"])) if ci["prev"] < len(row) else 0.0

            tp = cash + upi
            bal = rent + prev_due - tp
            if bal < 0:
                bal = 0  # excess is deposit/advance, not overpayment
            st = "UNPAID" if tp == 0 else ("PAID" if bal <= 0 else "PARTIAL")

            sheet_row = i + 1  # 1-based
            row_updates.append({"range": gspread.utils.rowcol_to_a1(sheet_row, ci["tp"] + 1), "values": [[tp]]})
            row_updates.append({"range": gspread.utils.rowcol_to_a1(sheet_row, ci["bal"] + 1), "values": [[bal]]})
            row_updates.append({"range": gspread.utils.rowcol_to_a1(sheet_row, ci["st"] + 1), "values": [[st]]})

        if row_updates:
            ws.batch_update(row_updates, value_input_option="USER_ENTERED")

        # ── Re-read to aggregate summary stats from recalculated values ──
        all_vals = ws.get_all_values()

        beds = 0
        regular = 0
        premium = 0
        noshow = 0
        cash_total = 0
        upi_total = 0
        balance_total = 0
        paid = 0
        partial = 0
        unpaid = 0
        new_checkins = 0
        exits = 0
        thor_beds = 0
        hulk_beds = 0
        thor_tenants = 0
        hulk_tenants = 0

        for i in range(4, len(all_vals)):
            row = all_vals[i]
            if not row[0] or not row[1]:
                continue

            building = str(row[ci["building"]]).upper().strip()
            sharing = str(row[ci["sharing"]]).lower().strip()
            cash = _safe_parse_numeric(_cell(row, ci["cash"]))
            upi = _safe_parse_numeric(_cell(row, ci["upi"]))
            bal = _safe_parse_numeric(_cell(row, ci["bal"]))
            status = str(row[ci["st"]]).upper().strip() if ci["st"] < len(row) else ""
            event = str(row[ci["event"]]).upper().strip() if ci["event"] < len(row) else ""

            cash_total += cash
            upi_total += upi
            balance_total += bal

            if status == "PAID":
                paid += 1
            elif status == "PARTIAL":
                partial += 1
            elif status == "UNPAID":
                unpaid += 1

            if "NEW CHECK-IN" in event:
                new_checkins += 1
            if "EXIT" in event or status == "EXIT":
                exits += 1

            if status == "EXIT":
                continue
            if event == "NO-SHOW" or status == "NO SHOW":
                noshow += 1
                continue

            bed_count = 2 if sharing == "premium" else 1
            beds += bed_count
            if sharing == "premium":
                premium += 1
            else:
                regular += 1

            if building == "THOR":
                thor_beds += bed_count
                thor_tenants += 1
            else:
                hulk_beds += bed_count
                hulk_tenants += 1

        collected = cash_total + upi_total
        vacant = TOTAL_BEDS - beds - noshow
        occ_pct = f"{beds / TOTAL_BEDS * 100:.1f}" if TOTAL_BEDS > 0 else "0"

        last_col = "Q" if is_new else "O"
        num_cols = 17 if is_new else 15

        # Row 2: Occupancy + Collections
        r2 = [
            "Checked-in",
            f"{beds} beds ({regular}+{premium}P)",
            f"No-show: {noshow}",
            f"Vacant: {vacant}",
            f"Occ: {occ_pct}%",
            "Cash", cash_total, "UPI", upi_total, "Total", collected,
            f"Bal: {int(balance_total)}", "", "", "",
        ]
        if is_new:
            r2 += ["", ""]  # 16th + 17th col

        # Row 3: Building split + status
        r3 = [
            f"THOR: {thor_beds}b ({thor_tenants}t)",
            f"HULK: {hulk_beds}b ({hulk_tenants}t)",
            f"New: {new_checkins}",
            f"Exit: {exits}",
            "",
            f"PAID:{paid}", f"PARTIAL:{partial}", f"UNPAID:{unpaid}",
            "", "", "", "", "", "", "",
        ]
        if is_new:
            r3 += ["", ""]  # 16th + 17th col

        ws.update(values=[r2[:num_cols]], range_name=f"A2:{last_col}2", value_input_option="USER_ENTERED")
        ws.update(values=[r3[:num_cols]], range_name=f"A3:{last_col}3", value_input_option="USER_ENTERED")

        logger.info(
            "GSheets: refreshed summary for %s — %d beds, %d paid, %d partial, %d unpaid, collected=%d, balance=%d",
            tab_name, beds, paid, partial, unpaid, int(collected), int(balance_total),
        )
    except Exception as e:
        logger.warning("GSheets: summary refresh failed for %s: %s", tab_name, e)


# -- Core functions (sync) -----------------------------------------------------

def _update_payment_sync(
    room_number: str,
    tenant_name: str,
    amount: float,
    method: str,
    month: Optional[int] = None,
    year: Optional[int] = None,
    entered_by: str = "",
) -> dict:
    """
    Update payment in the monthly tab. ADDs amount to Cash or UPI column.
    Returns result dict.
    """
    # Input validation
    if not amount or amount <= 0:
        return {"success": False, "error": "Amount must be positive", "row": None, "tab": None,
                "rent_due": 0, "total_paid": 0, "balance": 0, "overpayment": 0, "warning": None}
    method = method.lower().strip()
    if method not in ("cash", "upi"):
        return {"success": False, "error": f"Invalid method '{method}', must be 'cash' or 'upi'",
                "row": None, "tab": None, "rent_due": 0, "total_paid": 0, "balance": 0,
                "overpayment": 0, "warning": None}

    today = date.today()
    if month is None:
        month = today.month
    if year is None:
        year = today.year

    tab_name = _month_tab_for(month, year)

    result: dict[str, Any] = {
        "success": False,
        "row": None,
        "tab": tab_name,
        "rent_due": 0.0,
        "total_paid": 0.0,
        "balance": 0.0,
        "overpayment": 0.0,
        "warning": None,
        "error": None,
    }

    try:
        ws = _get_worksheet_sync(tab_name)
    except gspread.exceptions.WorksheetNotFound:
        result["error"] = f"Tab '{tab_name}' not found in sheet"
        logger.error("GSheets: %s", result["error"])
        return result
    except Exception as e:
        result["error"] = f"Sheet auth/access failed: {e}"
        logger.error("GSheets: %s", result["error"])
        return result

    # Read ALL data once (avoid multiple API calls)
    all_vals = ws.get_all_values()

    # Find row
    room_clean = room_number.strip().upper()
    name_lower = tenant_name.strip().lower()
    found = None
    for i in range(4, len(all_vals)):  # skip rows 0-3 (title/summary/headers)
        r_data = all_vals[i]
        if not r_data or not r_data[0]:
            continue
        cell_room = str(r_data[0]).strip().upper()
        cell_name = str(r_data[1]).strip().lower() if len(r_data) > 1 else ""
        if cell_room == room_clean and (name_lower in cell_name or cell_name in name_lower):
            found = (i + 1, r_data)  # 1-based row
            break

    if found is None:
        result["error"] = f"Row not found for Room {room_number} / {tenant_name} in {tab_name}"
        logger.warning("GSheets: %s", result["error"])
        return result

    row, row_data = found
    result["row"] = row

    # Detect old vs new column layout
    header_row = all_vals[3] if len(all_vals) > 3 else []
    is_new = "phone" in str(header_row[2] if len(header_row) > 2 else "").lower()

    if is_new:
        col_cash, col_upi, col_rent, col_prev, col_tp, col_bal, col_st, col_notes = (
            M_CASH, M_UPI, M_RENT_DUE, M_PREV_DUE, M_TOTAL_PAID, M_BALANCE, M_STATUS, M_NOTES)
    else:
        # Old format: no Phone column, everything shifted -1
        col_cash, col_upi, col_rent, col_prev, col_tp, col_bal, col_st, col_notes = (
            5, 6, 4, 15, 7, 8, 9, 12)

    # Determine target column
    method_lower = method.lower()
    target_col = col_cash if method_lower == "cash" else col_upi
    other_col = col_upi if method_lower == "cash" else col_cash

    # Parse existing values
    try:
        existing_target = _parse_numeric(_cell(row_data, target_col))
    except ValueError:
        result["warning"] = (
            f"Cell contains text: '{_cell(row_data, target_col)[:40]}' — cannot add. "
            f"Please update manually."
        )
        logger.warning("GSheets: %s", result["warning"])
        return result

    existing_other = _safe_parse_numeric(_cell(row_data, other_col))
    rent_due = _safe_parse_numeric(_cell(row_data, col_rent))
    prev_due = _safe_parse_numeric(_cell(row_data, col_prev))

    new_target = existing_target + amount
    new_total_paid = new_target + existing_other
    total_due = rent_due + prev_due
    new_balance = total_due - new_total_paid

    result["rent_due"] = rent_due
    result["total_paid"] = new_total_paid
    result["balance"] = new_balance

    # Check previous month dues + notes
    prev_info = _get_prev_month_info(room_number, tenant_name)
    if prev_info["balance"] > 0:
        result["prev_dues"] = prev_info["balance"]
        result["prev_notes"] = prev_info["notes"]
        result["prev_tab"] = prev_info["tab"]

    if new_balance < 0:
        result["overpayment"] = abs(new_balance)
        result["warning"] = (
            f"Overpayment: total Rs.{int(new_total_paid):,} vs due Rs.{int(total_due):,} "
            f"(+Rs.{int(abs(new_balance)):,} extra)"
        )

    # Determine status
    if new_total_paid >= total_due and total_due > 0:
        new_status = "PAID"
    elif new_total_paid > 0:
        new_status = "PARTIAL"
    else:
        new_status = _cell(row_data, col_st) or "UNPAID"

    # Build notes append
    ts = datetime.now().strftime("%d-%b %H:%M")
    method_upper = method.upper()
    by_tag = f" by {entered_by}" if entered_by else ""
    note_entry = f"[{ts}] Rs.{int(amount):,} {method_upper}{by_tag}"
    existing_notes = _cell(row_data, col_notes)
    updated_notes = f"{existing_notes} | {note_entry}" if existing_notes else note_entry

    # Batch update: target payment col, Total Paid, Balance, Status, Notes
    try:
        batch = [
            {
                "range": gspread.utils.rowcol_to_a1(row, target_col + 1),
                "values": [[new_target]],
            },
            {
                "range": gspread.utils.rowcol_to_a1(row, col_tp + 1),
                "values": [[new_total_paid]],
            },
            {
                "range": gspread.utils.rowcol_to_a1(row, col_bal + 1),
                "values": [[new_balance]],
            },
            {
                "range": gspread.utils.rowcol_to_a1(row, col_st + 1),
                "values": [[new_status]],
            },
            {
                "range": gspread.utils.rowcol_to_a1(row, col_notes + 1),
                "values": [[updated_notes]],
            },
        ]
        # Add Entered By column if new format
        if is_new and entered_by:
            batch.append({
                "range": gspread.utils.rowcol_to_a1(row, M_ENTERED_BY + 1),
                "values": [[entered_by]],
            })
        ws.batch_update(batch, value_input_option="USER_ENTERED")
        result["success"] = True
        logger.info(
            "GSheets: row %d in %s — Room %s / %s — Rs.%s %s → total %s/%s, balance=%s, status=%s",
            row, tab_name, room_number, tenant_name, int(amount), method_upper,
            int(new_total_paid), int(total_due), int(new_balance), new_status,
        )
        # Refresh summary rows (API writes don't trigger Apps Script onEdit)
        _refresh_summary_sync(tab_name)
    except Exception as e:
        result["error"] = f"Batch update failed: {e}"
        logger.error("GSheets batch update error: %s", e)

    return result


def _add_tenant_sync(
    room_number: str,
    name: str,
    phone: str,
    gender: str,
    building: str,
    floor: str,
    sharing: str,
    checkin: str,
    agreed_rent: float,
    deposit: float,
    booking: float,
    maintenance: float,
    notes: str = "",
    # KYC fields
    dob: str = "",
    father_name: str = "",
    father_phone: str = "",
    address: str = "",
    emergency_contact: str = "",
    emergency_relationship: str = "",
    email: str = "",
    occupation: str = "",
    education: str = "",
    office_address: str = "",
    office_phone: str = "",
    id_type: str = "",
    id_number: str = "",
    food_pref: str = "",
) -> dict:
    """
    Add tenant to TENANTS master tab AND current monthly tab.
    Returns result dict.
    """
    result: dict[str, Any] = {
        "success": False,
        "tenants_row": None,
        "monthly_row": None,
        "monthly_tab": None,
        "error": None,
    }

    # Input validation
    if not room_number or not name or not phone:
        result["error"] = "Room, name, and phone are required"
        return result

    # Determine status: future check-in = no_show, past/today = active (match DB enum)
    from datetime import date as _date
    status = "active"
    checkin_display = checkin  # for sheet display (DD/MM/YYYY)
    try:
        from src.whatsapp.intent_detector import _extract_date_entity
        iso = _extract_date_entity(checkin)
        if iso:
            checkin_dt = _date.fromisoformat(iso)
            checkin_display = checkin_dt.strftime("%d/%m/%Y")
            if checkin_dt > _date.today():
                status = "no_show"
    except Exception:
        pass

    try:
        # -- TENANTS tab --
        tenants_ws = _get_worksheet_sync("TENANTS")
        tenants_row = [
            room_number,       # 0: Room
            name,              # 1: Name
            phone,             # 2: Phone
            gender,            # 3: Gender
            building,          # 4: Building
            floor,             # 5: Floor
            sharing,           # 6: Sharing
            checkin_display,   # 7: Check-in (DD/MM/YYYY, Indian format)
            status,            # 8: Status (active/no_show, matches DB enum)
            agreed_rent,       # 9: Agreed Rent
            deposit,           # 10: Deposit
            booking,           # 11: Booking
            maintenance,       # 12: Maintenance
            "",                # 13: Notice Date
            "",                # 14: Expected Exit
            "",                # 15: Checkout Date
            "",                # 16: Refund Status
            "",                # 17: Refund Amount
            dob,               # 18: DOB
            father_name,       # 19: Father Name
            father_phone,      # 20: Father Phone
            address,           # 21: Address
            emergency_contact, # 22: Emergency Contact
            emergency_relationship,  # 23: Emergency Relationship
            email,             # 24: Email
            occupation,        # 25: Occupation
            education,         # 26: Education
            office_address,    # 27: Office Address
            office_phone,      # 28: Office Phone
            id_type,           # 29: ID Type
            id_number,         # 30: ID Number
            food_pref,         # 31: Food Pref
            notes,             # 32: Notes
        ]
        t_data = tenants_ws.get_all_values()
        t_next = len(t_data) + 1
        tenants_ws.update(values=[tenants_row], range_name=f"A{t_next}", value_input_option="USER_ENTERED")
        result["tenants_row"] = t_next
        logger.info("GSheets: added tenant %s to TENANTS tab at row %d", name, result["tenants_row"])

        # -- Monthly tab (use checkin month, not current month) --
        checkin_month, checkin_year = None, None
        if checkin:
            from src.whatsapp.intent_detector import _extract_date_entity
            iso = _extract_date_entity(checkin)
            if iso:
                parts = iso.split("-")
                checkin_year, checkin_month = int(parts[0]), int(parts[1])
        tab_name = _month_tab_for(checkin_month, checkin_year) if checkin_month else _current_month_tab()
        result["monthly_tab"] = tab_name
        try:
            monthly_ws = _get_worksheet_sync(tab_name)
        except gspread.exceptions.WorksheetNotFound:
            result["error"] = f"Monthly tab '{tab_name}' not found — added to TENANTS only"
            result["success"] = True  # partial success
            logger.warning("GSheets: %s", result["error"])
            return result

        # Detect old vs new format
        all_vals = monthly_ws.get_all_values()
        header_row = all_vals[3] if len(all_vals) > 3 else []
        is_new = "phone" in str(header_row[2] if len(header_row) > 2 else "").lower()

        if is_new:
            monthly_row = [
                room_number, name, phone, building, sharing,
                agreed_rent, "", "", 0, agreed_rent, "UNPAID",
                checkin_display, "", "", notes, 0,
            ]
        else:
            # Old format: no Phone column (15 cols)
            monthly_row = [
                room_number, name, building, sharing,
                agreed_rent, "", "", 0, agreed_rent, "UNPAID",
                checkin_display, "", notes, 0, 0,
            ]
        # Use update (not append_row) because filters block append
        next_row = len(all_vals) + 1
        monthly_ws.update(values=[monthly_row], range_name=f"A{next_row}", value_input_option="USER_ENTERED")
        result["monthly_row"] = next_row
        result["success"] = True
        logger.info(
            "GSheets: added tenant %s to monthly tab '%s' at row %d",
            name, tab_name, result["monthly_row"],
        )
        # Refresh summary rows
        _refresh_summary_sync(tab_name)

    except Exception as e:
        result["error"] = f"Add tenant failed: {e}"
        logger.error("GSheets add_tenant error: %s", e)

    return result


def _record_checkout_sync(
    room_number: str,
    tenant_name: str,
    notice_date: Optional[str] = None,
    exit_date: Optional[str] = None,
) -> dict:
    """
    Mark tenant as EXIT in the current monthly tab.
    Updates Event col to 'EXIT', Status col to 'EXIT'.
    Optionally sets Notice Date.
    Also updates TENANTS tab Status to 'EXIT'.
    """
    result: dict[str, Any] = {
        "success": False,
        "row": None,
        "tab": None,
        "error": None,
    }

    try:
        # -- Monthly tab (search current + adjacent months) --
        tenant_tab = _find_tenant_tab(room_number, tenant_name)
        if tenant_tab is None:
            result["error"] = f"Row not found for Room {room_number} / {tenant_name}"
            logger.warning("GSheets: %s", result["error"])
            return result

        ws, tab_name, row, row_data = tenant_tab
        result["tab"] = tab_name
        result["row"] = row

        batch = [
            {
                "range": gspread.utils.rowcol_to_a1(row, M_EVENT + 1),
                "values": [["EXIT"]],
            },
            {
                "range": gspread.utils.rowcol_to_a1(row, M_STATUS + 1),
                "values": [["EXIT"]],
            },
        ]
        if notice_date:
            batch.append({
                "range": gspread.utils.rowcol_to_a1(row, M_NOTICE_DATE + 1),
                "values": [[notice_date]],
            })

        ws.batch_update(batch, value_input_option="USER_ENTERED")
        logger.info(
            "GSheets: checkout Room %s / %s in %s at row %d",
            room_number, tenant_name, tab_name, row,
        )

        # -- TENANTS tab --
        try:
            tenants_ws = _get_worksheet_sync("TENANTS")
            t_found = _find_row_in_tenants(tenants_ws, room_number, tenant_name)
            if t_found:
                t_row, _ = t_found
                checkout_str = exit_date or datetime.now().strftime("%d/%m/%Y")
                t_batch = [
                    {
                        "range": gspread.utils.rowcol_to_a1(t_row, T_STATUS + 1),
                        "values": [["Exited"]],
                    },
                    {
                        "range": gspread.utils.rowcol_to_a1(t_row, T_CHECKOUT_DATE + 1),
                        "values": [[checkout_str]],
                    },
                ]
                if notice_date:
                    t_batch.append({
                        "range": gspread.utils.rowcol_to_a1(t_row, T_NOTICE_DATE + 1),
                        "values": [[notice_date]],
                    })
                tenants_ws.batch_update(t_batch, value_input_option="USER_ENTERED")
                logger.info("GSheets: updated TENANTS tab status to EXIT for %s", tenant_name)
        except Exception as e:
            logger.warning("GSheets: TENANTS tab update failed (checkout still recorded): %s", e)

        result["success"] = True
        # Refresh summary rows
        _refresh_summary_sync(tab_name)

    except Exception as e:
        result["error"] = f"Checkout failed: {e}"
        logger.error("GSheets record_checkout error: %s", e)

    return result


def _record_notice_sync(
    room_number: str,
    tenant_name: str,
    notice_date: str,
    expected_exit: str = "",
) -> dict:
    """
    Update Notice Date + Expected Exit in monthly tab (if exists) and TENANTS tab.

    For future-month exits (e.g. "exiting in June"), the monthly tab won't exist yet.
    We still write to the TENANTS tab — the monthly tab will be populated when
    Apps Script creates it.
    """
    result: dict[str, Any] = {
        "success": False,
        "row": None,
        "tab": None,
        "error": None,
    }

    try:
        # -- Monthly tab (search current + adjacent months) --
        # Gracefully skip if tab doesn't exist (future month)
        tenant_tab = _find_tenant_tab(room_number, tenant_name)
        if tenant_tab is not None:
            ws, tab_name, _row, _row_data = tenant_tab
            result["tab"] = tab_name
            result["row"] = _row

            ws.batch_update(
                [{"range": gspread.utils.rowcol_to_a1(_row, M_NOTICE_DATE + 1), "values": [[notice_date]]}],
                value_input_option="USER_ENTERED",
            )
            logger.info(
                "GSheets: notice date %s for Room %s / %s in %s at row %d",
                notice_date, room_number, tenant_name, tab_name, _row,
            )
        else:
            logger.info(
                "GSheets: monthly tab not found for Room %s / %s — future exit, skipping monthly tab",
                room_number, tenant_name,
            )

        # -- TENANTS tab (always written — this is the master record) --
        try:
            tenants_ws = _get_worksheet_sync("TENANTS")
            t_found = _find_row_in_tenants(tenants_ws, room_number, tenant_name)
            if t_found:
                t_row, _ = t_found
                updates = [
                    {"range": gspread.utils.rowcol_to_a1(t_row, T_NOTICE_DATE + 1), "values": [[notice_date]]},
                ]
                if expected_exit:
                    updates.append(
                        {"range": gspread.utils.rowcol_to_a1(t_row, T_EXPECTED_EXIT + 1), "values": [[expected_exit]]},
                    )
                tenants_ws.batch_update(updates, value_input_option="USER_ENTERED")
                logger.info("GSheets: updated TENANTS tab notice=%s expected_exit=%s for %s", notice_date, expected_exit, tenant_name)
        except Exception as e:
            logger.warning("GSheets: TENANTS tab notice update failed: %s", e)

        result["success"] = True
        # Refresh summary rows if monthly tab was updated
        if tenant_tab is not None:
            _refresh_summary_sync(tab_name)

    except Exception as e:
        result["error"] = f"Record notice failed: {e}"
        logger.error("GSheets record_notice error: %s", e)

    return result


# -- Async wrappers (public API) -----------------------------------------------

async def update_payment(
    room_number: str,
    tenant_name: str,
    amount: float,
    method: str,
    month: Optional[int] = None,
    year: Optional[int] = None,
    entered_by: str = "",
) -> dict:
    """
    Async entry point — update payment in Google Sheet monthly tab.

    Args:
        room_number: e.g. "102"
        tenant_name: tenant name for row lookup
        amount: payment amount
        method: "cash" or "upi"
        month: month number (1-12). None = current month
        year: year. None = current year
        entered_by: name of person who logged this payment (for audit trail)

    Returns dict: success, row, tab, rent_due, total_paid, balance, overpayment, warning, error
    """
    return await asyncio.to_thread(
        _update_payment_sync, room_number, tenant_name, amount, method, month, year, entered_by,
    )


def _void_payment_sync(
    room_number: str,
    tenant_name: str,
    amount: float,
    method: str,
    month: Optional[int] = None,
    year: Optional[int] = None,
) -> dict:
    """
    Reverse/void a payment in the monthly tab. SUBTRACTS amount from Cash or UPI column.
    """
    result = {"success": False, "error": None}
    method = method.lower().strip()
    if method not in ("cash", "upi"):
        method = "cash"  # fallback

    today = date.today()
    if month is None:
        month = today.month
    if year is None:
        year = today.year

    tab_name = _month_tab_for(month, year)
    try:
        ws = _get_worksheet_sync(tab_name)
    except gspread.WorksheetNotFound:
        result["error"] = f"Tab '{tab_name}' not found"
        return result
    except Exception as e:
        result["error"] = f"Sheet access failed: {e}"
        return result

    all_vals = ws.get_all_values()
    room_clean = room_number.strip().upper()
    name_lower = tenant_name.strip().lower()
    found = None
    for i in range(4, len(all_vals)):
        r_data = all_vals[i]
        if not r_data or not r_data[0]:
            continue
        cell_room = str(r_data[0]).strip().upper()
        cell_name = str(r_data[1]).strip().lower() if len(r_data) > 1 else ""
        if cell_room == room_clean and (name_lower in cell_name or cell_name in name_lower):
            found = (i + 1, r_data)
            break

    if found is None:
        result["error"] = f"Row not found for Room {room_number} / {tenant_name} in {tab_name}"
        return result

    row, row_data = found

    header_row = all_vals[3] if len(all_vals) > 3 else []
    is_new = "phone" in str(header_row[2] if len(header_row) > 2 else "").lower()

    if is_new:
        col_cash, col_upi, col_rent, col_prev, col_tp, col_bal, col_st, col_notes = (
            M_CASH, M_UPI, M_RENT_DUE, M_PREV_DUE, M_TOTAL_PAID, M_BALANCE, M_STATUS, M_NOTES)
    else:
        col_cash, col_upi, col_rent, col_prev, col_tp, col_bal, col_st, col_notes = (
            5, 6, 4, 15, 7, 8, 9, 12)

    target_col = col_cash if method == "cash" else col_upi
    other_col = col_upi if method == "cash" else col_cash

    existing_target = _safe_parse_numeric(_cell(row_data, target_col))
    existing_other = _safe_parse_numeric(_cell(row_data, other_col))
    rent_due = _safe_parse_numeric(_cell(row_data, col_rent))
    prev_due = _safe_parse_numeric(_cell(row_data, col_prev))

    new_target = max(0, existing_target - amount)  # never go negative
    new_total_paid = new_target + existing_other
    total_due = rent_due + prev_due
    new_balance = total_due - new_total_paid

    if new_total_paid >= total_due and total_due > 0:
        new_status = "PAID"
    elif new_total_paid > 0:
        new_status = "PARTIAL"
    else:
        new_status = "UNPAID"

    # Remove the specific payment note that was added when this payment was logged
    # Notes format: "[03-Apr 11:00] Rs.5,000 UPI by Kiran | [other notes]"
    existing_notes = _cell(row_data, col_notes)
    import re as _re
    # Match pattern: [date time] Rs.AMOUNT METHOD ... (with optional "by Name")
    amount_str = f"{int(amount):,}"
    method_upper = method.upper()
    # Remove the matching note entry (last occurrence — most recent payment)
    pattern = _re.compile(
        r'\s*\|?\s*\[\d{2}-\w{3}\s\d{2}:\d{2}\]\s*Rs\.' + _re.escape(amount_str)
        + r'\s+' + _re.escape(method_upper) + r'[^|]*',
        _re.IGNORECASE,
    )
    updated_notes = pattern.sub('', existing_notes).strip(' |')
    if not updated_notes:
        updated_notes = ""

    try:
        batch = [
            {"range": gspread.utils.rowcol_to_a1(row, target_col + 1), "values": [[new_target]]},
            {"range": gspread.utils.rowcol_to_a1(row, col_tp + 1), "values": [[new_total_paid]]},
            {"range": gspread.utils.rowcol_to_a1(row, col_bal + 1), "values": [[new_balance]]},
            {"range": gspread.utils.rowcol_to_a1(row, col_st + 1), "values": [[new_status]]},
            {"range": gspread.utils.rowcol_to_a1(row, col_notes + 1), "values": [[updated_notes]]},
        ]
        ws.batch_update(batch, value_input_option="USER_ENTERED")
        result["success"] = True
        logger.info("GSheets VOID: row %d in %s — Room %s / %s — Rs.%s %s",
                     row, tab_name, room_number, tenant_name, int(amount), method.upper())
        _refresh_summary_sync(tab_name)
    except Exception as e:
        result["error"] = f"Batch update failed: {e}"
        logger.error("GSheets void error: %s", e)

    return result


async def void_payment(
    room_number: str,
    tenant_name: str,
    amount: float,
    method: str,
    month: Optional[int] = None,
    year: Optional[int] = None,
) -> dict:
    """Async entry point — void/reverse a payment in Google Sheet monthly tab."""
    return await asyncio.to_thread(
        _void_payment_sync, room_number, tenant_name, amount, method, month, year,
    )


async def add_tenant(
    room_number: str,
    name: str,
    phone: str,
    gender: str,
    building: str,
    floor: str,
    sharing: str,
    checkin: str,
    agreed_rent: float,
    deposit: float,
    booking: float,
    maintenance: float,
    notes: str = "",
    # KYC fields
    dob: str = "",
    father_name: str = "",
    father_phone: str = "",
    address: str = "",
    emergency_contact: str = "",
    emergency_relationship: str = "",
    email: str = "",
    occupation: str = "",
    education: str = "",
    office_address: str = "",
    office_phone: str = "",
    id_type: str = "",
    id_number: str = "",
    food_pref: str = "",
) -> dict:
    """
    Async entry point — add tenant to TENANTS tab + current monthly tab.

    Returns dict: success, tenants_row, monthly_row, monthly_tab, error
    """
    return await asyncio.to_thread(
        _add_tenant_sync, room_number, name, phone, gender, building, floor,
        sharing, checkin, agreed_rent, deposit, booking, maintenance, notes,
        dob, father_name, father_phone, address, emergency_contact,
        emergency_relationship, email, occupation, education, office_address,
        office_phone, id_type, id_number, food_pref,
    )


async def record_checkout(
    room_number: str,
    tenant_name: str,
    notice_date: Optional[str] = None,
    exit_date: Optional[str] = None,
) -> dict:
    """
    Async entry point — mark tenant as EXIT in monthly tab + TENANTS tab.

    Returns dict: success, row, tab, error
    """
    return await asyncio.to_thread(
        _record_checkout_sync, room_number, tenant_name, notice_date, exit_date,
    )


async def record_notice(
    room_number: str,
    tenant_name: str,
    notice_date: str,
    expected_exit: str = "",
) -> dict:
    """
    Async entry point — update Notice Date + Expected Exit in monthly tab + TENANTS tab.

    Returns dict: success, row, tab, error
    """
    return await asyncio.to_thread(
        _record_notice_sync, room_number, tenant_name, notice_date, expected_exit,
    )


# -- Update check-in date ------------------------------------------------------

def _update_checkin_sync(room_number: str, tenant_name: str, new_checkin: str) -> dict:
    """Update check-in date in TENANTS tab and current monthly tab."""
    result: dict[str, Any] = {"success": False, "error": None}

    try:
        # Parse to DD/MM/YYYY display format
        from src.whatsapp.intent_detector import _extract_date_entity
        iso = _extract_date_entity(new_checkin)
        if iso:
            checkin_display = date.fromisoformat(iso).strftime("%d/%m/%Y")
        else:
            checkin_display = new_checkin

        # -- TENANTS tab --
        tenants_ws = _get_worksheet_sync("TENANTS")
        t_data = tenants_ws.get_all_values()
        room_clean = room_number.strip().upper()
        name_lower = tenant_name.strip().lower()

        for i in range(1, len(t_data)):
            row = t_data[i]
            if (str(row[T_ROOM]).strip().upper() == room_clean and
                    name_lower in str(row[T_NAME]).strip().lower()):
                cell = gspread.utils.rowcol_to_a1(i + 1, T_CHECKIN + 1)
                tenants_ws.update(values=[[checkin_display]], range_name=cell, value_input_option="USER_ENTERED")
                logger.info("GSheets: updated checkin for %s in TENANTS row %d", tenant_name, i + 1)
                break

        # -- Monthly tabs: search all tabs for this tenant --
        ss = _get_spreadsheet_sync()
        for ws_meta in ss.worksheets():
            tab = ws_meta.title
            if not any(m in tab.upper() for m in MONTH_NAMES):
                continue
            try:
                ws = _get_worksheet_sync(tab)
                all_vals = ws.get_all_values()
                header_row = all_vals[3] if len(all_vals) > 3 else []
                is_new = "phone" in str(header_row[2] if len(header_row) > 2 else "").lower()
                col_checkin = M_CHECKIN if is_new else 10  # old format

                for j in range(4, len(all_vals)):
                    r = all_vals[j]
                    if (str(r[0]).strip().upper() == room_clean and
                            name_lower in str(r[1]).strip().lower()):
                        cell = gspread.utils.rowcol_to_a1(j + 1, col_checkin + 1)
                        ws.update(values=[[checkin_display]], range_name=cell, value_input_option="USER_ENTERED")
                        logger.info("GSheets: updated checkin in '%s' row %d", tab, j + 1)
                        break
            except Exception:
                continue

        result["success"] = True
    except Exception as e:
        result["error"] = f"Update checkin failed: {e}"
        logger.error("GSheets: %s", result["error"])

    return result


async def update_checkin(room_number: str, tenant_name: str, new_checkin: str) -> dict:
    """Async entry point — update check-in date in TENANTS + monthly tabs."""
    return await asyncio.to_thread(_update_checkin_sync, room_number, tenant_name, new_checkin)


# -- Update notes in monthly tab -----------------------------------------------

def _update_notes_sync(room_number: str, tenant_name: str, notes: str,
                       month: Optional[int] = None, year: Optional[int] = None) -> dict:
    """Update/replace notes for a tenant in a monthly tab."""
    result: dict[str, Any] = {"success": False, "error": None, "tab": None}

    today = date.today()
    if month is None:
        month = today.month
    if year is None:
        year = today.year

    tab_name = _month_tab_for(month, year)
    result["tab"] = tab_name

    try:
        ws = _get_worksheet_sync(tab_name)
        all_vals = ws.get_all_values()
        header_row = all_vals[3] if len(all_vals) > 3 else []
        is_new = "phone" in str(header_row[2] if len(header_row) > 2 else "").lower()
        col_notes = M_NOTES if is_new else 12

        room_clean = room_number.strip().upper()
        name_lower = tenant_name.strip().lower()

        for i in range(4, len(all_vals)):
            r = all_vals[i]
            if (str(r[0]).strip().upper() == room_clean and
                    name_lower in str(r[1]).strip().lower()):
                cell = gspread.utils.rowcol_to_a1(i + 1, col_notes + 1)
                ws.update(values=[[notes]], range_name=cell, value_input_option="USER_ENTERED")
                result["success"] = True
                logger.info("GSheets: updated notes for %s in '%s' row %d", tenant_name, tab_name, i + 1)
                return result

        result["error"] = f"Row not found for {room_number}/{tenant_name} in {tab_name}"
    except gspread.exceptions.WorksheetNotFound:
        result["error"] = f"Tab '{tab_name}' not found"
    except Exception as e:
        result["error"] = f"Update notes failed: {e}"

    return result


async def update_notes(room_number: str, tenant_name: str, notes: str,
                       month: Optional[int] = None, year: Optional[int] = None) -> dict:
    """Async entry point — update notes in monthly tab."""
    return await asyncio.to_thread(_update_notes_sync, room_number, tenant_name, notes, month, year)


async def sync_notes_with_retry(
    room_number: str,
    tenant_name: str,
    notes: str,
    month: Optional[int] = None,
    year: Optional[int] = None,
    max_retries: int = 3,
) -> dict:
    """
    Update notes in Sheet with retry. Up to max_retries attempts.
    Returns the result dict from the last attempt.
    """
    result = {}
    for attempt in range(max_retries):
        result = await update_notes(room_number, tenant_name, notes, month, year)
        if result.get("success"):
            return result
        if attempt < max_retries - 1:
            await asyncio.sleep(1 * (attempt + 1))  # backoff: 1s, 2s
            logger.warning("GSheets sync retry %d/%d for %s: %s", attempt + 1, max_retries, tenant_name, result.get("error"))
    logger.error("GSheets sync FAILED after %d retries for %s/%s: %s", max_retries, room_number, tenant_name, result.get("error"))
    return result


def _update_tenants_tab_notes_sync(room_number: str, tenant_name: str, notes: str) -> dict:
    """Update permanent notes in the TENANTS tab."""
    result: dict[str, Any] = {"success": False, "error": None}
    try:
        ws = _get_worksheet_sync("TENANTS")
        all_vals = ws.get_all_values()
        room_clean = room_number.strip().upper()
        name_lower = tenant_name.strip().lower()
        # Find notes column — scan header for "Notes" or "Comment"
        header = all_vals[0] if all_vals else []
        notes_col = None
        for i, h in enumerate(header):
            if h.strip().lower() in ("notes", "comment", "remarks"):
                notes_col = i
                break
        if notes_col is None:
            result["error"] = "Notes column not found in TENANTS tab"
            return result

        assert notes_col is not None  # guarded above
        col_idx: int = notes_col
        for i in range(1, len(all_vals)):
            r = all_vals[i]
            if (str(r[0]).strip().upper() == room_clean and
                    name_lower in str(r[1]).strip().lower()):
                cell = gspread.utils.rowcol_to_a1(i + 1, col_idx + 1)
                ws.update(values=[[notes]], range_name=cell, value_input_option="USER_ENTERED")
                result["success"] = True
                logger.info("GSheets: updated TENANTS notes for %s row %d", tenant_name, i + 1)
                return result

        result["error"] = f"Row not found for {room_number}/{tenant_name} in TENANTS"
    except Exception as e:
        result["error"] = f"TENANTS notes update failed: {e}"
    return result


async def sync_tenants_tab_notes(
    room_number: str,
    tenant_name: str,
    notes: str,
    max_retries: int = 3,
) -> dict:
    """Async entry point — update permanent notes in TENANTS tab with retry."""
    result = {}
    for attempt in range(max_retries):
        result = await asyncio.to_thread(_update_tenants_tab_notes_sync, room_number, tenant_name, notes)
        if result.get("success"):
            return result
        if attempt < max_retries - 1:
            await asyncio.sleep(1 * (attempt + 1))
            logger.warning("GSheets TENANTS sync retry %d/%d for %s: %s", attempt + 1, max_retries, tenant_name, result.get("error"))
    logger.error("GSheets TENANTS sync FAILED after %d retries for %s: %s", max_retries, tenant_name, result.get("error"))
    return result


# -- Update KYC gender on TENANTS tab after onboarding approval ----------------

def _update_tenant_gender_sync(phone: str, gender: str) -> dict:
    """Find tenant row by phone in TENANTS tab and update gender column."""
    result: dict[str, Any] = {"success": False, "error": None}
    if not phone or not gender:
        result["error"] = "Phone and gender required"
        return result

    try:
        ws = _get_worksheet_sync("TENANTS")
        all_vals = ws.get_all_values()
        phone_clean = phone.strip().replace("+91", "").replace(" ", "")

        for i, row in enumerate(all_vals):
            if i == 0:
                continue  # skip header
            cell_phone = _cell(row, T_PHONE).strip().replace("+91", "").replace(" ", "")
            if cell_phone == phone_clean:
                cell_ref = gspread.utils.rowcol_to_a1(i + 1, T_GENDER + 1)
                ws.update(values=[[gender]], range_name=cell_ref, value_input_option="USER_ENTERED")
                result["success"] = True
                logger.info("GSheets: updated gender for phone %s to '%s' at row %d", phone, gender, i + 1)
                return result

        result["error"] = f"Tenant with phone {phone} not found in TENANTS tab"
    except Exception as e:
        result["error"] = f"Update gender failed: {e}"
    return result


async def update_tenant_gender(phone: str, gender: str) -> dict:
    """Async entry point — update gender in TENANTS tab by phone."""
    return await asyncio.to_thread(_update_tenant_gender_sync, phone, gender)


# -- Convenience: get sheet for direct access ----------------------------------

async def get_sheet(tab_name: Optional[str] = None) -> gspread.Worksheet:
    """Async wrapper — returns worksheet by tab name (default: current month)."""
    if tab_name is None:
        tab_name = _current_month_tab()
    return await asyncio.to_thread(_get_worksheet_sync, tab_name)


# ── Column index map (0-based) for the 17-col monthly tab layout ─────────────
T_ROOM = 0; T_NAME = 1; T_PHONE = 2; T_BUILDING = 3; T_SHARING = 4
T_RENT = 5; T_CASH = 6; T_UPI = 7; T_TOTAL_PAID = 8; T_BALANCE = 9
T_STATUS = 10; T_CHECKIN = 11; T_NOTICE_DATE = 12; T_EVENT = 13
T_NOTES = 14; T_PREV_DUE = 15

_FIELD_TO_COL = {
    "sharing_type": T_SHARING,
    "sharing": T_SHARING,
    "agreed_rent": T_RENT,
    "rent": T_RENT,
    "phone": T_PHONE,
    "notes": T_NOTES,
    "status": T_STATUS,
}


def _update_tenant_field_sync(
    room_number: str,
    tenant_name: str,
    field: str,
    new_value: str,
    tab_name: Optional[str] = None,
) -> dict:
    """
    Update a single field for a tenant row on the monthly Sheet tab.
    Finds the row by room_number + tenant_name match.
    """
    result = {"success": False, "error": None}

    col_idx = _FIELD_TO_COL.get(field)
    if col_idx is None:
        result["error"] = f"Unknown field '{field}' — not mapped to a Sheet column"
        return result

    if tab_name is None:
        tab_name = _current_month_tab()

    try:
        ws = _get_worksheet_sync(tab_name)
        all_vals = ws.get_all_values()

        # Find the row
        target_row = None
        for i in range(4, len(all_vals)):
            row = all_vals[i]
            if not row[0] or not row[1]:
                continue
            row_room = str(row[0]).strip()
            row_name = str(row[1]).strip().lower()
            if row_room == str(room_number) and tenant_name.lower() in row_name:
                target_row = i + 1  # 1-based for gspread
                break

        if not target_row:
            # Try name-only match
            for i in range(4, len(all_vals)):
                row = all_vals[i]
                if not row[1]:
                    continue
                if tenant_name.lower() in str(row[1]).strip().lower():
                    target_row = i + 1
                    break

        if not target_row:
            result["error"] = f"Tenant '{tenant_name}' not found on {tab_name} tab"
            return result

        # Update the cell
        ws.update_cell(target_row, col_idx + 1, new_value)  # gspread is 1-based
        result["success"] = True
        logger.info(f"[GSheets] Updated {tenant_name} row {target_row}: {field} = {new_value} on {tab_name}")

    except Exception as e:
        result["error"] = str(e)
        logger.error(f"[GSheets] Failed to update {tenant_name}.{field}: {e}")

    return result


async def update_tenant_field(
    room_number: str,
    tenant_name: str,
    field: str,
    new_value: str,
    tab_name: Optional[str] = None,
) -> dict:
    """Async entry point — update a tenant field on the Sheet."""
    return await asyncio.to_thread(
        _update_tenant_field_sync, room_number, tenant_name, field, new_value, tab_name,
    )
