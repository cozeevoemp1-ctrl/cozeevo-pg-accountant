"""
Month payments ledger → .xlsx.

Renders the rows produced by `src.api.v2.kpi._month_payment_rows` — one row per
payment, cash and UPI in their own columns, matching the Activity month table in
the PWA. Column names live in HEADERS; rows are built as dicts and flattened only
at write time, so a column can be added in one place.
"""
from __future__ import annotations

import io
from datetime import date, datetime

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from src.utils.inr_format import INR_NUMBER_FORMAT

HEADERS = [
    "Date", "Time", "Room", "Tenant", "Cash", "UPI",
    "Type", "For period", "Logged on",
]

# Excel column widths, keyed by header — never by index.
WIDTHS = {
    "Date": 13, "Time": 10, "Room": 8, "Tenant": 30, "Cash": 14, "UPI": 14,
    "Type": 12, "For period": 12, "Logged on": 13,
}

MONEY_COLS = ("Cash", "UPI")

_TYPE_LABEL = {"rent": "Rent", "deposit": "Deposit", "booking": "Advance",
               "maintenance": "Maintenance"}

_HEAD_FILL = PatternFill("solid", fgColor="F2EFEC")
_HEAD_FONT = Font(bold=True, size=10, color="4C4753")
_TOTAL_FONT = Font(bold=True, size=11)
_HAIR = Side(style="thin", color="D9D5D1")
_BORDER = Border(left=_HAIR, right=_HAIR, top=_HAIR, bottom=_HAIR)


def _fmt_day(iso: str) -> str:
    if not iso:
        return ""
    return date.fromisoformat(iso).strftime("%d %b %Y")


def _split_logged(iso: str) -> tuple[str, str]:
    """Return (time, date) from an ISO timestamp."""
    if not iso:
        return "", ""
    dt = datetime.fromisoformat(iso)
    return dt.strftime("%I:%M %p").lstrip("0"), dt.strftime("%d %b %Y")


def _period(iso: str) -> str:
    if not iso:
        return ""
    return date.fromisoformat(iso).strftime("%b %Y")


def build_month_payments_xlsx(month: str, rows: list[dict]) -> bytes:
    """Build the workbook. `month` is 'YYYY-MM'; `rows` come from _month_payment_rows."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"Payments {month}"

    ws.append(HEADERS)
    for i, h in enumerate(HEADERS, start=1):
        c = ws.cell(row=1, column=i)
        c.fill, c.font, c.border = _HEAD_FILL, _HEAD_FONT, _BORDER
        c.alignment = Alignment(horizontal="right" if h in MONEY_COLS else "left")
        ws.column_dimensions[get_column_letter(i)].width = WIDTHS[h]

    for r in rows:
        logged_time, logged_day = _split_logged(r.get("logged_at", ""))
        pay_day = _fmt_day(r.get("date", ""))
        row = {
            "Date":       pay_day,
            "Time":       logged_time,
            "Room":       r.get("room_number") or "—",
            "Tenant":     r.get("tenant_name") or "",
            # A payment has exactly one mode, so exactly one of these is a number.
            "Cash":       r["amount"] if r.get("mode") == "cash" else None,
            "UPI":        r["amount"] if r.get("mode") == "upi" else None,
            "Type":       _TYPE_LABEL.get(r.get("for_type", ""), r.get("for_type", "")),
            "For period": _period(r.get("period_month", "")),
            # Only meaningful when the money arrived on a different day than it was entered.
            "Logged on":  logged_day if logged_day and logged_day != pay_day else "",
        }
        ws.append([row[h] for h in HEADERS])

    last = ws.max_row
    for r_i in range(2, last + 1):
        for c_i, h in enumerate(HEADERS, start=1):
            c = ws.cell(row=r_i, column=c_i)
            c.border = _BORDER
            if h in MONEY_COLS:
                c.number_format = INR_NUMBER_FORMAT

    total_row = last + 1
    ws.cell(row=total_row, column=1, value="TOTAL").font = _TOTAL_FONT
    for h in MONEY_COLS:
        idx = HEADERS.index(h) + 1
        col = get_column_letter(idx)
        c = ws.cell(row=total_row, column=idx)
        c.value = f"=SUM({col}2:{col}{last})" if last >= 2 else 0
        c.number_format = INR_NUMBER_FORMAT
        c.font = _TOTAL_FONT

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(HEADERS))}{last}"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
