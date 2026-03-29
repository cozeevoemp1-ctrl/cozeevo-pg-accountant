"""
Comprehensive unit tests for notice flow:
  - Intent detection (NOTICE_GIVEN)
  - Date entity extraction
  - calc_notice_last_day logic
  - Deposit eligibility
  - Future month notice references
  - Edge cases (leap year, year boundary, etc.)

~100 tests total.  Pure unit tests — no DB, no HTTP.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from datetime import date
from src.whatsapp.intent_detector import detect_intent, _extract_entities, _extract_date_entity
from services.property_logic import calc_notice_last_day, is_deposit_eligible, NOTICE_BY_DAY


# ============================================================================
# 1. NOTICE INTENT DETECTION (20 tests)
# ============================================================================

class TestNoticeIntentDetection:
    """Various phrasings should map to NOTICE_GIVEN."""

    @pytest.mark.parametrize("msg", [
        "Raj gave notice",
        "gave notice for room 203",
        "Raj is giving notice",
        "giving notice for Priya",
        "serving notice period",
        "Arjun serving notice",
        "notice period started for Raj",
        "Deepak notice",
        "notice for room 305",
        "Raj plans to leave",
        "Kiran plans to vacate",
        "he wants to leave",
        "she wants to move",
        "Sunil wants to leave end of month",
        "gave notice on 3rd Feb",
        "notice given by Priya on 1st March",
        "Amit serving notice from today",
        "room 203 gave notice",
        "tenant in 305 wants to leave",
    ])
    def test_notice_intent_detected(self, msg):
        result = detect_intent(msg, "admin")
        assert result.intent == "NOTICE_GIVEN", (
            f"Expected NOTICE_GIVEN for '{msg}', got {result.intent}"
        )

    @pytest.mark.parametrize("msg,expected_not", [
        ("Raj paid 15000", "NOTICE_GIVEN"),
        ("monthly report", "NOTICE_GIVEN"),
        ("add tenant Raj", "NOTICE_GIVEN"),
        ("who hasn't paid", "NOTICE_GIVEN"),
        ("Raj balance", "NOTICE_GIVEN"),
    ])
    def test_non_notice_messages(self, msg, expected_not):
        result = detect_intent(msg, "admin")
        assert result.intent != expected_not, (
            f"'{msg}' should NOT be {expected_not}, got {result.intent}"
        )


# ============================================================================
# 2. NOTICE DATE EXTRACTION (20 tests)
# ============================================================================

class TestNoticeDateExtraction:
    """_extract_date_entity should parse dates from various formats."""

    @pytest.mark.parametrize("text,expected", [
        ("gave notice on 5 March", "2026-03-05"),
        ("notice on 5th March", "2026-03-05"),
        ("notice on 15 Feb", "2026-02-15"),
        ("notice on 1st January", "2026-01-01"),
        ("notice on 31 December", "2026-12-31"),
        ("gave notice on 20th April 2026", "2026-04-20"),
        ("notice March 5", "2026-03-05"),
        ("notice Feb 15th", "2026-02-15"),
        ("notice January 1st", "2026-01-01"),
        ("notice December 31st", "2026-12-31"),
    ])
    def test_date_month_name_formats(self, text, expected):
        result = _extract_date_entity(text)
        assert result == expected, f"For '{text}': expected {expected}, got {result}"

    @pytest.mark.parametrize("text,expected", [
        ("notice on 05/03/2026", "2026-03-05"),
        ("notice on 15/02/2026", "2026-02-15"),
        ("notice on 01/01/2026", "2026-01-01"),
        ("notice on 31/12/2026", "2026-12-31"),
        ("notice on 5.03.2026", "2026-03-05"),
        ("notice on 5-03-2026", "2026-03-05"),
    ])
    def test_date_numeric_formats(self, text, expected):
        result = _extract_date_entity(text)
        assert result == expected, f"For '{text}': expected {expected}, got {result}"

    @pytest.mark.parametrize("text,expected", [
        ("notice on 05/03/26", "2026-03-05"),
        ("notice on 15/02/26", "2026-02-15"),
    ])
    def test_date_two_digit_year(self, text, expected):
        result = _extract_date_entity(text)
        assert result == expected, f"For '{text}': expected {expected}, got {result}"

    def test_no_date_returns_none(self):
        assert _extract_date_entity("gave notice") is None

    def test_no_date_plain_text(self):
        assert _extract_date_entity("hello world") is None


# ============================================================================
# 3. calc_notice_last_day LOGIC (25 tests)
# ============================================================================

class TestCalcNoticeLastDay:
    """Core business logic: on/before 5th = end of this month, after 5th = end of next month."""

    # -- On or before the 5th: last day = end of same month --

    @pytest.mark.parametrize("notice_date,expected_last_day", [
        (date(2026, 3, 1), date(2026, 3, 31)),   # 1st March
        (date(2026, 3, 2), date(2026, 3, 31)),   # 2nd March
        (date(2026, 3, 3), date(2026, 3, 31)),   # 3rd March
        (date(2026, 3, 4), date(2026, 3, 31)),   # 4th March
        (date(2026, 3, 5), date(2026, 3, 31)),   # 5th March (boundary)
    ])
    def test_on_or_before_5th_same_month(self, notice_date, expected_last_day):
        assert calc_notice_last_day(notice_date) == expected_last_day

    # -- After the 5th: last day = end of NEXT month --

    @pytest.mark.parametrize("notice_date,expected_last_day", [
        (date(2026, 3, 6), date(2026, 4, 30)),   # 6th March (just past boundary)
        (date(2026, 3, 7), date(2026, 4, 30)),   # 7th March
        (date(2026, 3, 10), date(2026, 4, 30)),  # 10th March
        (date(2026, 3, 15), date(2026, 4, 30)),  # mid-month
        (date(2026, 3, 20), date(2026, 4, 30)),  # 20th
        (date(2026, 3, 28), date(2026, 4, 30)),  # 28th
        (date(2026, 3, 31), date(2026, 4, 30)),  # last day of March
    ])
    def test_after_5th_next_month(self, notice_date, expected_last_day):
        assert calc_notice_last_day(notice_date) == expected_last_day

    # -- Every month of the year (notice on 1st = end of same month) --

    @pytest.mark.parametrize("month,last_day_of_month", [
        (1, 31), (2, 28), (3, 31), (4, 30), (5, 31), (6, 30),
        (7, 31), (8, 31), (9, 30), (10, 31), (11, 30), (12, 31),
    ])
    def test_1st_of_each_month_2026(self, month, last_day_of_month):
        notice = date(2026, month, 1)
        expected = date(2026, month, last_day_of_month)
        assert calc_notice_last_day(notice) == expected

    # -- December → January year rollover --

    def test_december_6th_rolls_to_january_next_year(self):
        assert calc_notice_last_day(date(2026, 12, 6)) == date(2027, 1, 31)

    def test_december_15th_rolls_to_january_next_year(self):
        assert calc_notice_last_day(date(2026, 12, 15)) == date(2027, 1, 31)

    def test_december_31st_rolls_to_january_next_year(self):
        assert calc_notice_last_day(date(2026, 12, 31)) == date(2027, 1, 31)

    def test_december_5th_stays_in_december(self):
        assert calc_notice_last_day(date(2026, 12, 5)) == date(2026, 12, 31)

    # -- February edge cases --

    def test_february_non_leap_28_days(self):
        # 2026 is not a leap year
        assert calc_notice_last_day(date(2026, 2, 3)) == date(2026, 2, 28)

    def test_february_leap_year_29_days(self):
        # 2028 is a leap year
        assert calc_notice_last_day(date(2028, 2, 3)) == date(2028, 2, 29)

    def test_january_late_notice_ends_in_feb_non_leap(self):
        # Jan 6 2026 → end of Feb 2026 (28 days, not leap)
        assert calc_notice_last_day(date(2026, 1, 6)) == date(2026, 2, 28)

    def test_january_late_notice_ends_in_feb_leap(self):
        # Jan 6 2028 → end of Feb 2028 (29 days, leap)
        assert calc_notice_last_day(date(2028, 1, 6)) == date(2028, 2, 29)


# ============================================================================
# 4. DEPOSIT ELIGIBILITY (15 tests)
# ============================================================================

class TestDepositEligibility:
    """Notice on/before 5th = deposit eligible; after 5th = forfeited."""

    @pytest.mark.parametrize("day,eligible", [
        (1, True),
        (2, True),
        (3, True),
        (4, True),
        (5, True),    # boundary — still eligible
        (6, False),   # boundary — forfeited
        (7, False),
        (10, False),
        (15, False),
        (20, False),
        (25, False),
        (28, False),
    ])
    def test_deposit_eligibility_by_day(self, day, eligible):
        notice = date(2026, 3, day)
        assert is_deposit_eligible(notice) == eligible

    def test_deposit_eligible_1st_of_month(self):
        assert is_deposit_eligible(date(2026, 1, 1)) is True

    def test_deposit_forfeited_last_day_of_month(self):
        assert is_deposit_eligible(date(2026, 3, 31)) is False

    def test_deposit_eligible_5th_december(self):
        assert is_deposit_eligible(date(2026, 12, 5)) is True


# ============================================================================
# 5. FUTURE MONTH NOTICE REFERENCES (10 tests)
# ============================================================================

class TestFutureMonthNotice:
    """Messages referencing future exit months should still detect NOTICE_GIVEN."""

    @pytest.mark.parametrize("msg", [
        "Raj wants to leave in June",
        "Priya plans to vacate in April",
        "Sunil wants to move next month",
        "Amit plans to leave end of next month",
        "Deepak wants to leave by May",
    ])
    def test_future_exit_detected_as_notice(self, msg):
        result = detect_intent(msg, "admin")
        assert result.intent == "NOTICE_GIVEN", (
            f"Expected NOTICE_GIVEN for '{msg}', got {result.intent}"
        )

    @pytest.mark.parametrize("msg,expected_month", [
        ("Raj wants to leave in June", 6),
        ("Priya plans to vacate in April", 4),
        ("leaving in December", 12),
        ("exit in January", 1),
        ("wants to leave in May", 5),
    ])
    def test_future_month_extracted(self, msg, expected_month):
        entities = _extract_entities(msg, "NOTICE_GIVEN")
        assert entities.get("month") == expected_month, (
            f"Expected month={expected_month} for '{msg}', got {entities.get('month')}"
        )


# ============================================================================
# 6. EDGE CASES (10 tests)
# ============================================================================

class TestNoticeEdgeCases:
    """Boundary and unusual scenarios."""

    def test_notice_by_day_constant_is_5(self):
        assert NOTICE_BY_DAY == 5

    def test_calc_with_custom_notice_by_day(self):
        # If policy changes to 10th
        assert calc_notice_last_day(date(2026, 3, 10), notice_by_day=10) == date(2026, 3, 31)
        assert calc_notice_last_day(date(2026, 3, 11), notice_by_day=10) == date(2026, 4, 30)

    def test_deposit_with_custom_notice_by_day(self):
        assert is_deposit_eligible(date(2026, 3, 10), notice_by_day=10) is True
        assert is_deposit_eligible(date(2026, 3, 11), notice_by_day=10) is False

    def test_notice_on_feb_28_non_leap(self):
        # Feb 28 is after the 5th → next month (March 31)
        assert calc_notice_last_day(date(2026, 2, 28)) == date(2026, 3, 31)

    def test_notice_on_feb_29_leap_year(self):
        # Feb 29 2028 is after the 5th → next month (March 31)
        assert calc_notice_last_day(date(2028, 2, 29)) == date(2028, 3, 31)

    def test_notice_on_last_day_of_30_day_month(self):
        # April 30 → end of May
        assert calc_notice_last_day(date(2026, 4, 30)) == date(2026, 5, 31)

    def test_notice_on_last_day_of_31_day_month(self):
        # January 31 → end of February (28 in 2026)
        assert calc_notice_last_day(date(2026, 1, 31)) == date(2026, 2, 28)

    def test_year_boundary_dec_to_jan(self):
        # December 20 → end of January next year
        result = calc_notice_last_day(date(2025, 12, 20))
        assert result == date(2026, 1, 31)

    def test_entity_extraction_name_from_notice(self):
        entities = _extract_entities("Raj gave notice", "NOTICE_GIVEN")
        assert entities.get("name") == "Raj"

    def test_entity_extraction_room_from_notice(self):
        entities = _extract_entities("room 203 gave notice", "NOTICE_GIVEN")
        assert entities.get("room") == "203"


# ============================================================================
# Run with: pytest tests/test_notice_comprehensive.py -v
# ============================================================================
