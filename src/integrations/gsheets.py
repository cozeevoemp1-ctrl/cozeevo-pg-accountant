"""
src/integrations/gsheets.py
============================
Google Sheets integration for Cozeevo PG — NEW sheet format (v2).

Sheet ID: 1Hp5dTM7TcDEq75jgHEjvwtBjOolruGfQ7CVMzVqjdGw

TENANTS tab (master data) columns (0-indexed):
  [0] Room, [1] Name, [2] Phone, [3] Gender, [4] Building, [5] Floor,
  [6] Sharing, [7] Check-in, [8] Status, [9] Agreed Rent, [10] Deposit,
  [11] Booking, [12] Maintenance, [13] Notice Date, [14] Expected Exit

Monthly tab (e.g. "APRIL 2026") columns (0-indexed):
  [0] Room, [1] Name, [2] Phone, [3] Building, [4] Sharing, [5] Rent Due,
  [6] Cash, [7] UPI, [8] Total Paid, [9] Balance, [10] Status,
  [11] Check-in, [12] Notice Date, [13] Event, [14] Notes, [15] Prev Due

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

MONTHLY_DATA_START_ROW = 5  # 1-based: rows 1-4 are title/summary/headers

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
    logger.info("GSheets: authorized and cached spreadsheet")
    return ss


def _get_worksheet_sync(tab_name: str) -> gspread.Worksheet:
    """Return a worksheet by tab name, cached for 5 min."""
    now = time.time()
    if tab_name in _ws_cache:
        ws, cached_at = _ws_cache[tab_name]
        if (now - cached_at) < _CACHE_TTL:
            return ws

    ss = _get_spreadsheet_sync()
    ws = ss.worksheet(tab_name)
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


# -- Core functions (sync) -----------------------------------------------------

def _update_payment_sync(
    room_number: str,
    tenant_name: str,
    amount: float,
    method: str,
    month: Optional[int] = None,
    year: Optional[int] = None,
) -> dict:
    """
    Update payment in the monthly tab. ADDs amount to Cash or UPI column.
    Returns result dict.
    """
    # Input validation
    if not amount or amount <= 0:
        return {"success": False, "error": "Amount must be positive", "row": None, "tab": None,
                "rent_due": 0, "total_paid": 0, "balance": 0, "overpayment": 0, "warning": None}
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
    note_entry = f"[{ts}] Rs.{int(amount):,} {method_upper}"
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
        ws.batch_update(batch, value_input_option="USER_ENTERED")
        result["success"] = True
        logger.info(
            "GSheets: row %d in %s — Room %s / %s — Rs.%s %s → total %s/%s, balance=%s, status=%s",
            row, tab_name, room_number, tenant_name, int(amount), method_upper,
            int(new_total_paid), int(total_due), int(new_balance), new_status,
        )
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
            checkin,           # 7: Check-in
            "ACTIVE",          # 8: Status
            agreed_rent,       # 9: Agreed Rent
            deposit,           # 10: Deposit
            booking,           # 11: Booking
            maintenance,       # 12: Maintenance
            "",                # 13: Notice Date
            "",                # 14: Expected Exit
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
                checkin, "", "", "", 0,
            ]
        else:
            # Old format: no Phone column (15 cols)
            monthly_row = [
                room_number, name, building, sharing,
                agreed_rent, "", "", 0, agreed_rent, "UNPAID",
                checkin, "", "", 0, 0,
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

    except Exception as e:
        result["error"] = f"Add tenant failed: {e}"
        logger.error("GSheets add_tenant error: %s", e)

    return result


def _record_checkout_sync(
    room_number: str,
    tenant_name: str,
    notice_date: Optional[str] = None,
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
                today_str = datetime.now().strftime("%d/%m/%Y")
                t_batch = [
                    {
                        "range": gspread.utils.rowcol_to_a1(t_row, T_STATUS + 1),
                        "values": [["Exited"]],
                    },
                    {
                        "range": gspread.utils.rowcol_to_a1(t_row, T_CHECKOUT_DATE + 1),
                        "values": [[today_str]],
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

    Returns dict: success, row, tab, rent_due, total_paid, balance, overpayment, warning, error
    """
    return await asyncio.to_thread(
        _update_payment_sync, room_number, tenant_name, amount, method, month, year,
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
) -> dict:
    """
    Async entry point — add tenant to TENANTS tab + current monthly tab.

    Returns dict: success, tenants_row, monthly_row, monthly_tab, error
    """
    return await asyncio.to_thread(
        _add_tenant_sync, room_number, name, phone, gender, building, floor,
        sharing, checkin, agreed_rent, deposit, booking, maintenance,
    )


async def record_checkout(
    room_number: str,
    tenant_name: str,
    notice_date: Optional[str] = None,
) -> dict:
    """
    Async entry point — mark tenant as EXIT in monthly tab + TENANTS tab.

    Returns dict: success, row, tab, error
    """
    return await asyncio.to_thread(
        _record_checkout_sync, room_number, tenant_name, notice_date,
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


# -- Convenience: get sheet for direct access ----------------------------------

async def get_sheet(tab_name: Optional[str] = None) -> gspread.Worksheet:
    """Async wrapper — returns worksheet by tab name (default: current month)."""
    if tab_name is None:
        tab_name = _current_month_tab()
    return await asyncio.to_thread(_get_worksheet_sync, tab_name)
