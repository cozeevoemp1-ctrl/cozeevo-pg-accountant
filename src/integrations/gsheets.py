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

# -- Canonical header lists — derived from src/database/field_registry.py --------
# Every header and the bot→sheet field-name map come from FIELDS, so
# adding a field server-side auto-appears in the PWA, the onboarding form,
# and the Apps Script dashboard without duplicated hardcoded lists.
# All writes use header-based mapping.

from src.database.field_registry import (
    monthly_headers as _monthly_headers,
    tenants_headers as _tenants_headers,
    tenants_field_to_header as _tenants_field_to_header,
    field_to_col as _field_to_col,
)
from src.services.rent_status import compute_status as _compute_status

MONTHLY_HEADERS = _monthly_headers()
TENANTS_HEADERS = _tenants_headers()


def _header_index(headers: list[str], name: str) -> int:
    """Find column index by header name (case-insensitive). Returns -1 if missing."""
    name_l = name.strip().lower()
    for i, h in enumerate(headers):
        if h.strip().lower() == name_l:
            return i
    return -1


def _build_header_map(headers: list[str]) -> dict[str, int]:
    """Build {lowercase_header: index} map from a header row."""
    return {h.strip().lower(): i for i, h in enumerate(headers) if h.strip()}


# -- Derived index constants (auto-generated from canonical header lists) -------
# Used for reads / old-format compat. All writes go through header-based mapping.

def _derive_constants(headers, prefix):
    """Generate index constants from header list. Returns dict of NAME: index."""
    mapping = {}
    for i, h in enumerate(headers):
        key = prefix + h.upper().replace(" ", "_").replace("-", "_")
        mapping[key] = i
    return mapping

_M = _derive_constants(MONTHLY_HEADERS, "M_")
_T = _derive_constants(TENANTS_HEADERS, "T_")

# Monthly tab column indices (derived from MONTHLY_HEADERS)
M_ROOM = _M["M_ROOM"]
M_NAME = _M["M_NAME"]
M_PHONE = _M["M_PHONE"]
M_BUILDING = _M["M_BUILDING"]
M_SHARING = _M["M_SHARING"]
M_RENT = _M["M_RENT"]
M_DEPOSIT = _M["M_DEPOSIT"]
M_RENT_DUE = _M["M_RENT_DUE"]
M_CASH = _M["M_CASH"]
M_UPI = _M["M_UPI"]
M_TOTAL_PAID = _M["M_TOTAL_PAID"]
M_BALANCE = _M["M_BALANCE"]
M_STATUS = _M["M_STATUS"]
M_CHECKIN = _M["M_CHECK_IN"]
M_NOTICE_DATE = _M["M_NOTICE_DATE"]
M_EVENT = _M["M_EVENT"]
M_NOTES = _M["M_NOTES"]
M_PREV_DUE = _M["M_PREV_DUE"]
M_ENTERED_BY = _M["M_ENTERED_BY"]

# TENANTS tab column indices (derived from TENANTS_HEADERS)
T_ROOM = _T["T_ROOM"]
T_NAME = _T["T_NAME"]
T_PHONE = _T["T_PHONE"]
T_GENDER = _T["T_GENDER"]
T_BUILDING = _T["T_BUILDING"]
T_FLOOR = _T["T_FLOOR"]
T_SHARING = _T["T_SHARING"]
T_CHECKIN = _T["T_CHECK_IN"]
T_STATUS = _T["T_STATUS"]
T_AGREED_RENT = _T["T_AGREED_RENT"]
T_DEPOSIT = _T["T_DEPOSIT"]
T_BOOKING = _T["T_BOOKING"]
T_MAINTENANCE = _T["T_MAINTENANCE"]
T_NOTICE_DATE = _T["T_NOTICE_DATE"]
T_EXPECTED_EXIT = _T["T_EXPECTED_EXIT"]
T_CHECKOUT_DATE = _T["T_CHECKOUT_DATE"]
T_REFUND_STATUS = _T["T_REFUND_STATUS"]
T_REFUND_AMOUNT = _T["T_REFUND_AMOUNT"]
T_DOB = _T["T_DOB"]
T_FATHER_NAME = _T["T_FATHER_NAME"]
T_FATHER_PHONE = _T["T_FATHER_PHONE"]
T_ADDRESS = _T["T_ADDRESS"]
T_EMERGENCY_CONTACT = _T["T_EMERGENCY_CONTACT"]
T_EMERGENCY_RELATIONSHIP = _T["T_EMERGENCY_RELATIONSHIP"]
T_EMAIL = _T["T_EMAIL"]
T_OCCUPATION = _T["T_OCCUPATION"]
T_EDUCATION = _T["T_EDUCATION"]
T_OFFICE_ADDRESS = _T["T_OFFICE_ADDRESS"]
T_OFFICE_PHONE = _T["T_OFFICE_PHONE"]
T_ID_TYPE = _T["T_ID_TYPE"]
T_ID_NUMBER = _T["T_ID_NUMBER"]
T_FOOD_PREF = _T["T_FOOD_PREF"]
T_NOTES = _T["T_NOTES"]
T_EVENT = _T["T_EVENT"]

MONTHLY_DATA_START_ROW = 5  # 1-based: rows 1-4 are title/summary/headers (legacy default)
TOTAL_BEDS = 294  # updated 2026-04-26; 295 when G20 returns to revenue May 2026


def _locate_monthly_header(all_vals: list[list]) -> tuple[int, int]:
    """
    Find the column-header row of a monthly tab by scanning column A for "Room".

    Works for both layouts:
      - Legacy: header at row 4 (index 3), data from row 5 (index 4)
      - New (sync_sheet_from_db.py): header at row 7 (index 6), data from row 8 (index 7)

    Returns (header_idx_0based, data_start_idx_0based). Returns (-1, -1) if
    no "Room" header found in the first 12 rows.

    Use everywhere we need to read or write data rows of a monthly tab —
    never assume a fixed offset.
    """
    for idx in range(0, min(12, len(all_vals))):
        cell = all_vals[idx][0] if all_vals[idx] else ""
        if str(cell or "").strip().lower() == "room":
            return idx, idx + 1
    return -1, -1

# -- Failed Sheet writes retry queue -------------------------------------------
import json as _json
_FAILED_WRITES_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "sheet_write_queue.json",
)
_failed_writes_lock = asyncio.Lock() if asyncio else None  # type: ignore

def _queue_failed_write(operation: str, kwargs: dict) -> None:
    """Queue a failed Sheet write for retry. Fire-and-forget, never raises."""
    try:
        os.makedirs(os.path.dirname(_FAILED_WRITES_PATH), exist_ok=True)
        queue = []
        if os.path.exists(_FAILED_WRITES_PATH):
            with open(_FAILED_WRITES_PATH, "r") as f:
                queue = _json.load(f)
        queue.append({"op": operation, "kwargs": kwargs, "ts": time.time()})
        # Cap at 200 entries to prevent unbounded growth
        if len(queue) > 200:
            queue = queue[-200:]
        with open(_FAILED_WRITES_PATH, "w") as f:
            _json.dump(queue, f)
        logger.warning("Queued failed Sheet write: %s (%d in queue)", operation, len(queue))
    except Exception as e:
        logger.error("Could not queue failed Sheet write: %s", e)


async def retry_failed_writes() -> dict:
    """Retry all queued Sheet writes. Call on bot startup or periodically.
    Returns {"retried": N, "failed": N, "remaining": N}."""
    if not os.path.exists(_FAILED_WRITES_PATH):
        return {"retried": 0, "failed": 0, "remaining": 0}
    try:
        with open(_FAILED_WRITES_PATH, "r") as f:
            queue = _json.load(f)
    except Exception:
        return {"retried": 0, "failed": 0, "remaining": 0}

    if not queue:
        return {"retried": 0, "failed": 0, "remaining": 0}

    logger.info("Retrying %d failed Sheet writes...", len(queue))
    still_failed = []
    retried = 0

    # Map operation names to functions
    op_map = {
        "add_tenant": add_tenant,
        "record_checkout": record_checkout,
        "update_tenant_field": update_tenant_field,
        "update_payment": update_payment,
        "record_notice": record_notice,
    }

    for item in queue:
        op = item.get("op", "")
        kwargs = item.get("kwargs", {})
        fn = op_map.get(op)
        if not fn:
            logger.warning("Unknown queued op: %s", op)
            continue
        try:
            result = await fn(**kwargs)
            if result and result.get("success"):
                retried += 1
            else:
                still_failed.append(item)
        except Exception as e:
            logger.warning("Retry failed for %s: %s", op, e)
            still_failed.append(item)

    # Save remaining failures
    if still_failed:
        with open(_FAILED_WRITES_PATH, "w") as f:
            _json.dump(still_failed, f)
    elif os.path.exists(_FAILED_WRITES_PATH):
        os.remove(_FAILED_WRITES_PATH)

    return {"retried": retried, "failed": len(still_failed), "remaining": len(still_failed)}

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


# Frozen period: Dec 2025–Mar 2026 are loaded 1:1 from Cozeevo source sheets
# and MUST NOT be mutated by the bot or sync scripts. Convention → code guard.
FROZEN_MONTHS: frozenset[tuple[int, int]] = frozenset({
    (2025, 12), (2026, 1), (2026, 2), (2026, 3),
})


def _is_frozen_month(month: int, year: int) -> bool:
    return (year, month) in FROZEN_MONTHS


def _is_frozen_tab(tab_name: str) -> bool:
    """True if tab_name like 'MARCH 2026' falls in the frozen range."""
    if not tab_name:
        return False
    parts = tab_name.strip().upper().split()
    if len(parts) != 2 or parts[0] not in MONTH_NAMES:
        return False
    try:
        m = MONTH_NAMES.index(parts[0]) + 1
        y = int(parts[1])
    except (ValueError, IndexError):
        return False
    return _is_frozen_month(m, y)


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
            # Detect format via header row + look up columns by name
            all_vals = ws.get_all_values()
            hdr_idx, _ = _locate_monthly_header(all_vals)
            hdr = all_vals[hdr_idx] if hdr_idx >= 0 else []
            hmap = _build_header_map(hdr)
            bal_col = hmap.get("balance", 9)
            notes_col = hmap.get("notes", 14)
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

        # Detect column layout AND header row position. The new layout has 5
        # summary rows (R2-R6), header at R7, data from R8. The legacy layout
        # had 2 summary rows (R2-R3), header at R4, data from R5.
        # Locate the column-header row by finding "Room" in column A.
        header_row_idx = None
        for idx in range(0, min(10, len(all_vals))):
            if str(all_vals[idx][0] if all_vals[idx] else "").strip().lower() == "room":
                header_row_idx = idx
                break
        if header_row_idx is None:
            # Tab not initialised by sync_sheet_from_db — skip refresh
            logger.warning("GSheets refresh: no 'Room' header found in %s — skipping", tab_name)
            return
        data_start_idx = header_row_idx + 1  # 0-indexed list index where data rows begin

        hdr = all_vals[header_row_idx]
        is_new = "phone" in str(hdr[2] if len(hdr) > 2 else "").lower()
        if is_new:
            ci = {"rent": M_RENT_DUE,
                  "cash": M_CASH, "upi": M_UPI, "tp": M_TOTAL_PAID, "bal": M_BALANCE, "st": M_STATUS,
                  "building": M_BUILDING, "sharing": M_SHARING, "event": M_EVENT, "prev": M_PREV_DUE}
        else:
            ci = {"rent": 4,
                  "cash": 5, "upi": 6, "tp": 7, "bal": 8, "st": 9,
                  "building": 2, "sharing": 3, "event": 11, "prev": 15}

        # ── Per-row recalculation (only true data rows, never header/summary) ──
        row_updates = []  # list of batch update dicts
        for i in range(data_start_idx, len(all_vals)):
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
            st = _compute_status(tp, rent)

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

        for i in range(data_start_idx, len(all_vals)):
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

            if status == "EXIT" or "EXIT" in event:
                continue
            # event is "NO SHOW" (space) in the data; older code looked for "NO-SHOW" (dash)
            if "NO SHOW" in event or "NO-SHOW" in event or "NO SHOW" in status or "NO-SHOW" in status:
                noshow += 1
                continue

            bed_count = 2 if sharing == "premium" else 1
            beds += bed_count
            if sharing == "premium":
                premium += 1
            else:
                regular += 1

            # building cell is "Cozeevo THOR" / "Cozeevo HULK" — substring match
            if "THOR" in building:
                thor_beds += bed_count
                thor_tenants += 1
            elif "HULK" in building:
                hulk_beds += bed_count
                hulk_tenants += 1
            else:
                # Unknown building — count somewhere so the totals don't drop
                hulk_beds += bed_count
                hulk_tenants += 1

        collected = cash_total + upi_total
        vacant = TOTAL_BEDS - beds - noshow
        occ_pct = f"{beds / TOTAL_BEDS * 100:.1f}" if TOTAL_BEDS > 0 else "0"
        pending = max(0, int(balance_total))

        def _lk(n):
            v = int(round(float(n or 0)))
            s = str(abs(v))
            if len(s) > 3:
                last3, rest = s[-3:], s[:-3]
                groups = []
                while len(rest) > 2:
                    groups.insert(0, rest[-2:])
                    rest = rest[:-2]
                if rest:
                    groups.insert(0, rest)
                s = ",".join(groups) + "," + last3
            return f"-{s}" if v < 0 else s

        # New layout uses canonical MONTHLY_HEADERS (header-driven, no hardcoding).
        # Old layout was a fixed 15-column legacy format.
        if is_new:
            num_cols = len(MONTHLY_HEADERS)
            last_col = gspread.utils.rowcol_to_a1(1, num_cols).rstrip("0123456789")
        else:
            num_cols = 15
            last_col = "O"

        # 5-row labeled summary (matches sync_sheet_from_db.py layout).
        # Each cell is independent so users can click/copy values.
        r2_occ = ["OCCUPANCY", f"Active: {regular + premium}",
                  f"Beds: {beds} ({regular}+{premium}P)",
                  f"No-show: {noshow}", f"Vacant: {vacant}/{TOTAL_BEDS}",
                  f"Occupancy: {occ_pct}%"]
        r3_bld = ["BUILDINGS", f"THOR: {thor_beds} beds ({thor_tenants}t)",
                  f"HULK: {hulk_beds} beds ({hulk_tenants}t)",
                  f"Exits: {exits}"]
        r4_col = ["COLLECTION", f"Cash: {_lk(cash_total)}",
                  f"UPI: {_lk(upi_total)}", f"Collected: {_lk(collected)}",
                  f"Pending: {_lk(pending)}"]
        r5_sts = ["STATUS", f"PAID: {paid}", f"PARTIAL: {partial}",
                  f"UNPAID: {unpaid}", f"New: {new_checkins}"]
        r6_notice = ["NOTICE", "On notice: see full sync",
                     "Vacating next month: see full sync"]

        def _pad(row):
            return (row + [""] * num_cols)[:num_cols]

        summary_rows = [_pad(r2_occ), _pad(r3_bld), _pad(r4_col), _pad(r5_sts), _pad(r6_notice)]
        ws.update(values=summary_rows, range_name=f"A2:{last_col}6",
                  value_input_option="USER_ENTERED")

        logger.info(
            "GSheets: refreshed summary for %s — %d beds, %d paid, %d partial, %d unpaid, collected=%d",
            tab_name, beds, paid, partial, unpaid, int(collected),
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
    is_daily: bool = False,
) -> dict:
    """
    Update payment in the monthly tab (or DAY WISE tab for daily stays).
    ADDs amount to Cash or UPI column. Returns result dict.
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

    if is_daily:
        tab_name = "DAY WISE"
    else:
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

    if not is_daily and _is_frozen_month(month, year):
        result["error"] = f"Refused write to frozen tab '{tab_name}' (Dec 2025–Mar 2026 is read-only)"
        logger.warning("GSheets update_payment: blocked frozen-month write to %s", tab_name)
        return result

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

    # Locate header row dynamically (legacy: row 4, new: row 7)
    header_idx, data_start = _locate_monthly_header(all_vals)
    if data_start < 0:
        result["error"] = f"No 'Room' header found in {tab_name}"
        return result
    header_row = all_vals[header_idx]

    # Find row
    room_clean = room_number.strip().upper()
    name_lower = tenant_name.strip().lower()
    found = None
    for i in range(data_start, len(all_vals)):
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

    # Old vs new column layout (header_row already located above)
    is_new = "phone" in str(header_row[2] if len(header_row) > 2 else "").lower()

    if is_new:
        col_cash, col_upi, col_rent, col_prev, col_tp, col_bal, col_st, col_notes = (
            M_CASH, M_UPI, M_RENT_DUE, M_PREV_DUE, M_TOTAL_PAID, M_BALANCE, M_STATUS, M_NOTES)
    else:
        # Old format: no Phone column, no deposit/maint columns
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

    new_status = _compute_status(new_total_paid, rent_due)

    # Kiran 2026-04-23: stop appending payment timestamps to Notes.
    # Payment history lives in DB payments table + Cash/UPI columns.
    # Notes column is reserved for tenant business notes (lockin, special rent, etc.).
    # Batch update: target payment col, Total Paid, Balance, Status
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
            row, tab_name, room_number, tenant_name, int(amount), method.upper(),
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
    emergency_contact_phone: str = "",
    emergency_relationship: str = "",
    email: str = "",
    occupation: str = "",
    education: str = "",
    office_address: str = "",
    office_phone: str = "",
    id_type: str = "",
    id_number: str = "",
    food_pref: str = "",
    entered_by: str = "",
    advance_amount: float = 0,
    advance_mode: str = "",
    tenants_only: bool = False,
) -> dict:
    """
    Add tenant to TENANTS master tab AND current monthly tab.
    Pass tenants_only=True to skip the monthly tab write (e.g. day-wise guests).
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
        # -- TENANTS tab (header-based mapping) --
        tenants_ws = _get_worksheet_sync("TENANTS")
        t_data = tenants_ws.get_all_values()
        t_headers = [h.strip().lower() for h in t_data[0]] if t_data else []

        # Map header names to values — keys are lowercase header names
        # Apostrophe prefix forces Sheet to treat as text (preserves + prefix, leading zeros)
        phone_txt = f"'{phone}" if phone else ""
        father_phone_txt = f"'{father_phone}" if father_phone else ""
        office_phone_txt = f"'{office_phone}" if office_phone else ""
        emergency_contact_txt = f"'{emergency_contact}" if emergency_contact else ""
        emergency_contact_phone_txt = f"'{emergency_contact_phone}" if emergency_contact_phone else ""
        id_number_txt = f"'{id_number}" if id_number else ""
        field_map = {
            "room": room_number,
            "name": name,
            "phone": phone_txt,
            "gender": gender,
            "building": building,
            "floor": floor,
            "sharing": sharing,
            "check-in": checkin_display,
            "status": status,
            "agreed rent": agreed_rent,
            "deposit": deposit,
            "booking": booking,
            "maintenance": maintenance,
            "notes": notes,
            "food": food_pref,
            "dob": dob,
            "father name": father_name,
            "father phone": father_phone_txt,
            "address": address,
            "email": email,
            "occupation": occupation,
            "education": education,
            "emergency contact": emergency_contact_txt,
            "emergency relationship": emergency_relationship,
            "emergency phone": emergency_contact_phone_txt,
            "id type": id_type,
            "id number": id_number_txt,
            "office address": office_address,
            "office phone": office_phone_txt,
            "event": "CHECKIN",
            "entered by": entered_by,
        }
        # Also match alternate header names
        alt_names = {
            "emergency relationship": emergency_relationship,
            "emergency rel": emergency_relationship,
            "food preference": food_pref,
            "food pref": food_pref,
            "date of birth": dob,
            "checkin": checkin_display,
            "check in": checkin_display,
            "rent": agreed_rent,
            "agreed_rent": agreed_rent,
            "office_phone": office_phone,
            "office_address": office_address,
            "father_name": father_name,
            "father_phone": father_phone,
            "id_type": id_type,
            "id_number": id_number,
        }
        field_map.update(alt_names)

        # Build row by matching headers
        tenants_row = [""] * len(t_headers)
        for i, header in enumerate(t_headers):
            if header in field_map:
                tenants_row[i] = field_map[header]

        t_next = len(t_data) + 1
        tenants_ws.update(values=[tenants_row], range_name=f"A{t_next}", value_input_option="USER_ENTERED")
        result["tenants_row"] = t_next
        logger.info("GSheets: added tenant %s to TENANTS tab at row %d", name, result["tenants_row"])

        if tenants_only:
            result["success"] = True
            return result

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

        # Header-based mapping for monthly tab (same approach as TENANTS).
        # Locate the column-header row by finding "Room" in column A —
        # works for both old layout (row 4) and new sync_sheet_from_db
        # layout (row 7) without hardcoding.
        all_vals = monthly_ws.get_all_values()
        header_row_idx = None
        for _idx in range(0, min(10, len(all_vals))):
            if str(all_vals[_idx][0] if all_vals[_idx] else "").strip().lower() == "room":
                header_row_idx = _idx
                break
        header_row = all_vals[header_row_idx] if header_row_idx is not None else []
        m_headers = [h.strip().lower() for h in header_row]

        # Advance payment: put in Cash or UPI column based on mode
        adv_cash = advance_amount if advance_mode == "cash" and advance_amount > 0 else ""
        adv_upi = advance_amount if advance_mode == "upi" and advance_amount > 0 else ""
        adv_total = advance_amount if advance_amount > 0 else 0
        # First month: Rent Due = rent, Deposit Due = deposit (separate column)
        first_month_total = agreed_rent + deposit
        adv_balance = first_month_total - advance_amount
        # First-month status: rent+deposit bundle. Balance <= 0 means advance
        # covered the full bundle. Delegated to canonical helper.
        adv_status = _compute_status(float(advance_amount or 0), float(first_month_total or 0))

        m_field_map = {
            "room": room_number,
            "name": name,
            "phone": phone_txt,
            "building": building,
            "sharing": sharing,
            "rent": int(agreed_rent) if agreed_rent else "",
            "deposit": int(deposit) if deposit else "",
            "rent due": first_month_total,
            "cash": adv_cash,
            "upi": adv_upi,
            "total paid": adv_total,
            "balance": adv_balance,
            "status": adv_status,
            "check-in": checkin_display,
            "checkin": checkin_display,
            "check in": checkin_display,
            "notice date": "",
            "event": "CHECKIN",
            "notes": (notes + " | " if notes else "") + (f"First month: rent {int(agreed_rent):,} + deposit {int(deposit):,}" if deposit > 0 else ""),
            "prev due": 0,
            "entered by": entered_by,
        }

        monthly_row = [""] * len(m_headers)
        for i, header in enumerate(m_headers):
            if header in m_field_map:
                monthly_row[i] = m_field_map[header]

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
    is_daily: bool = False,
) -> dict:
    """
    Async entry point — update payment in Google Sheet monthly tab (or DAY WISE for daily stays).

    Args:
        room_number: e.g. "102"
        tenant_name: tenant name for row lookup
        amount: payment amount
        method: "cash" or "upi"
        month: month number (1-12). None = current month
        year: year. None = current year
        entered_by: name of person who logged this payment (for audit trail)
        is_daily: True for Tenancy(stay_type=daily) — writes to DAY WISE tab

    Returns dict: success, row, tab, rent_due, total_paid, balance, overpayment, warning, error
    """
    return await asyncio.to_thread(
        _update_payment_sync, room_number, tenant_name, amount, method, month, year, entered_by, is_daily,
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
    if _is_frozen_month(month, year):
        result["error"] = f"Refused write to frozen tab '{tab_name}' (Dec 2025–Mar 2026 is read-only)"
        logger.warning("GSheets void: blocked frozen-month write to %s", tab_name)
        return result
    try:
        ws = _get_worksheet_sync(tab_name)
    except gspread.WorksheetNotFound:
        result["error"] = f"Tab '{tab_name}' not found"
        return result
    except Exception as e:
        result["error"] = f"Sheet access failed: {e}"
        return result

    all_vals = ws.get_all_values()
    header_idx, data_start = _locate_monthly_header(all_vals)
    if data_start < 0:
        result["error"] = f"No 'Room' header found in {tab_name}"
        return result

    room_clean = room_number.strip().upper()
    name_lower = tenant_name.strip().lower()
    found = None
    for i in range(data_start, len(all_vals)):
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

    header_row = all_vals[header_idx]
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

    new_status = _compute_status(new_total_paid, rent_due)

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


# ── Day-wise stay Sheet writer ────────────────────────────────────────────────

def _build_daywise_row(
    room_number: str, tenant_name: str, phone: str, building: str,
    sharing: str, daily_rate: float, num_days: int, booking_amount: float,
    total_paid: float, maintenance: float, checkin: str, checkout: str,
    status: str, notes: str, entered_by: str,
) -> list:
    """Build a MONTHLY_HEADERS-aligned row for a daily-stay tenant."""
    rent_due = round(daily_rate * num_days + maintenance, 2)
    balance = round(rent_due - total_paid, 2)
    # MONTHLY_HEADERS order:
    # Room|Name|Phone|Building|Sharing|Rent|Deposit|Rent Due|Cash|UPI|Total Paid|Balance|Status|Check-in|Notice Date|Event|Notes|Prev Due|Entered By
    return [
        room_number,                            # Room
        tenant_name,                            # Name
        f"'{phone}" if phone else "",           # Phone (prefix ' so Sheets treats as text)
        building,                               # Building
        sharing,                                # Sharing
        daily_rate,                             # Rent (= daily rate)
        booking_amount,                         # Deposit (= advance/booking)
        rent_due,                               # Rent Due
        total_paid,                             # Cash (total shown as cash; mode tracked in Payment)
        0,                                      # UPI
        total_paid,                             # Total Paid
        balance,                                # Balance
        status,                                 # Status
        checkin,                                # Check-in
        "",                                     # Notice Date
        f"checkout: {checkout}" if checkout else "",  # Event
        notes,                                  # Notes
        "",                                     # Prev Due
        entered_by,                             # Entered By
    ]


def _add_daywise_stay_sync(
    room_number: str, tenant_name: str = "", phone: str = "", building: str = "",
    sharing: str = "", daily_rate: float = 0, num_days: int = 0,
    booking_amount: float = 0, total_paid: float = 0, maintenance: float = 0,
    checkin: str = "", checkout: str = "", status: str = "ACTIVE",
    notes: str = "", entered_by: str = "",
    **_kwargs,   # swallow legacy keyword args gracefully
) -> dict:
    """Append a day-wise stay row to DAY WISE tab using MONTHLY_HEADERS format."""
    result = {"success": False, "row": None, "error": None}
    try:
        ws = _get_worksheet_sync("DAY WISE")
        all_vals = ws.get_all_values()

        # Ensure header row exists at row 1
        if not all_vals or [h.strip() for h in all_vals[0]] != MONTHLY_HEADERS:
            ws.update(values=[MONTHLY_HEADERS], range_name="A1",
                      value_input_option="USER_ENTERED")
            all_vals = ws.get_all_values()

        row = _build_daywise_row(
            room_number=room_number, tenant_name=tenant_name, phone=phone,
            building=building, sharing=sharing, daily_rate=daily_rate,
            num_days=num_days, booking_amount=booking_amount, total_paid=total_paid,
            maintenance=maintenance, checkin=checkin, checkout=checkout,
            status=status, notes=notes, entered_by=entered_by,
        )
        next_row = len(all_vals) + 1
        ws.update(values=[row], range_name=f"A{next_row}", value_input_option="USER_ENTERED")
        result["success"] = True
        result["row"] = next_row
    except Exception as e:
        result["error"] = str(e)
    return result


async def add_daywise_stay(**kwargs) -> dict:
    """Async wrapper for _add_daywise_stay_sync."""
    import asyncio
    return await asyncio.to_thread(_add_daywise_stay_sync, **kwargs)


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
    emergency_contact_phone: str = "",
    emergency_relationship: str = "",
    email: str = "",
    occupation: str = "",
    education: str = "",
    office_address: str = "",
    office_phone: str = "",
    id_type: str = "",
    id_number: str = "",
    food_pref: str = "",
    entered_by: str = "",
    advance_amount: float = 0,
    advance_mode: str = "",
    tenants_only: bool = False,
) -> dict:
    """
    Async entry point — add tenant to TENANTS tab + current monthly tab.
    Pass tenants_only=True to write only to TENANTS master tab (e.g. day-wise guests).

    Returns dict: success, tenants_row, monthly_row, monthly_tab, error
    """
    return await asyncio.to_thread(
        _add_tenant_sync, room_number, name, phone, gender, building, floor,
        sharing, checkin, agreed_rent, deposit, booking, maintenance, notes,
        dob, father_name, father_phone, address, emergency_contact,
        emergency_contact_phone, emergency_relationship, email, occupation,
        education, office_address, office_phone, id_type, id_number, food_pref,
        entered_by, advance_amount, advance_mode, tenants_only,
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
                header_idx, data_start = _locate_monthly_header(all_vals)
                if data_start < 0:
                    continue
                header_row = all_vals[header_idx]
                is_new = "phone" in str(header_row[2] if len(header_row) > 2 else "").lower()
                col_checkin = M_CHECKIN if is_new else 10  # old format

                updated_here = False
                for j in range(data_start, len(all_vals)):
                    r = all_vals[j]
                    if not r or not r[0] or len(r) < 2:
                        continue
                    if (str(r[0]).strip().upper() == room_clean and
                            name_lower in str(r[1]).strip().lower()):
                        cell = gspread.utils.rowcol_to_a1(j + 1, col_checkin + 1)
                        ws.update(values=[[checkin_display]], range_name=cell, value_input_option="USER_ENTERED")
                        logger.info("GSheets: updated checkin in '%s' row %d", tab, j + 1)
                        updated_here = True
                        break
                if updated_here:
                    try:
                        _refresh_summary_sync(tab)
                    except Exception as _re:
                        logger.warning("GSheets: summary refresh after checkin change on %s failed: %s", tab, _re)
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
        header_idx, data_start = _locate_monthly_header(all_vals)
        if data_start < 0:
            result["error"] = f"No 'Room' header found in {tab_name}"
            return result
        header_row = all_vals[header_idx]
        is_new = "phone" in str(header_row[2] if len(header_row) > 2 else "").lower()
        col_notes = M_NOTES if is_new else 12

        room_clean = room_number.strip().upper()
        name_lower = tenant_name.strip().lower()

        for i in range(data_start, len(all_vals)):
            r = all_vals[i]
            if not r or not r[0] or len(r) < 2:
                continue
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


# ── Field-to-column map for monthly tab (uses M_* constants from top of file) ──

# Derived from field registry — any field with a monthly_header becomes
# addressable here. Previously hardcoded; see src/database/field_registry.py.
_FIELD_TO_COL = _field_to_col()


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

        # Locate header row dynamically — works on legacy AND new layouts.
        _hdr_idx, data_start = _locate_monthly_header(all_vals)
        if data_start < 0:
            result["error"] = f"No 'Room' header found in {tab_name}"
            return result

        # Find the row by room+name, fall back to name-only
        target_row = None
        for i in range(data_start, len(all_vals)):
            row = all_vals[i]
            if not row or not row[0] or len(row) < 2 or not row[1]:
                continue
            row_room = str(row[0]).strip()
            row_name = str(row[1]).strip().lower()
            if row_room == str(room_number) and tenant_name.lower() in row_name:
                target_row = i + 1  # 1-based for gspread
                break

        if not target_row:
            for i in range(data_start, len(all_vals)):
                row = all_vals[i]
                if not row or len(row) < 2 or not row[1]:
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

        # Dashboard banner (Active / Beds / Vacant / Occupancy / per-row
        # Balance / Status) must reflect this write — API cell writes don't
        # fire the Apps Script onEdit trigger, so refresh it from here.
        try:
            _refresh_summary_sync(tab_name)
        except Exception as _re:
            logger.warning(f"[GSheets] Summary refresh after {field} on {tab_name} failed: {_re}")

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


# ── Generic TENANTS-master-tab field update ───────────────────────────────────
# Maps short field names used by handlers to TENANTS_HEADERS column names.
# Derived from field registry — adding a Field with a tenants_header auto
# exposes it here (plus any declared aliases).
# Lookup is case-insensitive — keys must be lowercase.
_TENANTS_FIELD_TO_HEADER = _tenants_field_to_header()


def _update_tenants_tab_field_sync(
    room_number: str,
    tenant_name: str,
    field: str,
    new_value: Any,
) -> dict:
    """
    Update one column for a tenant row in the TENANTS master tab.
    Field names are looked up via _TENANTS_FIELD_TO_HEADER → TENANTS_HEADERS.
    Locates the row by room_number + tenant_name (substring, case-insensitive).
    """
    result: dict[str, Any] = {"success": False, "error": None}
    header_name = _TENANTS_FIELD_TO_HEADER.get(field.strip().lower())
    if not header_name:
        result["error"] = f"Unknown TENANTS field '{field}'"
        return result

    try:
        ws = _get_worksheet_sync("TENANTS")
        all_vals = ws.get_all_values()
        if not all_vals:
            result["error"] = "TENANTS tab is empty"
            return result

        headers = [h.strip().lower() for h in all_vals[0]]
        try:
            col_idx = headers.index(header_name.lower())
        except ValueError:
            result["error"] = f"Header '{header_name}' not found in TENANTS tab"
            return result

        room_clean = str(room_number).strip().upper()
        name_lower = str(tenant_name).strip().lower()
        target_row = None
        for i in range(1, len(all_vals)):
            r = all_vals[i]
            if not r or len(r) < 2:
                continue
            row_room = str(r[T_ROOM]).strip().upper() if T_ROOM < len(r) else ""
            row_name = str(r[T_NAME]).strip().lower() if T_NAME < len(r) else ""
            if row_room == room_clean and name_lower in row_name:
                target_row = i + 1  # gspread is 1-based
                break
        # Fallback — match by name only if room+name didn't hit
        if target_row is None:
            for i in range(1, len(all_vals)):
                r = all_vals[i]
                if not r or len(r) < 2:
                    continue
                row_name = str(r[T_NAME]).strip().lower() if T_NAME < len(r) else ""
                if name_lower and name_lower == row_name:
                    target_row = i + 1
                    break

        if target_row is None:
            result["error"] = f"Tenant '{tenant_name}' not found in TENANTS tab"
            return result

        cell = gspread.utils.rowcol_to_a1(target_row, col_idx + 1)
        ws.update(values=[[new_value]], range_name=cell, value_input_option="USER_ENTERED")
        result["success"] = True
        logger.info("GSheets: TENANTS tab — %s row %d, %s = %s",
                    tenant_name, target_row, header_name, new_value)
    except Exception as e:
        result["error"] = f"TENANTS field update failed: {e}"
        logger.warning("GSheets: TENANTS update failed for %s.%s: %s", tenant_name, field, e)
    return result


async def update_tenants_tab_field(
    room_number: str,
    tenant_name: str,
    field: str,
    new_value: Any,
) -> dict:
    """Async entry point — update one column on the TENANTS master tab."""
    return await asyncio.to_thread(
        _update_tenants_tab_field_sync, room_number, tenant_name, field, new_value
    )


# ── SYSTEMIC: push every DB field of a tenant to both sheet tabs ──────────────
# The rule (per Kiran, 2026-04-19): whenever ANY attribute of a tenant or
# tenancy changes in DB, every sheet column that shows that attribute must
# auto-update so the receptionist never sees stale data. This helper does
# that wholesale — pass it a tenant_id, it reads the current DB state and
# writes every tenant+tenancy+room column to both TENANTS and the current
# monthly tab in ONE batch per sheet. Call after any mutation.


def _sync_tenant_all_fields_sync(tenant_id: int, skip_fields: list | None = None) -> dict:
    """
    Push every DB field of a tenant (and their active tenancy) to
    TENANTS master tab + current monthly tab.

    Single batch update per sheet — fast (~1.5s for both tabs).
    Safe to call from fire-and-forget background tasks; never raises.
    """
    import os as _os
    from datetime import date as _date
    result: dict[str, Any] = {"success": False, "tenants_written": 0, "monthly_written": 0, "error": None}

    # Work on our own DB session so we're safe in background tasks.
    try:
        from sqlalchemy import create_engine as _ce, select as _sel
        from sqlalchemy.orm import sessionmaker as _sm
        from src.database.models import (
            Tenant as _Tenant, Tenancy as _Tenancy, Room as _Room,
            Property as _Property, TenancyStatus as _TS,
            Refund as _Refund,
        )
        db_url = _os.environ.get("DATABASE_URL", "")
        if db_url.startswith("postgresql+asyncpg://"):
            db_url = db_url.replace("postgresql+asyncpg://", "postgresql://", 1)
        if not db_url:
            result["error"] = "DATABASE_URL not set"
            return result
        engine = _ce(db_url, pool_pre_ping=True)
        Session = _sm(engine, expire_on_commit=False)
        with Session() as s:
            tenant = s.get(_Tenant, tenant_id)
            if not tenant:
                result["error"] = f"Tenant {tenant_id} not found"
                return result
            tenancy = s.scalar(_sel(_Tenancy).where(
                _Tenancy.tenant_id == tenant_id,
                _Tenancy.status.in_([_TS.active, _TS.no_show]),
            ).order_by(_Tenancy.created_at.desc()))
            room = s.get(_Room, tenancy.room_id) if tenancy and tenancy.room_id else None
            prop = s.get(_Property, room.property_id) if room and room.property_id else None
            # Latest refund for this tenancy — drives TENANTS.Refund Status / Amount.
            latest_refund = None
            if tenancy:
                latest_refund = s.scalar(
                    _sel(_Refund)
                    .where(_Refund.tenancy_id == tenancy.id)
                    .order_by(_Refund.created_at.desc())
                )

        engine.dispose()
    except Exception as e:
        result["error"] = f"DB read failed: {e}"
        return result

    if not tenancy or not room:
        result["error"] = f"No active/no-show tenancy for tenant {tenant_id}"
        return result

    skip = set(f.strip().lower() for f in (skip_fields or []))

    def _date_str(d):
        if d is None:
            return ""
        if isinstance(d, _date):
            return d.strftime("%d/%m/%Y")
        return str(d)

    def _enum_str(v):
        return v.value if hasattr(v, "value") else (v or "")

    def _phone_str(p):
        # Normalise to +91XXXXXXXXXX (10-digit Indian phone with prefix).
        import re as _re
        if not p:
            return ""
        digits = _re.sub(r"[^0-9]", "", str(p))
        if len(digits) > 10:
            digits = digits[-10:]
        return f"+91{digits}" if len(digits) == 10 else (p or "")

    def _building_short(name):
        # Strip "Cozeevo " prefix so TENANTS shows "HULK" / "THOR" consistently.
        if not name:
            return ""
        return name.replace("Cozeevo ", "").strip()

    def _tc(s):
        # Title-case free-text categoricals (Male/Female, Double/Single/Premium, Active/No-show).
        return str(s or "").strip().title()

    # ── Build TENANTS tab row values keyed by header name ─────────────────
    refund_status_val = ""
    refund_amount_val: int | str = ""
    if latest_refund is not None:
        refund_status_val = _enum_str(latest_refund.status) or ""
        refund_amount_val = int(latest_refund.amount or 0)

    tenants_row = {
        "room": room.room_number,
        "name": tenant.name or "",
        "phone": _phone_str(tenant.phone),
        "gender": _tc(tenant.gender),
        "building": _building_short(prop.name if prop else ""),
        "floor": str(room.floor or ""),
        "sharing": _tc(_enum_str(tenancy.sharing_type)),
        "check-in": _date_str(tenancy.checkin_date),
        "status": _tc(_enum_str(tenancy.status)),
        "agreed rent": int(tenancy.agreed_rent or 0),
        "deposit": int(tenancy.security_deposit or 0),
        "booking": int(tenancy.booking_amount or 0),
        "maintenance": int(tenancy.maintenance_fee or 0),
        "notice date": _date_str(tenancy.notice_date),
        "expected exit": _date_str(tenancy.expected_checkout),
        "checkout date": _date_str(tenancy.checkout_date),
        "refund status": refund_status_val,
        "refund amount": refund_amount_val,
        "dob": _date_str(tenant.date_of_birth),
        "father name": tenant.father_name or "",
        "father phone": tenant.father_phone or "",
        "address": tenant.permanent_address or "",
        # Split emergency-contact into separate name + phone cells.
        # "Emergency Contact" stays (legacy column) → name only.
        # "Emergency Contact Phone" is additive — populated once present
        # in the TENANTS sheet header row.
        "emergency contact": tenant.emergency_contact_name or "",
        "emergency contact phone": tenant.emergency_contact_phone or "",
        "emergency relationship": tenant.emergency_contact_relationship or "",
        "email": tenant.email or "",
        "occupation": tenant.occupation or "",
        "education": tenant.educational_qualification or "",
        "office address": tenant.office_address or "",
        "office phone": tenant.office_phone or "",
        "id type": tenant.id_proof_type or "",
        "id number": tenant.id_proof_number or "",
        "food pref": tenant.food_preference or "",
        "notes": tenancy.notes or "",
    }

    # Write TENANTS tab — locate row by room+name, batch-update only
    # cells whose value differs from current.
    try:
        t_ws = _get_worksheet_sync("TENANTS")
        t_vals = t_ws.get_all_values()
        t_headers = [h.strip().lower() for h in t_vals[0]] if t_vals else []
        name_lower = (tenant.name or "").strip().lower()
        room_upper = str(room.room_number).strip().upper()
        target_row = None
        for i in range(1, len(t_vals)):
            r = t_vals[i]
            if not r or len(r) < 2:
                continue
            if (str(r[T_ROOM]).strip().upper() == room_upper and
                    name_lower in str(r[T_NAME]).strip().lower()):
                target_row = i + 1  # 1-based
                break
        if target_row is None:
            for i in range(1, len(t_vals)):
                r = t_vals[i]
                if r and len(r) > 1 and name_lower == str(r[T_NAME]).strip().lower():
                    target_row = i + 1
                    break
        if target_row is not None:
            # Build batch of {range, values} only for fields that changed.
            existing = t_vals[target_row - 1] if target_row - 1 < len(t_vals) else []
            batch = []
            for i, hdr in enumerate(t_headers):
                if hdr not in tenants_row:
                    continue
                if hdr in skip:
                    continue
                new_v = tenants_row[hdr]
                cur_v = str(existing[i]).strip() if i < len(existing) else ""
                if str(new_v).strip() == cur_v:
                    continue
                cell = gspread.utils.rowcol_to_a1(target_row, i + 1)
                batch.append({"range": cell, "values": [[new_v]]})
            if batch:
                t_ws.batch_update(batch, value_input_option="USER_ENTERED")
                result["tenants_written"] = len(batch)
                logger.info("sync_tenant_all_fields: TENANTS — wrote %d cells for %s", len(batch), tenant.name)
    except Exception as e:
        logger.warning("sync_tenant_all_fields: TENANTS write failed: %s", e)

    # ── Monthly tab row: per-cell diff update, same pattern ───────────────
    # Only sync the CURRENT month tab. Other months stay historical.
    tab_name = _current_month_tab()
    try:
        m_ws = _get_worksheet_sync(tab_name)
        m_vals = m_ws.get_all_values()
        hdr_idx, data_start = _locate_monthly_header(m_vals)
        if hdr_idx >= 0:
            m_headers = [h.strip().lower() for h in m_vals[hdr_idx]]
            target_row = None
            for i in range(data_start, len(m_vals)):
                r = m_vals[i]
                if not r or len(r) < 2 or not r[0]:
                    continue
                if (str(r[0]).strip().upper() == room_upper and
                        name_lower in str(r[1]).strip().lower()):
                    target_row = i + 1
                    break
            if target_row is not None:
                existing = m_vals[target_row - 1]
                # Monthly tab fields it covers (rest recomputed by full sync)
                monthly_row = {
                    "room": room.room_number,
                    "name": tenant.name or "",
                    "phone": tenant.phone or "",
                    "building": prop.name if prop else "",
                    "sharing": _enum_str(tenancy.sharing_type),
                    "rent": int(tenancy.agreed_rent or 0),
                    "deposit": int(tenancy.security_deposit or 0),
                    "check-in": _date_str(tenancy.checkin_date),
                    "notice date": _date_str(tenancy.notice_date),
                    "notes": tenancy.notes or "",
                }
                batch = []
                for i, hdr in enumerate(m_headers):
                    if hdr not in monthly_row:
                        continue
                    if hdr in skip:
                        continue
                    new_v = monthly_row[hdr]
                    cur_v = str(existing[i]).strip() if i < len(existing) else ""
                    if str(new_v).strip() == cur_v:
                        continue
                    cell = gspread.utils.rowcol_to_a1(target_row, i + 1)
                    batch.append({"range": cell, "values": [[new_v]]})
                if batch:
                    m_ws.batch_update(batch, value_input_option="USER_ENTERED")
                    result["monthly_written"] = len(batch)
                    logger.info("sync_tenant_all_fields: %s — wrote %d cells for %s",
                                tab_name, len(batch), tenant.name)
                    try:
                        _refresh_summary_sync(tab_name)
                    except Exception as _re:
                        logger.warning("sync_tenant_all_fields: summary refresh on %s failed: %s", tab_name, _re)
    except Exception as e:
        logger.warning("sync_tenant_all_fields: monthly write failed: %s", e)

    result["success"] = True
    return result


async def sync_tenant_all_fields(tenant_id: int, skip_fields: list | None = None) -> dict:
    """
    Async entry point for the systemic per-tenant sheet sync.

    Call this after ANY mutation of tenant.* or tenancy.* fields so the
    sheet cells shown to the receptionist stay in lock-step with the DB.

    Fire-and-forget pattern is expected — schedule via asyncio.create_task
    if you don't need to await. Never raises.
    """
    return await asyncio.to_thread(_sync_tenant_all_fields_sync, tenant_id, skip_fields)


def trigger_daywise_sheet_sync() -> None:
    """Fire `scripts/sync_daywise_from_db.py --write` in the background.

    Used after a day-wise stay row mutates (e.g. room move) so the DAY WISE
    tab reflects DB state without waiting for the nightly cron.
    Fire-and-forget — never raises.
    """
    import subprocess
    import sys
    from pathlib import Path

    try:
        project_root = Path(__file__).resolve().parents[2]
        script = project_root / "scripts" / "sync_daywise_from_db.py"
        if not script.exists():
            logger.warning("trigger_daywise_sheet_sync: script not found at %s", script)
            return
        subprocess.Popen(
            [sys.executable, str(script), "--write"],
            cwd=str(project_root),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        logger.info("trigger_daywise_sheet_sync: queued day-wise sync")
    except Exception as e:
        logger.warning("trigger_daywise_sheet_sync failed: %s", e)


def trigger_monthly_sheet_sync(month: int, year: int) -> None:
    """
    Fire `scripts/sync_sheet_from_db.py --month M --year Y --write` in the
    background. Project root + python interpreter resolved from runtime so it
    works locally and on the VPS without hardcoded paths.

    Fire-and-forget — never raises. Used after deposit/rent/field changes so
    the monthly tab summary reflects DB state without waiting for the cron.
    """
    import subprocess
    import sys
    from pathlib import Path

    if _is_frozen_month(month, year):
        logger.warning(
            "trigger_monthly_sheet_sync: blocked frozen month %d/%d (Dec 2025–Mar 2026 is read-only)",
            month, year,
        )
        return

    try:
        project_root = Path(__file__).resolve().parents[2]
        script = project_root / "scripts" / "sync_sheet_from_db.py"
        if not script.exists():
            logger.warning("trigger_monthly_sheet_sync: script not found at %s", script)
            return
        # sys.executable is the running interpreter (venv on both local + VPS)
        subprocess.Popen(
            [sys.executable, str(script),
             "--month", str(month), "--year", str(year), "--write"],
            cwd=str(project_root),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        logger.info("trigger_monthly_sheet_sync: queued sync for %02d/%d", month, year)
    except Exception as e:
        logger.warning("trigger_monthly_sheet_sync failed: %s", e)
