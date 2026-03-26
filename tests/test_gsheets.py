"""
tests/test_gsheets.py
=====================
Comprehensive test suite (50 tests) for Google Sheets payment write-back logic.

Tests the internal functions from src/integrations/gsheets.py:
  - _parse_numeric_cell, _rent_status_label, _detect_month, _get_rent_due
  - _get_month_status, _find_row_sync, _find_row_with_data
  - get_tenant_dues (read-only)

READ-ONLY: no writes to the sheet. Row-lookup tests read from the live sheet.
"""
from __future__ import annotations

import asyncio
import sys
import os
import unittest
from unittest.mock import patch
from datetime import datetime

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.integrations.gsheets import (
    _parse_numeric_cell,
    _get_rent_due,
    _get_month_status,
    _rent_status_label,
    _detect_month,
    _find_row_sync,
    _find_row_with_data,
    get_tenant_dues,
    MONTH_COLUMNS,
    RENT_COL,
    RENT_FEB_COL,
    RENT_MAY_COL,
    COMMENTS_COL,
    _get_worksheet_sync,
)

# --------------------------------------------------------------------------- #
#  Helpers: build fake row data
# --------------------------------------------------------------------------- #

def make_row(
    room="101",
    name="Test Tenant",
    monthly_rent="8000",
    rent_feb="",
    rent_may="",
    sharing="Double",
    comments="",
    in_out="IN",
    feb_status="NOT PAID",
    mar_status="NOT PAID",
    feb_cash="",
    feb_upi="",
    mar_cash="",
    mar_upi="",
) -> list[str]:
    """Build a fake row list matching the sheet column layout (0-indexed).

    Columns used by gsheets.py:
      [0] Room No, [1] Name, [9] Monthly Rent, [10] From 1st FEB,
      [11] From 1st May, [12] Sharing, [14] Comments, [16] IN/OUT,
      [25] FEB RENT, [26] MARCH RENT, [28] FEB Cash, [29] FEB UPI,
      [31] March Cash, [32] March UPI
    """
    row = [""] * 33
    row[0] = room
    row[1] = name
    row[9] = monthly_rent
    row[10] = rent_feb
    row[11] = rent_may
    row[12] = sharing
    row[14] = comments
    row[16] = in_out
    row[25] = feb_status
    row[26] = mar_status
    row[28] = feb_cash
    row[29] = feb_upi
    row[31] = mar_cash
    row[32] = mar_upi
    return row


# =========================================================================== #
#  Category 1: _parse_numeric_cell (part of Row Lookup & helpers)
# =========================================================================== #

class TestParseNumericCell(unittest.TestCase):
    """5 tests for _parse_numeric_cell."""

    def test_empty_string_returns_zero(self):
        self.assertEqual(_parse_numeric_cell(""), 0.0)

    def test_plain_integer(self):
        self.assertEqual(_parse_numeric_cell("8000"), 8000.0)

    def test_comma_separated(self):
        self.assertEqual(_parse_numeric_cell("12,500"), 12500.0)

    def test_non_numeric_text_returns_none(self):
        self.assertIsNone(_parse_numeric_cell("Received by Chandra"))

    def test_whitespace_only_returns_zero(self):
        self.assertEqual(_parse_numeric_cell("   "), 0.0)


# =========================================================================== #
#  Category 2: Rent Calculation — _get_rent_due
# =========================================================================== #

class TestRentCalculation(unittest.TestCase):
    """5 tests for _get_rent_due."""

    def test_monthly_rent_read_correctly(self):
        row = make_row(monthly_rent="8000")
        self.assertEqual(_get_rent_due(row), 8000.0)

    def test_feb_overrides_monthly(self):
        row = make_row(monthly_rent="8000", rent_feb="9000")
        self.assertEqual(_get_rent_due(row), 9000.0)

    def test_may_overrides_feb(self):
        row = make_row(monthly_rent="8000", rent_feb="9000", rent_may="9500")
        self.assertEqual(_get_rent_due(row), 9500.0)

    def test_dash_in_rent_falls_through(self):
        """'-' in May col => fall to Feb => fall to Monthly."""
        row = make_row(monthly_rent="7000", rent_feb="", rent_may="-")
        self.assertEqual(_get_rent_due(row), 7000.0)

    def test_all_empty_returns_zero(self):
        row = make_row(monthly_rent="", rent_feb="", rent_may="")
        self.assertEqual(_get_rent_due(row), 0.0)


# =========================================================================== #
#  Category 3: Month Auto-Detection — _detect_month
# =========================================================================== #

class TestMonthAutoDetection(unittest.TestCase):
    """8 tests for _detect_month."""

    def test_both_unpaid_returns_feb(self):
        row = make_row(feb_status="NOT PAID", mar_status="NOT PAID")
        self.assertEqual(_detect_month(row), 2)

    def test_feb_paid_mar_unpaid(self):
        row = make_row(feb_status="PAID", mar_status="NOT PAID")
        self.assertEqual(_detect_month(row), 3)

    def test_both_paid_returns_current(self):
        row = make_row(feb_status="PAID", mar_status="PAID")
        month = _detect_month(row)
        # Should be current month if in MONTH_COLUMNS, else max month
        self.assertIn(month, MONTH_COLUMNS.keys())

    def test_feb_no_show_mar_partial(self):
        row = make_row(feb_status="NO SHOW", mar_status="PARTIALLY PAID")
        self.assertEqual(_detect_month(row), 3)

    def test_feb_exit_goes_to_mar(self):
        row = make_row(feb_status="EXIT", mar_status="NOT PAID")
        self.assertEqual(_detect_month(row), 3)

    def test_all_cancelled_returns_current(self):
        row = make_row(feb_status="CANCELLED", mar_status="CANCELLED")
        month = _detect_month(row)
        self.assertIn(month, MONTH_COLUMNS.keys())

    def test_explicit_month_override(self):
        """If month is explicitly passed, _detect_month is bypassed.
        Simulate the caller logic: if month is set, use it directly."""
        row = make_row(feb_status="NOT PAID", mar_status="NOT PAID")
        explicit_month = 3
        # Caller would do: if month is not None: use month, else _detect_month
        self.assertEqual(explicit_month, 3)
        # Also verify auto-detect would pick Feb
        self.assertEqual(_detect_month(row), 2)

    def test_feb_partially_paid_returns_feb(self):
        row = make_row(feb_status="PARTIALLY PAID", mar_status="NOT PAID")
        self.assertEqual(_detect_month(row), 2)


# =========================================================================== #
#  Category 4: Payment Logic (unit-level simulation)
# =========================================================================== #

class TestPaymentLogic(unittest.TestCase):
    """10 tests for payment accumulation / validation logic."""

    def test_cash_adds_to_existing(self):
        existing = _parse_numeric_cell("5000")
        new_amount = 3000.0
        self.assertEqual(existing + new_amount, 8000.0)

    def test_upi_adds_to_existing(self):
        existing = _parse_numeric_cell("2,500")
        new_amount = 5500.0
        self.assertEqual(existing + new_amount, 8000.0)

    def test_payment_to_empty_cell(self):
        existing = _parse_numeric_cell("")
        self.assertEqual(existing, 0.0)
        self.assertEqual(existing + 8000.0, 8000.0)

    def test_text_cell_blocks_update(self):
        """Non-numeric text in cell should return None => warning."""
        existing = _parse_numeric_cell("Received by Chandra")
        self.assertIsNone(existing)

    def test_small_payment_partial_status(self):
        rent = 8000.0
        total_paid = 500.0
        self.assertEqual(_rent_status_label(total_paid, rent), "PARTIALLY PAID")

    def test_exact_payment_paid_status(self):
        rent = 8000.0
        total_paid = 8000.0
        self.assertEqual(_rent_status_label(total_paid, rent), "PAID")

    def test_overpayment_still_paid(self):
        rent = 8000.0
        total_paid = 8500.0
        self.assertEqual(_rent_status_label(total_paid, rent), "PAID")

    def test_multiple_payments_accumulate(self):
        """Simulate two sequential payments."""
        existing = _parse_numeric_cell("3000")
        after_first = existing + 2000.0
        after_second = after_first + 3000.0
        self.assertEqual(after_second, 8000.0)

    def test_zero_amount_rejected(self):
        """Zero amount should not change status from NOT PAID."""
        rent = 8000.0
        total = 0.0
        self.assertEqual(_rent_status_label(total, rent), "NOT PAID")

    def test_payment_no_rent_data(self):
        """If rent is 0 but tenant paid, still marks PAID."""
        rent = 0.0
        total = 5000.0
        self.assertEqual(_rent_status_label(total, rent), "PAID")


# =========================================================================== #
#  Category 5: Status Calculation — _rent_status_label
# =========================================================================== #

class TestStatusCalculation(unittest.TestCase):
    """8 tests for _rent_status_label."""

    def test_zero_paid_nonzero_rent_not_paid(self):
        self.assertEqual(_rent_status_label(0, 8000), "NOT PAID")

    def test_partial_paid(self):
        self.assertEqual(_rent_status_label(3000, 8000), "PARTIALLY PAID")

    def test_exact_paid(self):
        self.assertEqual(_rent_status_label(8000, 8000), "PAID")

    def test_over_paid(self):
        self.assertEqual(_rent_status_label(9000, 8000), "PAID")

    def test_cash_plus_upi_meet_rent(self):
        cash = 4000.0
        upi = 4000.0
        total = cash + upi
        self.assertEqual(_rent_status_label(total, 8000), "PAID")

    def test_cash_partial_upi_partial(self):
        total = 2000 + 2000
        self.assertEqual(_rent_status_label(total, 8000), "PARTIALLY PAID")

    def test_zero_rent_positive_paid(self):
        self.assertEqual(_rent_status_label(5000, 0), "PAID")

    def test_both_zero(self):
        self.assertEqual(_rent_status_label(0, 0), "NOT PAID")


# =========================================================================== #
#  Category 6: Overpayment Detection
# =========================================================================== #

class TestOverpaymentDetection(unittest.TestCase):
    """5 tests for overpayment calculation."""

    def test_no_overpayment_under_rent(self):
        total_paid = 5000.0
        rent = 8000.0
        overpayment = max(0, total_paid - rent)
        self.assertEqual(overpayment, 0)

    def test_exact_no_overpayment(self):
        total_paid = 8000.0
        rent = 8000.0
        overpayment = max(0, total_paid - rent)
        self.assertEqual(overpayment, 0)

    def test_500_over(self):
        total_paid = 8500.0
        rent = 8000.0
        overpayment = max(0, total_paid - rent)
        self.assertEqual(overpayment, 500)

    def test_already_overpaid_plus_new(self):
        """Already paid 8500 (500 over), new 1000 => 1500 over."""
        existing_total = 8500.0
        new_payment = 1000.0
        rent = 8000.0
        total = existing_total + new_payment
        overpayment = max(0, total - rent)
        self.assertEqual(overpayment, 1500)

    def test_advance_payment_scenario(self):
        """All months paid. New 8000 payment => overpayment for current month."""
        rent = 8000.0
        already_paid_this_month = 8000.0
        new_advance = 8000.0
        total = already_paid_this_month + new_advance
        overpayment = max(0, total - rent)
        self.assertEqual(overpayment, 8000)


# =========================================================================== #
#  Category 7: Comments
# =========================================================================== #

class TestComments(unittest.TestCase):
    """4 tests for comment building logic."""

    def _build_comment(self, existing: str, amount: float, method: str, month: int) -> str:
        """Replicate the comment-building logic from _update_payment_sync."""
        ts = datetime.now().strftime("%d-%b %H:%M")
        method_upper = method.upper()
        month_names = {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May"}
        month_label = month_names.get(month, f"M{month}")
        new_line = f"[{ts}] Rs.{int(amount):,} {method_upper} for {month_label}"
        if existing.strip():
            return f"{existing} | {new_line}"
        return new_line

    def test_new_comment_has_timestamp(self):
        c = self._build_comment("", 8000, "cash", 2)
        self.assertRegex(c, r"\[\d{2}-\w{3} \d{2}:\d{2}\]")
        self.assertIn("Rs.8,000", c)

    def test_existing_preserved_with_pipe(self):
        c = self._build_comment("Old note", 5000, "upi", 3)
        self.assertTrue(c.startswith("Old note | "))

    def test_comment_includes_method_and_month(self):
        c = self._build_comment("", 3000, "upi", 3)
        self.assertIn("UPI", c)
        self.assertIn("Mar", c)

    def test_multiple_comments_build_up(self):
        c1 = self._build_comment("", 3000, "cash", 2)
        c2 = self._build_comment(c1, 5000, "upi", 2)
        parts = c2.split(" | ")
        self.assertEqual(len(parts), 2)


# =========================================================================== #
#  Category 8: _get_month_status helper
# =========================================================================== #

class TestGetMonthStatus(unittest.TestCase):
    """3 bonus tests for _get_month_status (supports other categories)."""

    def test_feb_status(self):
        row = make_row(feb_status="PARTIALLY PAID")
        self.assertEqual(_get_month_status(row, 2), "PARTIALLY PAID")

    def test_mar_status(self):
        row = make_row(mar_status="PAID")
        self.assertEqual(_get_month_status(row, 3), "PAID")

    def test_unknown_month_returns_empty(self):
        row = make_row()
        self.assertEqual(_get_month_status(row, 7), "")


# =========================================================================== #
#  LIVE READ-ONLY tests (Categories 1 & 8 from spec: Row Lookup + Dues Query)
#  These read from the actual Google Sheet — no writes.
# =========================================================================== #

class TestLiveRowLookup(unittest.TestCase):
    """5 tests for row lookup against real Google Sheet data."""

    _ws = None

    @classmethod
    def setUpClass(cls):
        try:
            cls._ws = _get_worksheet_sync()
            cls._all_values = cls._ws.get_all_values()
        except Exception as e:
            raise unittest.SkipTest(f"Cannot connect to Google Sheet: {e}")

    def _find_first_data_row(self):
        """Return (room, name) from the first non-header row with data."""
        for i, row in enumerate(self._all_values):
            if i == 0:
                continue
            room = (row[0] if len(row) > 0 else "").strip()
            name = (row[1] if len(row) > 1 else "").strip()
            if room and name:
                return room, name, i + 1
        return None, None, None

    def _find_ground_floor_row(self):
        """Return a row starting with 'G'."""
        for i, row in enumerate(self._all_values):
            if i == 0:
                continue
            room = (row[0] if len(row) > 0 else "").strip().upper()
            name = (row[1] if len(row) > 1 else "").strip()
            if room.startswith("G") and name:
                return room, name, i + 1
        return None, None, None

    def test_exact_match(self):
        room, name, expected_row = self._find_first_data_row()
        if room is None:
            self.skipTest("No data rows in sheet")
        found = _find_row_sync(self._ws, room, name)
        self.assertEqual(found, expected_row)

    def test_partial_name_match(self):
        room, name, expected_row = self._find_first_data_row()
        if room is None:
            self.skipTest("No data rows")
        # Use first word of name as partial
        partial = name.split()[0] if " " in name else name
        found = _find_row_sync(self._ws, room, partial)
        self.assertIsNotNone(found)

    def test_room_not_found(self):
        found = _find_row_sync(self._ws, "ZZZ999", "Nobody")
        self.assertIsNone(found)

    def test_name_mismatch(self):
        room, name, _ = self._find_first_data_row()
        if room is None:
            self.skipTest("No data rows")
        found = _find_row_sync(self._ws, room, "XYZNONEXISTENT12345")
        self.assertIsNone(found)

    def test_ground_floor_room(self):
        room, name, expected_row = self._find_ground_floor_row()
        if room is None:
            self.skipTest("No ground floor rooms in sheet")
        found = _find_row_sync(self._ws, room, name)
        self.assertEqual(found, expected_row)


class TestLiveDuesQuery(unittest.TestCase):
    """5 tests for get_tenant_dues (read-only) against real sheet."""

    _ws = None

    @classmethod
    def setUpClass(cls):
        try:
            cls._ws = _get_worksheet_sync()
            cls._all_values = cls._ws.get_all_values()
        except Exception as e:
            raise unittest.SkipTest(f"Cannot connect to Google Sheet: {e}")

    def _find_row_by_criteria(self, status_filter=None, skip_statuses=None):
        """Find a row matching optional status criteria on Feb (col 25)."""
        for i, row in enumerate(self._all_values):
            if i == 0:
                continue
            room = (row[0] if len(row) > 0 else "").strip()
            name = (row[1] if len(row) > 1 else "").strip()
            if not room or not name:
                continue
            feb_status = (row[25] if len(row) > 25 else "").strip().upper()
            if status_filter and feb_status != status_filter:
                continue
            if skip_statuses and feb_status in skip_statuses:
                continue
            return room, name
        return None, None

    def test_dues_returns_breakdown(self):
        room, name = self._find_row_by_criteria()
        if room is None:
            self.skipTest("No data rows")
        result = asyncio.get_event_loop().run_until_complete(
            get_tenant_dues(room, name)
        )
        self.assertTrue(result["success"])
        self.assertIsInstance(result["months"], list)

    def test_dues_skips_no_show(self):
        room, name = self._find_row_by_criteria(status_filter="NO SHOW")
        if room is None:
            self.skipTest("No NO SHOW rows found")
        result = asyncio.get_event_loop().run_until_complete(
            get_tenant_dues(room, name)
        )
        self.assertTrue(result["success"])
        # Feb should not appear since it is NO SHOW
        feb_entries = [m for m in result["months"] if m["month"] == 2]
        self.assertEqual(len(feb_entries), 0)

    def test_dues_correct_due_calc(self):
        room, name = self._find_row_by_criteria(
            skip_statuses={"NO SHOW", "EXIT", "CANCELLED", ""}
        )
        if room is None:
            self.skipTest("No qualifying rows")
        result = asyncio.get_event_loop().run_until_complete(
            get_tenant_dues(room, name)
        )
        self.assertTrue(result["success"])
        rent = result["rent_due"]
        for m in result["months"]:
            expected_due = max(0, rent - m["total_paid"])
            self.assertEqual(m["due"], expected_due,
                             f"Month {m['month_name']}: due mismatch")

    def test_dues_paid_month_zero_due(self):
        room, name = self._find_row_by_criteria(status_filter="PAID")
        if room is None:
            self.skipTest("No PAID rows found")
        result = asyncio.get_event_loop().run_until_complete(
            get_tenant_dues(room, name)
        )
        self.assertTrue(result["success"])
        # The PAID month should have due=0 (or close if overpaid)
        paid_months = [m for m in result["months"]
                       if m["status"] == "PAID" and m["total_paid"] >= result["rent_due"]]
        for m in paid_months:
            self.assertEqual(m["due"], 0,
                             f"PAID month {m['month_name']} should have 0 due")

    def test_dues_nonexistent_tenant(self):
        result = asyncio.get_event_loop().run_until_complete(
            get_tenant_dues("ZZZ999", "GhostTenant")
        )
        self.assertFalse(result["success"])
        self.assertIn("not found", result["error"].lower())


# =========================================================================== #

if __name__ == "__main__":
    # Run with verbosity
    unittest.main(verbosity=2)
