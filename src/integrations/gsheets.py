"""
src/integrations/gsheets.py
============================
Google Sheets write-back for Cozeevo PG payments.

Writes to the "History" sheet whenever a payment is logged via WhatsApp.
Columns referenced (0-indexed):
  [0]  Room No
  [1]  Name
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
  - Batch updates via worksheet.update() to minimize API calls
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
    2: (25, 28, 29),   # FEB: rent_status=col25, cash=col28, upi=col29
    3: (26, 31, 32),   # MARCH: rent_status=col26, cash=col31, upi=col32
}

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
    Matching rules:
      - Room No: exact match (case-insensitive, stripped)
      - Name: case-insensitive substring match (sheet may have full name,
        DB may have partial or vice versa)
    Returns None if not found.
    """
    all_values = ws.get_all_values()
    room_clean = room_number.strip().upper()
    name_lower = tenant_name.strip().lower()

    for i, row in enumerate(all_values):
        if i == 0:  # skip header
            continue
        cell_room = (row[0] if len(row) > 0 else "").strip().upper()
        cell_name = (row[1] if len(row) > 1 else "").strip().lower()

        if cell_room != room_clean:
            continue

        # Flexible name match: either is a substring of the other
        if name_lower in cell_name or cell_name in name_lower:
            return i + 1  # gspread uses 1-based rows

    return None


# ── Cell value helpers ────────────────────────────────────────────────────────

_NUMERIC_RE = re.compile(r"^[\d,.\s]*$")


def _parse_numeric_cell(cell_value: str) -> Optional[float]:
    """
    Parse a cell that should contain a number.
    Returns None if the cell has non-numeric text (e.g. "Received by Chandra anna").
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


def _rent_status_label(total_paid: float, rent_due: float) -> str:
    """Determine rent status string for the sheet."""
    if rent_due <= 0:
        return "PAID" if total_paid > 0 else "NOT PAID"
    if total_paid >= rent_due:
        return "PAID"
    if total_paid > 0:
        return "PARTIALLY PAID"
    return "NOT PAID"


# ── Core update function ─────────────────────────────────────────────────────

def _update_payment_sync(
    room_number: str,
    tenant_name: str,
    amount: float,
    method: str,
    month: int,
    rent_due: float,
) -> dict:
    """
    Synchronous payment update. Returns a result dict with status info.

    Args:
        room_number: e.g. "102", "G03"
        tenant_name: tenant name from DB
        amount: payment amount
        method: "cash" or "upi"
        month: month number (2=Feb, 3=Mar, etc.)
        rent_due: total rent due for the month (for status calc)
    """
    result = {
        "success": False,
        "row": None,
        "warning": None,
        "error": None,
    }

    if month not in MONTH_COLUMNS:
        result["error"] = f"Month {month} not configured in MONTH_COLUMNS"
        return result

    rent_status_col, cash_col, upi_col = MONTH_COLUMNS[month]
    target_col = cash_col if method.lower() == "cash" else upi_col

    try:
        ws = _get_worksheet_sync()
    except Exception as e:
        result["error"] = f"Sheet auth failed: {e}"
        logger.error("GSheets auth error: %s", e)
        return result

    # Find the row
    row = _find_row_sync(ws, room_number, tenant_name)
    if row is None:
        result["error"] = (
            f"Row not found for Room {room_number} / {tenant_name}"
        )
        logger.warning("GSheets: %s", result["error"])
        return result

    result["row"] = row

    # Read current values in the target payment column and the "other" column
    # to calculate total paid for rent status
    try:
        # Batch read: target col + other payment col + rent status col
        # gspread cell addressing is 1-based: row, col
        other_col = upi_col if method.lower() == "cash" else cash_col
        cells_to_read = [
            (row, target_col + 1),   # target payment cell (1-indexed col)
            (row, other_col + 1),    # other payment cell
            (row, COMMENTS_COL + 1), # comments cell
        ]
        # Use batch get for efficiency
        target_cell_val = ws.cell(row, target_col + 1).value or ""
        other_cell_val = ws.cell(row, other_col + 1).value or ""
        comments_val = ws.cell(row, COMMENTS_COL + 1).value or ""
    except Exception as e:
        result["error"] = f"Failed to read cells: {e}"
        logger.error("GSheets read error at row %d: %s", row, e)
        return result

    # Parse the target cell
    existing = _parse_numeric_cell(target_cell_val)
    if existing is None:
        result["warning"] = (
            f"Cell ({row}, {target_col+1}) contains non-numeric text: "
            f"'{target_cell_val}' — skipping update"
        )
        logger.warning("GSheets: %s", result["warning"])
        result["success"] = False
        return result

    # Parse the other payment column for rent status calculation
    other_amount = _parse_numeric_cell(other_cell_val)
    if other_amount is None:
        other_amount = 0.0

    new_value = existing + amount
    total_paid_all = new_value + other_amount
    new_status = _rent_status_label(total_paid_all, rent_due)

    # Build timestamp comment
    ts = datetime.now().strftime("%d-%b %H:%M")
    method_upper = method.upper()
    new_comment_line = f"[{ts}] Rs.{int(amount):,} {method_upper}"
    if comments_val.strip():
        updated_comments = f"{comments_val}\n{new_comment_line}"
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
            "GSheets: updated row %d — Room %s / %s — Rs.%s %s → total %s, status=%s",
            row, room_number, tenant_name, int(amount), method_upper,
            int(new_value), new_status,
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
    month: int,
    rent_due: float,
) -> dict:
    """
    Async entry point — updates Google Sheet after a payment is logged.

    Args:
        room_number: e.g. "102"
        tenant_name: tenant name from DB
        amount: payment amount (float)
        method: "cash" or "upi"
        month: month number (2=Feb, 3=Mar)
        rent_due: effective rent due for rent status calculation

    Returns dict with keys: success, row, warning, error
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

        row = _find_row_sync(ws, room_number, tenant_name)
        if row is None:
            result["error"] = f"Row not found for Room {room_number} / {tenant_name}"
            return

        result["row"] = row
        try:
            existing = ws.cell(row, COMMENTS_COL + 1).value or ""
            ts = datetime.now().strftime("%d-%b %H:%M")
            new_line = f"[{ts}] {comment}"
            updated = f"{existing}\n{new_line}" if existing.strip() else new_line
            ws.update_acell(
                gspread.utils.rowcol_to_a1(row, COMMENTS_COL + 1),
                updated,
            )
            result["success"] = True
        except Exception as e:
            result["error"] = f"Comment update failed: {e}"

    await asyncio.to_thread(_do)
    return result
