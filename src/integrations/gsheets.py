"""
src/integrations/gsheets.py
============================
Google Sheets write-back for Cozeevo PG payments.

Writes to the "History" sheet whenever a payment is logged via WhatsApp.
Columns referenced (0-indexed):
  [0]  Room No
  [1]  Name
  [9]  Monthly Rent
  [10] From 1st FEB (rent revision)
  [11] From 1st May (rent revision)
  [12] Sharing
  [14] Comments
  [16] IN/OUT
  [17] BLOCK
  [25] FEB RENT (status)
  [26] MARCH RENT (status)
  [28] FEB Cash
  [29] FEB UPI
  [31] March Cash
  [32] March UPI

Design decisions:
  - Uses gspread (sync lib) wrapped in asyncio.to_thread for async compat
  - Caches the worksheet handle for 5 minutes (avoids re-auth on every payment)
  - ADD to existing numeric values (never replace)
  - Skips update if cell contains non-numeric text (logs warning)
  - Batch updates via worksheet.batch_update() to minimize API calls
  - Auto-detects month: applies to oldest unpaid month first
  - Overpayment check: warns if total paid > rent due
  - Comments: appends new entries, preserves existing
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from datetime import datetime
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

SHEET_ID = os.getenv(
    "GSHEETS_SHEET_ID",
    "1T4YE7RK2eIZRg330kaOaNb5-8o8kJbxpDzK_7MfoyiA",
)
CREDENTIALS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "credentials",
    "gsheets_service_account.json",
)
WORKSHEET_NAME = "History"

# ── Column mapping per month ──────────────────────────────────────────────────
# month_number -> (rent_status_col, cash_col, upi_col)  — all 0-indexed
MONTH_COLUMNS: dict[int, tuple[int, int, int]] = {
    12: (20, 23, 24),  # DEC: rent_status=col20, cash=col23("until jan Cash"), upi=col24
    1:  (21, 23, 24),  # JAN: rent_status=col21, cash=col23("until jan Cash"), upi=col24
    2:  (25, 28, 29),  # FEB: rent_status=col25, cash=col28, upi=col29
    3:  (26, 31, 32),  # MARCH: rent_status=col26, cash=col31, upi=col32
}

# Rent columns (0-indexed): Monthly Rent, From 1st FEB, From 1st May
RENT_COL = 9
RENT_FEB_COL = 10
RENT_MAY_COL = 11

COMMENTS_COL = 14  # 0-indexed

# ── Worksheet cache ───────────────────────────────────────────────────────────

_ws_cache: Optional[gspread.Worksheet] = None
_ws_cache_time: float = 0
_CACHE_TTL = 300  # 5 minutes


def _get_worksheet_sync() -> gspread.Worksheet:
    """Return authorized gspread worksheet, with 5-min cache."""
    global _ws_cache, _ws_cache_time

    now = time.time()
    if _ws_cache is not None and (now - _ws_cache_time) < _CACHE_TTL:
        return _ws_cache

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=scopes)
    gc = gspread.authorize(creds)
    spreadsheet = gc.open_by_key(SHEET_ID)
    ws = spreadsheet.worksheet(WORKSHEET_NAME)

    _ws_cache = ws
    _ws_cache_time = now
    logger.info("GSheets: authorized and cached worksheet '%s'", WORKSHEET_NAME)
    return ws


async def get_sheet() -> gspread.Worksheet:
    """Async wrapper — returns authorized History worksheet."""
    return await asyncio.to_thread(_get_worksheet_sync)


# ── Row lookup ────────────────────────────────────────────────────────────────

def _find_row_sync(
    ws: gspread.Worksheet,
    room_number: str,
    tenant_name: str,
) -> Optional[int]:
    """
    Find the 1-based row index matching Room No + tenant Name.
    Returns None if not found.
    """
    all_values = ws.get_all_values()
    room_clean = room_number.strip().upper()
    name_lower = tenant_name.strip().lower()

    for i, row in enumerate(all_values):
        if i == 0:
            continue
        cell_room = (row[0] if len(row) > 0 else "").strip().upper()
        cell_name = (row[1] if len(row) > 1 else "").strip().lower()

        if cell_room != room_clean:
            continue

        if name_lower in cell_name or cell_name in name_lower:
            return i + 1  # gspread uses 1-based rows

    return None


def _find_row_with_data(
    ws: gspread.Worksheet,
    room_number: str,
    tenant_name: str,
) -> Optional[tuple[int, list[str]]]:
    """
    Find the 1-based row index AND return the full row data.
    Returns (row_index, row_data) or None.
    """
    all_values = ws.get_all_values()
    room_clean = room_number.strip().upper()
    name_lower = tenant_name.strip().lower()

    for i, row in enumerate(all_values):
        if i == 0:
            continue
        cell_room = (row[0] if len(row) > 0 else "").strip().upper()
        cell_name = (row[1] if len(row) > 1 else "").strip().lower()

        if cell_room != room_clean:
            continue

        if name_lower in cell_name or cell_name in name_lower:
            return (i + 1, row)

    return None


# ── Cell value helpers ────────────────────────────────────────────────────────

_NUMERIC_RE = re.compile(r"^[\d,.\s]*$")


def _parse_numeric_cell(cell_value: str) -> Optional[float]:
    """
    Parse a cell that should contain a number.
    Returns None if the cell has non-numeric text.
    Empty cells return 0.
    """
    val = cell_value.strip()
    if not val:
        return 0.0
    if _NUMERIC_RE.match(val):
        cleaned = val.replace(",", "").replace(" ", "")
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _get_rent_due(row_data: list[str]) -> float:
    """
    Get current rent from row data.
    Priority: From 1st May > From 1st FEB > Monthly Rent
    """
    for col in [RENT_MAY_COL, RENT_FEB_COL, RENT_COL]:
        if col < len(row_data):
            val = _parse_numeric_cell(row_data[col])
            if val and val > 0:
                return val
    return 0.0


def _get_month_status(row_data: list[str], month: int) -> str:
    """Get the rent status text for a given month from row data."""
    if month not in MONTH_COLUMNS:
        return ""
    status_col = MONTH_COLUMNS[month][0]
    if status_col < len(row_data):
        return row_data[status_col].strip().upper()
    return ""


def _rent_status_label(total_paid: float, rent_due: float) -> str:
    """Determine rent status string for the sheet."""
    if rent_due <= 0:
        return "PAID" if total_paid > 0 else "NOT PAID"
    if total_paid >= rent_due:
        return "PAID"
    if total_paid > 0:
        return "PARTIALLY PAID"
    return "NOT PAID"


def _detect_month(row_data: list[str]) -> Optional[int]:
    """
    Auto-detect which month to apply payment to.
    Logic: apply to oldest unpaid month first.
    Returns month number (2=Feb, 3=Mar) or None if all paid.
    """
    for month in sorted(MONTH_COLUMNS.keys()):
        status = _get_month_status(row_data, month)
        if status in ("NO SHOW", "EXIT", "CANCELLED", ""):
            continue  # skip months where tenant wasn't present
        if status in ("NOT PAID", "PARTIALLY PAID"):
            return month
    # All months are PAID — default to current month (for advance payments)
    now = datetime.now()
    return now.month if now.month in MONTH_COLUMNS else max(MONTH_COLUMNS.keys())


# ── Core update function ─────────────────────────────────────────────────────

def _update_payment_sync(
    room_number: str,
    tenant_name: str,
    amount: float,
    method: str,
    month: Optional[int],
    rent_due: float,
) -> dict:
    """
    Synchronous payment update. Returns a result dict with status info.
    """
    result = {
        "success": False,
        "row": None,
        "month": month,
        "rent_due": 0.0,
        "total_paid": 0.0,
        "overpayment": 0.0,
        "warning": None,
        "error": None,
    }

    try:
        ws = _get_worksheet_sync()
    except Exception as e:
        result["error"] = f"Sheet auth failed: {e}"
        logger.error("GSheets auth error: %s", e)
        return result

    # Find the row with full data
    found = _find_row_with_data(ws, room_number, tenant_name)
    if found is None:
        result["error"] = f"Row not found for Room {room_number} / {tenant_name}"
        logger.warning("GSheets: %s", result["error"])
        return result

    row, row_data = found
    result["row"] = row

    # Get rent from sheet (not from DB — sheet is source of truth)
    sheet_rent = _get_rent_due(row_data)
    if sheet_rent > 0:
        rent_due = sheet_rent
    result["rent_due"] = rent_due

    # Auto-detect month if not specified
    if month is None or month == 0:
        month = _detect_month(row_data)
    result["month"] = month

    if month not in MONTH_COLUMNS:
        result["error"] = f"Month {month} not configured in MONTH_COLUMNS"
        return result

    rent_status_col, cash_col, upi_col = MONTH_COLUMNS[month]
    target_col = cash_col if method.lower() == "cash" else upi_col
    other_col = upi_col if method.lower() == "cash" else cash_col

    # Read current values from row_data (already fetched)
    target_cell_val = row_data[target_col] if target_col < len(row_data) else ""
    other_cell_val = row_data[other_col] if other_col < len(row_data) else ""
    comments_val = row_data[COMMENTS_COL] if COMMENTS_COL < len(row_data) else ""

    # Parse the target cell
    existing = _parse_numeric_cell(target_cell_val)
    if existing is None:
        result["warning"] = (
            f"Cell contains text: '{target_cell_val[:40]}' — cannot add to it. "
            f"Please update manually."
        )
        logger.warning("GSheets: %s", result["warning"])
        return result

    # Parse the other payment column
    other_amount = _parse_numeric_cell(other_cell_val)
    if other_amount is None:
        other_amount = 0.0

    new_value = existing + amount
    total_paid_all = new_value + other_amount
    result["total_paid"] = total_paid_all

    # Check overpayment
    if rent_due > 0 and total_paid_all > rent_due:
        overpayment = total_paid_all - rent_due
        result["overpayment"] = overpayment
        result["warning"] = (
            f"Overpayment: total Rs.{int(total_paid_all):,} vs rent Rs.{int(rent_due):,} "
            f"(+Rs.{int(overpayment):,} extra)"
        )

    new_status = _rent_status_label(total_paid_all, rent_due)

    # Build timestamp comment (append to existing)
    ts = datetime.now().strftime("%d-%b %H:%M")
    method_upper = method.upper()
    month_names = {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun"}
    month_label = month_names.get(month, f"M{month}")
    new_comment_line = f"[{ts}] Rs.{int(amount):,} {method_upper} for {month_label}"

    if comments_val.strip():
        updated_comments = f"{comments_val} | {new_comment_line}"
    else:
        updated_comments = new_comment_line

    # Batch update: payment cell + rent status + comments
    try:
        batch_updates = [
            {
                "range": gspread.utils.rowcol_to_a1(row, target_col + 1),
                "values": [[new_value]],
            },
            {
                "range": gspread.utils.rowcol_to_a1(row, rent_status_col + 1),
                "values": [[new_status]],
            },
            {
                "range": gspread.utils.rowcol_to_a1(row, COMMENTS_COL + 1),
                "values": [[updated_comments]],
            },
        ]
        ws.batch_update(batch_updates, value_input_option="USER_ENTERED")
        result["success"] = True
        logger.info(
            "GSheets: row %d — Room %s / %s — Rs.%s %s %s → total %s/%s, status=%s",
            row, room_number, tenant_name, int(amount), method_upper,
            month_label, int(total_paid_all), int(rent_due), new_status,
        )
    except Exception as e:
        result["error"] = f"Batch update failed: {e}"
        logger.error("GSheets batch update error: %s", e)

    return result


async def update_payment(
    room_number: str,
    tenant_name: str,
    amount: float,
    method: str,
    month: Optional[int] = None,
    rent_due: float = 0.0,
) -> dict:
    """
    Async entry point — updates Google Sheet after a payment is logged.

    Args:
        room_number: e.g. "102"
        tenant_name: tenant name from DB
        amount: payment amount (float)
        method: "cash" or "upi"
        month: month number (2=Feb, 3=Mar). None = auto-detect oldest unpaid
        rent_due: fallback rent (used only if sheet has no rent data)

    Returns dict with keys: success, row, month, rent_due, total_paid, overpayment, warning, error
    """
    return await asyncio.to_thread(
        _update_payment_sync,
        room_number,
        tenant_name,
        amount,
        method,
        month,
        rent_due,
    )


async def add_comment(room_number: str, tenant_name: str, comment: str) -> dict:
    """
    Append a comment to the Comments column for a tenant row.
    Returns dict with keys: success, row, error
    """
    result = {"success": False, "row": None, "error": None}

    def _do():
        try:
            ws = _get_worksheet_sync()
        except Exception as e:
            result["error"] = f"Sheet auth failed: {e}"
            return

        found = _find_row_with_data(ws, room_number, tenant_name)
        if found is None:
            result["error"] = f"Row not found for Room {room_number} / {tenant_name}"
            return

        row, row_data = found
        result["row"] = row
        try:
            existing = row_data[COMMENTS_COL] if COMMENTS_COL < len(row_data) else ""
            ts = datetime.now().strftime("%d-%b %H:%M")
            new_line = f"[{ts}] {comment}"
            updated = f"{existing} | {new_line}" if existing.strip() else new_line
            ws.update_acell(
                gspread.utils.rowcol_to_a1(row, COMMENTS_COL + 1),
                updated,
            )
            result["success"] = True
        except Exception as e:
            result["error"] = f"Comment update failed: {e}"

    await asyncio.to_thread(_do)
    return result


async def get_tenant_dues(room_number: str, tenant_name: str) -> dict:
    """
    Get month-by-month dues breakdown for a tenant from the sheet.
    Returns dict with: success, rent_due, months (list of {month, status, cash, upi, total_paid, due})
    """
    result = {"success": False, "rent_due": 0, "months": [], "error": None}

    def _do():
        try:
            ws = _get_worksheet_sync()
        except Exception as e:
            result["error"] = f"Sheet auth failed: {e}"
            return

        found = _find_row_with_data(ws, room_number, tenant_name)
        if found is None:
            result["error"] = f"Row not found for Room {room_number} / {tenant_name}"
            return

        row, row_data = found
        rent_due = _get_rent_due(row_data)
        result["rent_due"] = rent_due
        month_names = {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May"}

        for month in sorted(MONTH_COLUMNS.keys()):
            status = _get_month_status(row_data, month)
            if status in ("NO SHOW", "EXIT", "CANCELLED", ""):
                continue

            rent_status_col, cash_col, upi_col = MONTH_COLUMNS[month]
            cash = _parse_numeric_cell(row_data[cash_col] if cash_col < len(row_data) else "") or 0
            upi = _parse_numeric_cell(row_data[upi_col] if upi_col < len(row_data) else "") or 0
            total_paid = cash + upi
            due = max(0, rent_due - total_paid)

            result["months"].append({
                "month": month,
                "month_name": month_names.get(month, f"M{month}"),
                "status": status,
                "cash": cash,
                "upi": upi,
                "total_paid": total_paid,
                "due": due,
            })

        result["success"] = True

    await asyncio.to_thread(_do)
    return result
