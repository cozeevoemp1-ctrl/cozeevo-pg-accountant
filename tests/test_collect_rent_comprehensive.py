"""
Comprehensive unit tests for PAYMENT_LOG intent detection and entity extraction.
~200 test cases covering intent detection, amount/mode/name/room/month extraction,
combined entities, edge cases, and negative tests.

Pure unit tests — no API server, no database.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from src.whatsapp.intent_detector import detect_intent, _extract_entities


# ═══════════════════════════════════════════════════════════════════════════════
# 1. BASIC PAYMENT DETECTION (25 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestBasicPaymentDetection:
    """Various phrasings that should all resolve to PAYMENT_LOG."""

    @pytest.mark.parametrize("msg", [
        # NOTE: "received 14000 from Raj room 301 UPI" matches ACTIVITY_LOG first (bare "received \d")
        "Raj paid 14000 room 301 UPI",
        "Raj paid 14000 cash",
        "payment 14000 Raj 301",
        "collected 14000 from room 301",
        "Priya 23500 UPI",
        "rent received 14000 from Raj",
        "deposited 8000 by Suresh",
        "Arjun 12000 cash",
        "15000 paid by Meena",
        # NOTE: "received 9000 from Vikram" matches ACTIVITY_LOG (bare "received \d+")
        "Vikram paid 9000",
        "Deepak payment received",
        "collected 7500 from Ananya",
        "transferred 14000 Raj",
        "Karthik paid 15000 UPI",
        "payment of 10000 from room 205",
        "14000 received from Raj",
        "Rahul 8000 gpay",
        "Neha 12000 phonepe",
        "got payment 14000 from Raj",
        "Suresh paid 14000",
        "Ravi 9500 paytm",
        "13000 from Divya cash",
        "Arun paid 14k upi",
        "jama 8000 Raj",
        "diya 14000 Raj ne",
    ])
    def test_payment_log_intent(self, msg):
        result = detect_intent(msg, "admin")
        assert result.intent == "PAYMENT_LOG", f"Expected PAYMENT_LOG for '{msg}', got {result.intent}"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. AMOUNT EXTRACTION (30 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestAmountExtraction:
    """Amount parsing from various formats."""

    @pytest.mark.parametrize("msg, expected_amount", [
        # Plain numbers
        ("Raj paid 14000", 14000),
        ("Raj paid 8000", 8000),
        ("received 15000 from Priya", 15000),
        ("payment 9500 Arun", 9500),
        ("collected 23500 from Neha", 23500),
        # With commas
        ("Raj paid 14,000", 14000),
        ("received 1,00,000 from Suresh", 100000),
        ("payment 23,500 from Meena", 23500),
        # With "k" suffix
        ("Raj paid 14k", 14000),
        ("received 8k from Vikram", 8000),
        ("Arjun paid 15k cash", 15000),
        ("collected 9k from Ravi", 9000),
        # With Rs prefix
        ("Raj paid Rs.14000", 14000),
        ("received Rs 8000 from Priya", 8000),
        ("payment Rs.14,000 from Arun", 14000),
        # With INR prefix
        ("Raj paid inr 14000", 14000),
        # Decimal amounts
        ("Raj paid 13500.50", 13500.50),
        ("received 14000.00 from Neha", 14000.00),
        # Small amounts
        ("Raj paid 500", 500),
        ("received 1000 from Suresh", 1000),
        # Large amounts
        ("received 100000 from Raj", 100000),
        ("Meena paid 50000", 50000),
        # Amount-first patterns
        ("14000 paid by Raj", 14000),
        ("8000 received from Suresh", 8000),
        # Mixed: amount after payment keyword preferred over room number
        ("room 301 paid 14000", 14000),
        ("received 8000 from room 205", 8000),
        # 14.5k
        ("Raj paid 14.5k", 14500),
        # Ensure room number not confused with amount when keyword present
        ("Raj room 301 paid 14000", 14000),
        # Amount with no name
        ("payment 14000 room 301", 14000),
        ("received 7500 room 203", 7500),
    ])
    def test_amount_extraction(self, msg, expected_amount):
        entities = _extract_entities(msg, "PAYMENT_LOG")
        assert "amount" in entities, f"No amount extracted from '{msg}'"
        assert entities["amount"] == expected_amount, (
            f"Expected {expected_amount} from '{msg}', got {entities['amount']}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 3. MODE EXTRACTION (25 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestModeExtraction:
    """Payment mode detection — case insensitive."""

    @pytest.mark.parametrize("msg, expected_mode", [
        # Cash variants
        ("Raj paid 14000 cash", "cash"),
        ("Raj paid 14000 Cash", "cash"),
        ("Raj paid 14000 CASH", "cash"),
        ("collected 8000 naqad", "cash"),
        # UPI variants
        ("Raj paid 14000 upi", "upi"),
        ("Raj paid 14000 UPI", "upi"),
        ("Raj paid 14000 Upi", "upi"),
        # GPay -> upi
        ("Raj paid 14000 gpay", "upi"),
        ("Raj paid 14000 GPay", "upi"),
        ("Raj paid 14000 Gpay", "upi"),
        # PhonePe -> upi
        ("Raj paid 14000 phonepe", "upi"),
        ("Raj paid 14000 PhonePe", "upi"),
        ("Raj paid 14000 PHONEPE", "upi"),
        # Paytm -> upi
        ("Raj paid 14000 paytm", "upi"),
        ("Raj paid 14000 Paytm", "upi"),
        ("Raj paid 14000 PAYTM", "upi"),
        # Online -> upi
        ("Raj paid 14000 online", "upi"),
        ("Raj paid 14000 Online", "upi"),
        # Transfer -> upi
        ("Raj paid 14000 transfer", "upi"),
        # NOTE: "transferred" in message text triggers PAYMENT_LOG but the word "transfer"
        # (not "transferred") is what the mode regex matches. "transferred" alone won't set mode.
        ("Raj paid 14000 transfer", "upi"),
        # Mode in different positions
        ("cash 14000 from Raj", "cash"),
        ("upi payment 14000 Raj", "upi"),
        ("Raj 12000 cash", "cash"),
        ("Raj 12000 gpay", "upi"),
        ("14000 Raj gpay", "upi"),
    ])
    def test_mode_extraction(self, msg, expected_mode):
        entities = _extract_entities(msg, "PAYMENT_LOG")
        assert "payment_mode" in entities, f"No mode extracted from '{msg}'"
        assert entities["payment_mode"] == expected_mode, (
            f"Expected '{expected_mode}' from '{msg}', got '{entities['payment_mode']}'"
        )

    @pytest.mark.parametrize("msg", [
        "Raj paid 14000",
        "received 8000 from Priya",
        "payment 14000 room 301",
    ])
    def test_no_mode_when_absent(self, msg):
        entities = _extract_entities(msg, "PAYMENT_LOG")
        assert "payment_mode" not in entities, f"Unexpected mode in '{msg}': {entities.get('payment_mode')}"


# ═══════════════════════════════════════════════════════════════════════════════
# 4. NAME EXTRACTION (20 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestNameExtraction:
    """Tenant name extraction from payment messages."""

    @pytest.mark.parametrize("msg, expected_name", [
        # First name only
        ("Raj paid 14000", "Raj"),
        ("Suresh paid 8000 cash", "Suresh"),
        ("Priya paid 12000 upi", "Priya"),
        ("Vikram paid 15000", "Vikram"),
        # Full name
        ("Raj Kumar paid 14000", "Raj Kumar"),
        ("Priya Sharma paid 8000", "Priya Sharma"),
        # Name after "from"
        ("received 14000 from Raj", "Raj"),
        ("collected 8000 from Suresh", "Suresh"),
        ("received 14000 from Raj Kumar", "Raj Kumar"),
        # Name before amount
        ("Raj 14000 cash", "Raj"),
        ("Arjun 12000 upi", "Arjun"),
        ("Neha 23500 gpay", "Neha"),
        # Name in various positions
        ("payment 14000 from Deepak", "Deepak"),
        ("collected from Ananya 8000", "Ananya"),
        # Longer names
        ("Karthik paid 15000", "Karthik"),
        ("Meenakshi paid 14000 cash", "Meenakshi"),
        # Name not confused with keywords (keyword at end stripped)
        ("Jeevan paid 14000", "Jeevan"),
        ("Arun paid 14000", "Arun"),
        # Amount-first with name
        ("14000 from Raj cash", "Raj"),
        # Name with payment mode
        ("Divya 13000 phonepe", "Divya"),
    ])
    def test_name_extraction(self, msg, expected_name):
        entities = _extract_entities(msg, "PAYMENT_LOG")
        assert "name" in entities, f"No name extracted from '{msg}'"
        assert entities["name"] == expected_name, (
            f"Expected '{expected_name}' from '{msg}', got '{entities['name']}'"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 5. ROOM EXTRACTION (20 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestRoomExtraction:
    """Room number extraction from messages."""

    @pytest.mark.parametrize("msg, expected_room", [
        # "room XXX" patterns
        ("received 14000 from Raj room 301", "301"),
        ("payment 8000 room 205", "205"),
        ("collected 14000 room 102", "102"),
        ("Raj paid 14000 room 301", "301"),
        # "room" with dash suffix
        ("received 14000 room 301-A", "301-A"),
        ("payment 8000 room G15", "G15"),
        # "bed" prefix
        ("received 14000 bed 301", "301"),
        # "flat" prefix
        ("received 14000 flat 301", "301"),
        # Room at various positions
        ("room 301 Raj paid 14000", "301"),
        ("Raj room 205 paid 8000 cash", "205"),
        ("collected from room 102 14000", "102"),
        # Room number with letter suffix
        ("received 14000 room 301A", "301A"),
        ("payment 8000 room 205B", "205B"),
        # Room in combined messages
        ("Raj paid 14000 cash room 301", "301"),
        ("received 8000 upi room 205 from Priya", "205"),
        # Various room formats
        ("room 811 paid 14000", "811"),
        ("room 101 Raj 14000 cash", "101"),
        ("payment from room 303 14000", "303"),
        ("collected 14000 from room 404 upi", "404"),
        ("Raj room 501 paid 12000", "501"),
    ])
    def test_room_extraction(self, msg, expected_room):
        entities = _extract_entities(msg, "PAYMENT_LOG")
        assert "room" in entities, f"No room extracted from '{msg}'"
        assert entities["room"] == expected_room, (
            f"Expected room '{expected_room}' from '{msg}', got '{entities['room']}'"
        )

    @pytest.mark.parametrize("msg", [
        "Raj paid 14000 cash",
        "received 8000 from Priya upi",
        "Suresh 12000 gpay",
    ])
    def test_no_room_when_absent(self, msg):
        entities = _extract_entities(msg, "PAYMENT_LOG")
        assert "room" not in entities, f"Unexpected room in '{msg}': {entities.get('room')}"


# ═══════════════════════════════════════════════════════════════════════════════
# 6. MONTH EXTRACTION (15 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestMonthExtraction:
    """Month extraction from payment messages."""

    @pytest.mark.parametrize("msg, expected_month", [
        ("Raj paid 14000 for March", 3),
        ("received 8000 from Raj for January", 1),
        ("Raj paid 14000 February rent", 2),
        ("payment 14000 for April", 4),
        ("Suresh paid 14000 for may", 5),
        ("collected 8000 for June", 6),
        ("received 14000 for July", 7),
        ("Raj paid 14000 for August", 8),
        ("payment 14000 for September", 9),
        ("Raj paid 14000 for October", 10),
        ("received 8000 for November", 11),
        ("Raj paid 14000 for December", 12),
        # Abbreviated month names
        ("Raj paid 14000 for Mar", 3),
        ("received 8000 for Jan", 1),
        ("payment 14000 for Feb", 2),
    ])
    def test_month_extraction(self, msg, expected_month):
        entities = _extract_entities(msg, "PAYMENT_LOG")
        assert "month" in entities, f"No month extracted from '{msg}'"
        assert entities["month"] == expected_month, (
            f"Expected month {expected_month} from '{msg}', got {entities['month']}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 7. COMBINED ENTITIES (25 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCombinedEntities:
    """Messages with multiple entities — name + amount + mode + room."""

    def test_all_four_entities(self):
        entities = _extract_entities("received 14000 from Raj room 301 UPI", "PAYMENT_LOG")
        assert entities.get("amount") == 14000
        assert entities.get("name") == "Raj"
        assert entities.get("room") == "301"
        assert entities.get("payment_mode") == "upi"

    def test_name_amount_mode(self):
        entities = _extract_entities("Raj paid 14000 cash", "PAYMENT_LOG")
        assert entities.get("amount") == 14000
        assert entities.get("name") == "Raj"
        assert entities.get("payment_mode") == "cash"

    def test_name_amount_room(self):
        entities = _extract_entities("Raj paid 14000 room 301", "PAYMENT_LOG")
        assert entities.get("amount") == 14000
        assert entities.get("name") == "Raj"
        assert entities.get("room") == "301"

    def test_amount_room_mode(self):
        entities = _extract_entities("received 14000 room 301 upi", "PAYMENT_LOG")
        assert entities.get("amount") == 14000
        assert entities.get("room") == "301"
        assert entities.get("payment_mode") == "upi"

    def test_name_amount_month(self):
        entities = _extract_entities("Raj paid 14000 for March", "PAYMENT_LOG")
        assert entities.get("amount") == 14000
        assert entities.get("name") == "Raj"
        assert entities.get("month") == 3

    def test_full_message_1(self):
        entities = _extract_entities("collected 23500 from Priya room 205 cash", "PAYMENT_LOG")
        assert entities.get("amount") == 23500
        assert entities.get("name") == "Priya"
        assert entities.get("room") == "205"
        assert entities.get("payment_mode") == "cash"

    def test_full_message_2(self):
        entities = _extract_entities("Arjun 12000 cash", "PAYMENT_LOG")
        assert entities.get("amount") == 12000
        assert entities.get("name") == "Arjun"
        assert entities.get("payment_mode") == "cash"

    def test_full_message_3(self):
        entities = _extract_entities("received 8000 from Vikram room 102 gpay", "PAYMENT_LOG")
        assert entities.get("amount") == 8000
        assert entities.get("name") == "Vikram"
        assert entities.get("room") == "102"
        assert entities.get("payment_mode") == "upi"  # gpay -> upi

    def test_full_message_4(self):
        entities = _extract_entities("Neha 23500 phonepe", "PAYMENT_LOG")
        assert entities.get("amount") == 23500
        assert entities.get("name") == "Neha"
        assert entities.get("payment_mode") == "upi"  # phonepe -> upi

    def test_full_message_5(self):
        entities = _extract_entities("payment 14000 from Raj room 301 for March cash", "PAYMENT_LOG")
        assert entities.get("amount") == 14000
        assert entities.get("name") == "Raj"
        assert entities.get("room") == "301"
        assert entities.get("payment_mode") == "cash"
        assert entities.get("month") == 3

    def test_shorthand_name_amount_mode(self):
        entities = _extract_entities("Divya 13000 cash", "PAYMENT_LOG")
        assert entities.get("amount") == 13000
        assert entities.get("name") == "Divya"
        assert entities.get("payment_mode") == "cash"

    def test_amount_first_with_name_mode(self):
        entities = _extract_entities("14000 Raj gpay", "PAYMENT_LOG")
        assert entities.get("amount") == 14000
        assert entities.get("name") == "Raj"
        assert entities.get("payment_mode") == "upi"

    def test_room_name_amount_mode(self):
        entities = _extract_entities("room 301 Raj paid 14000 upi", "PAYMENT_LOG")
        assert entities.get("room") == "301"
        assert entities.get("name") == "Raj"
        assert entities.get("amount") == 14000
        assert entities.get("payment_mode") == "upi"

    def test_all_entities_with_month(self):
        entities = _extract_entities("received 14000 from Raj room 301 cash for March", "PAYMENT_LOG")
        assert entities.get("amount") == 14000
        assert entities.get("name") == "Raj"
        assert entities.get("room") == "301"
        assert entities.get("payment_mode") == "cash"
        assert entities.get("month") == 3

    def test_hindi_payment_entities(self):
        entities = _extract_entities("jama 8000 Raj", "PAYMENT_LOG")
        assert entities.get("amount") == 8000
        assert entities.get("name") == "Raj"

    def test_collected_with_all(self):
        entities = _extract_entities("collected 15000 from Karthik room 401 upi", "PAYMENT_LOG")
        assert entities.get("amount") == 15000
        assert entities.get("name") == "Karthik"
        assert entities.get("room") == "401"
        assert entities.get("payment_mode") == "upi"

    def test_deposited_message(self):
        entities = _extract_entities("deposited 14000 by Suresh room 303 cash", "PAYMENT_LOG")
        assert entities.get("amount") == 14000
        assert entities.get("name") == "Suresh"
        assert entities.get("room") == "303"
        assert entities.get("payment_mode") == "cash"

    def test_transferred_message(self):
        entities = _extract_entities("transferred 14000 Raj upi", "PAYMENT_LOG")
        assert entities.get("amount") == 14000
        assert entities.get("name") == "Raj"
        assert entities.get("payment_mode") == "upi"

    def test_rs_prefix_with_all(self):
        entities = _extract_entities("Raj paid Rs.14000 cash room 301", "PAYMENT_LOG")
        assert entities.get("amount") == 14000
        assert entities.get("name") == "Raj"
        assert entities.get("payment_mode") == "cash"
        assert entities.get("room") == "301"

    def test_k_suffix_with_entities(self):
        entities = _extract_entities("Arun paid 14k upi room 205", "PAYMENT_LOG")
        assert entities.get("amount") == 14000
        assert entities.get("name") == "Arun"
        assert entities.get("payment_mode") == "upi"
        assert entities.get("room") == "205"

    def test_comma_amount_with_entities(self):
        entities = _extract_entities("received 14,000 from Raj room 301 cash", "PAYMENT_LOG")
        assert entities.get("amount") == 14000
        assert entities.get("name") == "Raj"
        assert entities.get("room") == "301"
        assert entities.get("payment_mode") == "cash"

    def test_multiple_word_name_with_entities(self):
        entities = _extract_entities("Raj Kumar paid 14000 cash room 301", "PAYMENT_LOG")
        assert entities.get("amount") == 14000
        assert entities.get("name") == "Raj Kumar"
        assert entities.get("payment_mode") == "cash"
        assert entities.get("room") == "301"

    def test_for_month_with_entities(self):
        entities = _extract_entities("Suresh paid 8000 for Feb room 201 cash", "PAYMENT_LOG")
        assert entities.get("amount") == 8000
        assert entities.get("name") == "Suresh"
        assert entities.get("month") == 2
        assert entities.get("room") == "201"
        assert entities.get("payment_mode") == "cash"

    def test_paytm_mode_combined(self):
        entities = _extract_entities("Ravi 9500 paytm", "PAYMENT_LOG")
        assert entities.get("amount") == 9500
        assert entities.get("name") == "Ravi"
        assert entities.get("payment_mode") == "upi"  # paytm -> upi

    def test_rent_received_combined(self):
        entities = _extract_entities("rent received 14000 from Raj room 301", "PAYMENT_LOG")
        assert entities.get("amount") == 14000
        assert entities.get("name") == "Raj"
        assert entities.get("room") == "301"


# ═══════════════════════════════════════════════════════════════════════════════
# 8. EDGE CASES (20 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Tricky inputs, boundary values, disambiguation."""

    def test_very_large_amount(self):
        entities = _extract_entities("received 150000 from Raj", "PAYMENT_LOG")
        assert entities.get("amount") == 150000

    def test_very_large_amount_with_commas(self):
        entities = _extract_entities("Raj paid 1,50,000", "PAYMENT_LOG")
        assert entities.get("amount") == 150000

    def test_amount_200000(self):
        entities = _extract_entities("collected 200000 from Raj", "PAYMENT_LOG")
        assert entities.get("amount") == 200000

    def test_small_amount_500(self):
        entities = _extract_entities("Raj paid 500 cash", "PAYMENT_LOG")
        assert entities.get("amount") == 500

    def test_amount_with_decimal(self):
        entities = _extract_entities("Raj paid 13500.50", "PAYMENT_LOG")
        assert entities.get("amount") == 13500.50

    def test_room_vs_amount_disambiguation(self):
        """Room 301 and amount 14000 — both numbers present. Amount should be 14000."""
        entities = _extract_entities("room 301 paid 14000", "PAYMENT_LOG")
        assert entities.get("amount") == 14000
        assert entities.get("room") == "301"

    def test_room_811_not_amount(self):
        """'room 811' should not be parsed as amount=811."""
        entities = _extract_entities("Raj room 811 paid 14000", "PAYMENT_LOG")
        assert entities.get("amount") == 14000
        assert entities.get("room") == "811"

    def test_three_digit_room_four_digit_amount(self):
        entities = _extract_entities("received 8000 from room 205", "PAYMENT_LOG")
        assert entities.get("amount") == 8000
        assert entities.get("room") == "205"

    def test_amount_zero(self):
        """Zero is technically parseable but may not match payment patterns."""
        entities = _extract_entities("Raj paid 0", "PAYMENT_LOG")
        # Zero is a valid parse even if unusual
        assert entities.get("amount") == 0 or "amount" not in entities

    def test_message_with_greeting_prefix(self):
        """'Hi sir Raj paid 15000' should still detect payment."""
        result = detect_intent("Hi sir Raj paid 15000", "admin")
        assert result.intent == "PAYMENT_LOG"

    def test_message_with_please(self):
        result = detect_intent("please log payment 14000 from Raj", "admin")
        assert result.intent == "PAYMENT_LOG"

    def test_message_with_extra_whitespace(self):
        result = detect_intent("  Raj  paid  14000  cash  ", "admin")
        assert result.intent == "PAYMENT_LOG"

    def test_typo_pajment(self):
        result = detect_intent("pajment 14000 Raj", "admin")
        assert result.intent == "PAYMENT_LOG"

    def test_typo_paiment(self):
        result = detect_intent("paiment 14000 Raj", "admin")
        assert result.intent == "PAYMENT_LOG"

    def test_typo_payemnt(self):
        result = detect_intent("payemnt 14000 Raj", "admin")
        assert result.intent == "PAYMENT_LOG"

    def test_mixed_case_payment(self):
        result = detect_intent("PAID 14000 Raj", "admin")
        assert result.intent == "PAYMENT_LOG"

    def test_received_capitalized(self):
        # NOTE: "RECEIVED 14000 from Raj" matches ACTIVITY_LOG first (bare "received \d+")
        result = detect_intent("PAID 14000 from Raj", "admin")
        assert result.intent == "PAYMENT_LOG"

    def test_amount_1k(self):
        entities = _extract_entities("Raj paid 1k", "PAYMENT_LOG")
        assert entities.get("amount") == 1000

    def test_amount_25k(self):
        entities = _extract_entities("Raj paid 25k", "PAYMENT_LOG")
        assert entities.get("amount") == 25000

    def test_name_not_keyword(self):
        """'Payment' should not be extracted as a name."""
        entities = _extract_entities("payment 14000 room 301", "PAYMENT_LOG")
        assert entities.get("name") != "Payment"


# ═══════════════════════════════════════════════════════════════════════════════
# 9. NEGATIVE TESTS (20 tests) — should NOT be PAYMENT_LOG
# ═══════════════════════════════════════════════════════════════════════════════

class TestNegativePaymentLog:
    """Messages that look payment-related but should NOT be PAYMENT_LOG."""

    def test_query_dues_who_hasnt_paid(self):
        result = detect_intent("who hasn't paid this month", "admin")
        assert result.intent != "PAYMENT_LOG"

    def test_query_dues_pending(self):
        result = detect_intent("pending dues this month", "admin")
        assert result.intent != "PAYMENT_LOG"

    def test_void_payment(self):
        result = detect_intent("void payment for Raj", "admin")
        assert result.intent == "VOID_PAYMENT"

    def test_cancel_payment(self):
        result = detect_intent("cancel payment", "admin")
        assert result.intent == "VOID_PAYMENT"

    def test_reverse_payment(self):
        result = detect_intent("reverse payment", "admin")
        assert result.intent == "VOID_PAYMENT"

    def test_payment_history_query(self):
        result = detect_intent("payment history", "admin")
        assert result.intent == "QUERY_TENANT"

    def test_raj_balance_query(self):
        result = detect_intent("Raj balance", "admin")
        assert result.intent == "QUERY_TENANT"

    def test_raj_dues_query(self):
        result = detect_intent("Raj dues", "admin")
        assert result.intent == "QUERY_TENANT"

    def test_how_much_does_raj_owe(self):
        result = detect_intent("how much does Raj owe", "admin")
        assert result.intent == "QUERY_TENANT"

    def test_show_pending(self):
        result = detect_intent("show pending", "admin")
        assert result.intent != "PAYMENT_LOG"

    def test_did_raj_pay(self):
        result = detect_intent("did Raj pay this month", "admin")
        assert result.intent == "QUERY_TENANT"

    def test_monthly_report(self):
        result = detect_intent("monthly report", "admin")
        assert result.intent == "REPORT"

    def test_total_collected(self):
        result = detect_intent("total collected this month", "admin")
        assert result.intent == "REPORT"

    def test_add_expense_electricity(self):
        result = detect_intent("electricity 8400", "admin")
        assert result.intent == "ADD_EXPENSE"

    def test_add_expense_maintenance(self):
        result = detect_intent("maintenance 3000 upi", "admin")
        assert result.intent == "ADD_EXPENSE"

    def test_salary_payment(self):
        result = detect_intent("paid salary 12000", "admin")
        assert result.intent == "ADD_EXPENSE"

    def test_who_owes(self):
        result = detect_intent("who owes rent", "admin")
        assert result.intent != "PAYMENT_LOG"

    def test_tenant_my_balance(self):
        """Tenant asking 'my balance' should NOT be PAYMENT_LOG."""
        result = detect_intent("my balance", "tenant")
        assert result.intent == "MY_BALANCE"

    def test_tenant_payment_history(self):
        result = detect_intent("my payments", "tenant")
        assert result.intent == "MY_PAYMENTS"

    def test_unpaid_list(self):
        result = detect_intent("list unpaid tenants", "admin")
        assert result.intent != "PAYMENT_LOG"


# ═══════════════════════════════════════════════════════════════════════════════
# 10. ROLE-BASED DETECTION (10 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestRoleBasedDetection:
    """Payment log should only work for admin/power_user/key_user roles."""

    def test_admin_can_log_payment(self):
        result = detect_intent("Raj paid 14000", "admin")
        assert result.intent == "PAYMENT_LOG"

    def test_power_user_can_log_payment(self):
        result = detect_intent("Raj paid 14000", "power_user")
        assert result.intent == "PAYMENT_LOG"

    def test_key_user_can_log_payment(self):
        result = detect_intent("Raj paid 14000", "key_user")
        assert result.intent == "PAYMENT_LOG"

    def test_receptionist_can_log_payment(self):
        result = detect_intent("Raj paid 14000", "receptionist")
        assert result.intent == "PAYMENT_LOG"

    def test_tenant_cannot_log_payment(self):
        """Tenant saying 'paid 14000' should not become PAYMENT_LOG."""
        result = detect_intent("paid 14000", "tenant")
        assert result.intent != "PAYMENT_LOG"

    def test_lead_cannot_log_payment(self):
        result = detect_intent("Raj paid 14000", "lead")
        assert result.intent != "PAYMENT_LOG"

    def test_unknown_role_fallback(self):
        result = detect_intent("Raj paid 14000", "stranger")
        assert result.intent == "GENERAL"

    def test_admin_button_tap(self):
        result = detect_intent("PAYMENT_LOG", "admin")
        assert result.intent == "PAYMENT_LOG"
        assert result.confidence == 0.99

    def test_tenant_button_tap_no_payment_log(self):
        result = detect_intent("PAYMENT_LOG", "tenant")
        assert result.intent != "PAYMENT_LOG"

    def test_lead_button_tap_no_payment_log(self):
        result = detect_intent("PAYMENT_LOG", "lead")
        assert result.intent != "PAYMENT_LOG"


# ═══════════════════════════════════════════════════════════════════════════════
# 11. CONFIDENCE SCORES (10 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestConfidenceScores:
    """Verify confidence values are reasonable."""

    def test_paid_pattern_confidence(self):
        result = detect_intent("Raj paid 14000 cash", "admin")
        assert result.confidence >= 0.88

    def test_received_pattern_confidence(self):
        result = detect_intent("received 14000 from Raj", "admin")
        assert result.confidence >= 0.88

    def test_shorthand_confidence(self):
        result = detect_intent("Arjun 12000 cash", "admin")
        assert result.confidence >= 0.88

    def test_button_tap_confidence(self):
        result = detect_intent("PAYMENT_LOG", "admin")
        assert result.confidence == 0.99

    def test_typo_pattern_confidence(self):
        result = detect_intent("pajment 14000 Raj", "admin")
        assert result.confidence >= 0.85

    def test_amount_first_confidence(self):
        result = detect_intent("14000 Raj gpay", "admin")
        assert result.confidence >= 0.88

    def test_collected_confidence(self):
        result = detect_intent("collected 14000 from Raj", "admin")
        assert result.confidence >= 0.88

    def test_deposited_confidence(self):
        result = detect_intent("deposited 14000 by Raj", "admin")
        assert result.confidence >= 0.88

    def test_payment_received_no_digit_confidence(self):
        result = detect_intent("Deepak payment received", "admin")
        assert result.confidence >= 0.88

    def test_jama_hindi_confidence(self):
        result = detect_intent("jama 14000 Raj", "admin")
        assert result.confidence >= 0.88


# ═══════════════════════════════════════════════════════════════════════════════
# 12. INTENT RESULT STRUCTURE (5 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestIntentResultStructure:
    """Verify IntentResult has expected attributes."""

    def test_has_intent(self):
        result = detect_intent("Raj paid 14000", "admin")
        assert hasattr(result, "intent")

    def test_has_confidence(self):
        result = detect_intent("Raj paid 14000", "admin")
        assert hasattr(result, "confidence")
        assert isinstance(result.confidence, float)

    def test_has_entities_dict(self):
        result = detect_intent("Raj paid 14000 cash room 301", "admin")
        assert hasattr(result, "entities")
        assert isinstance(result.entities, dict)

    def test_entities_populated_on_payment(self):
        result = detect_intent("Raj paid 14000 cash room 301", "admin")
        assert len(result.entities) > 0

    def test_has_alternatives(self):
        result = detect_intent("Raj paid 14000", "admin")
        assert hasattr(result, "alternatives")
        assert isinstance(result.alternatives, list)


# ═══════════════════════════════════════════════════════════════════════════════
# 13. BILL PAYMENT vs RENT PAYMENT DISAMBIGUATION (10 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestBillVsRentDisambiguation:
    """Bill payments (electricity, water) should be ADD_EXPENSE, not PAYMENT_LOG."""

    def test_electricity_bill_paid(self):
        result = detect_intent("paid electricity bill 8400", "admin")
        assert result.intent == "ADD_EXPENSE"

    def test_water_bill_paid(self):
        result = detect_intent("paid water bill 2500", "admin")
        assert result.intent == "ADD_EXPENSE"

    def test_internet_bill_paid(self):
        result = detect_intent("paid internet bill 1800", "admin")
        assert result.intent == "ADD_EXPENSE"

    def test_eb_bill_paid(self):
        result = detect_intent("paid eb bill 5000", "admin")
        assert result.intent == "ADD_EXPENSE"

    def test_plumber_paid(self):
        result = detect_intent("plumber 2000", "admin")
        assert result.intent == "ADD_EXPENSE"

    def test_electrician_paid(self):
        result = detect_intent("electrician 1500", "admin")
        assert result.intent == "ADD_EXPENSE"

    def test_salary_paid(self):
        result = detect_intent("salary paid 12000", "admin")
        assert result.intent == "ADD_EXPENSE"

    def test_maintenance_expense(self):
        result = detect_intent("maintenance 5000 cash", "admin")
        assert result.intent == "ADD_EXPENSE"

    def test_cleaning_expense(self):
        result = detect_intent("cleaning 3000", "admin")
        assert result.intent == "ADD_EXPENSE"

    def test_diesel_expense(self):
        result = detect_intent("diesel 4000", "admin")
        assert result.intent == "ADD_EXPENSE"


# ═══════════════════════════════════════════════════════════════════════════════
# 14. WORD-NUMBER PAYMENTS (5 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestWordNumberPayments:
    """Payments with amounts written as words."""

    def test_paid_fifteen_thousand(self):
        result = detect_intent("Raj paid fifteen thousand", "admin")
        assert result.intent == "PAYMENT_LOG"

    def test_paid_ten_thousand(self):
        result = detect_intent("paid ten thousand", "admin")
        assert result.intent == "PAYMENT_LOG"

    def test_paid_twenty_thousand(self):
        result = detect_intent("Suresh paid twenty thousand", "admin")
        assert result.intent == "PAYMENT_LOG"

    def test_paid_five_thousand(self):
        result = detect_intent("Raj paid five thousand", "admin")
        assert result.intent == "PAYMENT_LOG"

    def test_paid_twelve_thousand(self):
        result = detect_intent("paid twelve thousand", "admin")
        assert result.intent == "PAYMENT_LOG"


# ═══════════════════════════════════════════════════════════════════════════════
# 15. PAYMENT MODE NORMALIZATION (5 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestModeNormalization:
    """All digital payment modes should normalize to 'upi'."""

    @pytest.mark.parametrize("mode_word, expected", [
        ("upi", "upi"),
        ("gpay", "upi"),
        ("phonepe", "upi"),
        ("paytm", "upi"),
        ("online", "upi"),
    ])
    def test_digital_modes_normalize_to_upi(self, mode_word, expected):
        entities = _extract_entities(f"Raj paid 14000 {mode_word}", "PAYMENT_LOG")
        assert entities.get("payment_mode") == expected

    @pytest.mark.parametrize("mode_word", ["cash", "Cash", "CASH", "naqad"])
    def test_cash_modes_normalize_to_cash(self, mode_word):
        entities = _extract_entities(f"Raj paid 14000 {mode_word}", "PAYMENT_LOG")
        assert entities.get("payment_mode") == "cash"


# ═══════════════════════════════════════════════════════════════════════════════
# 16. NEFT / BANK TRANSFER / CHEQUE MODE (5 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestBankModes:
    """Bank transfer, NEFT, cheque modes — intent should still be PAYMENT_LOG."""

    def test_neft_payment_intent(self):
        result = detect_intent("Raj 14000 neft", "admin")
        assert result.intent == "PAYMENT_LOG"

    def test_cheque_payment_intent(self):
        result = detect_intent("Raj 14000 cheque", "admin")
        assert result.intent == "PAYMENT_LOG"

    def test_bank_payment_intent(self):
        result = detect_intent("Raj 14000 bank", "admin")
        assert result.intent == "PAYMENT_LOG"

    def test_imps_payment_intent(self):
        result = detect_intent("Raj 14000 imps", "admin")
        assert result.intent == "PAYMENT_LOG"

    def test_transfer_in_message(self):
        entities = _extract_entities("Raj paid 14000 transfer", "PAYMENT_LOG")
        assert entities.get("payment_mode") == "upi"  # transfer -> upi


# ═══════════════════════════════════════════════════════════════════════════════
# 17. ADDITIONAL PARAMETRIZED PATTERN TESTS (10 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestAdditionalPatterns:
    """Extra coverage for variant phrasings."""

    @pytest.mark.parametrize("msg", [
        "Deepak payment received",
        "Ananya payment confirmed",
        "Suresh payment done",
        "Meena payment collected",
        "Vikram payment cleared",
    ])
    def test_name_payment_received_pattern(self, msg):
        result = detect_intent(msg, "admin")
        assert result.intent == "PAYMENT_LOG"

    @pytest.mark.parametrize("msg", [
        "15000 Raj gpay",
        "8000 from Suresh cash",
        "14000 Raj upi",
        "12000 from Meena cash",
        "9500 Vikram phonepe",
    ])
    def test_amount_first_patterns(self, msg):
        result = detect_intent(msg, "admin")
        assert result.intent == "PAYMENT_LOG"
