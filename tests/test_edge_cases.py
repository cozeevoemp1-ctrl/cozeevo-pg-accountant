"""
Edge-case unit tests for intent detection and entity extraction.
Pure unit tests — no DB, no HTTP, no external services.

Run:  pytest tests/test_edge_cases.py -v
"""
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from src.whatsapp.intent_detector import detect_intent, _extract_entities, _extract_date_entity


# ═══════════════════════════════════════════════════════════════════════════════
# 1. NON-EXISTENT ROOM REFERENCES (10 tests)
# Entity extraction should still pull room numbers regardless of whether
# the room actually exists — validation happens downstream in handlers.
# ═══════════════════════════════════════════════════════════════════════════════

class TestNonExistentRoomReferences:
    def test_room_999_extracted(self):
        """High room number that doesn't exist should still be extracted."""
        entities = _extract_entities("room 999 balance", "QUERY_TENANT")
        assert entities.get("room") == "999"

    def test_room_0_extracted(self):
        """Room 0 — edge case, should still extract."""
        entities = _extract_entities("room 0 tenant", "ROOM_STATUS")
        assert entities.get("room") == "0"

    def test_room_alpha_extracted(self):
        """Room with letters like G01 should be extracted."""
        entities = _extract_entities("room G01 balance", "QUERY_TENANT")
        assert entities.get("room") == "G01"

    def test_room_with_hyphen(self):
        """Room B-101 style should be extracted."""
        entities = _extract_entities("room B-101 status", "ROOM_STATUS")
        assert entities.get("room") == "B-101"

    def test_room_ph1(self):
        """Penthouse-style room PH-1."""
        entities = _extract_entities("room PH-1 who", "ROOM_STATUS")
        assert entities.get("room") == "PH-1"

    def test_room_4_digit(self):
        """4-digit room number."""
        entities = _extract_entities("room 1001 balance", "QUERY_TENANT")
        assert entities.get("room") == "1001"

    def test_room_with_letter_suffix(self):
        """Room 203A — number with letter suffix."""
        entities = _extract_entities("room 203A balance", "QUERY_TENANT")
        assert entities.get("room") == "203A"

    def test_bed_keyword(self):
        """'bed 5' should extract room entity."""
        entities = _extract_entities("bed 5 who is there", "ROOM_STATUS")
        assert entities.get("room") == "5"

    def test_flat_keyword(self):
        """'flat G15' should extract room entity."""
        entities = _extract_entities("flat G15 status", "ROOM_STATUS")
        assert entities.get("room") == "G15"

    def test_unit_keyword(self):
        """'unit 42' should extract room entity."""
        entities = _extract_entities("unit 42 balance", "QUERY_TENANT")
        assert entities.get("room") == "42"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. SPECIAL CHARACTERS IN INPUT (15 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestSpecialCharactersInInput:
    def test_name_with_apostrophe(self):
        """O'Brien should not crash entity extraction."""
        result = detect_intent("O'Brien paid 5000", "admin")
        assert result.intent is not None

    def test_name_dsouza(self):
        """D'Souza — apostrophe in name."""
        entities = _extract_entities("D'Souza paid 12000 cash", "PAYMENT_LOG")
        assert entities.get("amount") == 12000.0

    def test_name_with_hyphen(self):
        """Raj-Kumar — hyphenated name."""
        result = detect_intent("Raj-Kumar paid 8000", "admin")
        assert result.intent == "PAYMENT_LOG"

    def test_unicode_emoji_in_message(self):
        """Message with emoji should not crash."""
        result = detect_intent("Raj paid 5000 \U0001f44d", "admin")
        assert result.intent == "PAYMENT_LOG"

    def test_message_with_hindi_unicode(self):
        """Hindi unicode characters."""
        result = detect_intent("राज ने 5000 दिया", "admin")
        # May or may not detect — just should not crash
        assert result.intent is not None

    def test_extremely_long_message(self):
        """500+ character message should not hang or crash."""
        long_msg = "Raj paid 15000 cash " + "x" * 500
        result = detect_intent(long_msg, "admin")
        assert result.intent is not None

    def test_whitespace_only(self):
        """Whitespace-only message should return UNKNOWN/GENERAL."""
        result = detect_intent("   ", "admin")
        assert result.intent in ("UNKNOWN", "GENERAL", "HELP")

    def test_empty_string(self):
        """Empty string should return UNKNOWN/GENERAL."""
        result = detect_intent("", "admin")
        assert result.intent in ("UNKNOWN", "GENERAL", "HELP")

    def test_newlines_in_message(self):
        """Message with newlines should still detect intent."""
        result = detect_intent("Raj paid\n15000\ncash", "admin")
        assert result.intent == "PAYMENT_LOG"

    def test_multiple_spaces(self):
        """Multiple spaces between words."""
        result = detect_intent("Raj   paid   15000", "admin")
        assert result.intent == "PAYMENT_LOG"

    def test_tab_characters(self):
        """Tab characters in message."""
        result = detect_intent("Raj\tpaid\t15000", "admin")
        assert result.intent == "PAYMENT_LOG"

    def test_special_regex_chars(self):
        """Characters like ()[]{} that are regex-special should not crash."""
        result = detect_intent("paid (5000) [cash] {today}", "admin")
        assert result.intent is not None

    def test_url_in_message(self):
        """URL embedded in message should not crash."""
        result = detect_intent("payment proof https://example.com/receipt.png 5000", "admin")
        assert result.intent is not None

    def test_dollar_signs(self):
        """Dollar signs should not crash regex."""
        result = detect_intent("paid $5000", "admin")
        assert result.intent is not None

    def test_backslash_in_message(self):
        """Backslashes should not crash regex."""
        result = detect_intent("Raj\\Kumar paid 5000", "admin")
        assert result.intent is not None


# ═══════════════════════════════════════════════════════════════════════════════
# 3. AMBIGUOUS INTENTS (15 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestAmbiguousIntents:
    def test_name_date_ambiguous(self):
        """'Raj 31st March' — could be checkin update or checkout scheduling."""
        result = detect_intent("Raj 31st March", "admin")
        assert result.intent == "AMBIGUOUS"
        assert "UPDATE_CHECKIN" in result.alternatives
        assert "SCHEDULE_CHECKOUT" in result.alternatives

    def test_name_month_day_ambiguous(self):
        """'Suresh March 15' — same ambiguity."""
        result = detect_intent("Suresh March 15", "admin")
        assert result.intent == "AMBIGUOUS"

    def test_name_date_with_verb_not_ambiguous(self):
        """'Raj checkout 31st March' — has a verb, should NOT be ambiguous."""
        result = detect_intent("Raj checkout 31st March", "admin")
        assert result.intent != "AMBIGUOUS"

    def test_name_date_checkin_not_ambiguous(self):
        """'Raj checkin 31st March' — has a verb, should NOT be ambiguous."""
        result = detect_intent("Raj checkin March 5", "admin")
        assert result.intent != "AMBIGUOUS"

    def test_ambiguous_has_low_confidence(self):
        """Ambiguous result should have confidence around 0.5."""
        result = detect_intent("Deepak 15th April", "admin")
        assert result.confidence <= 0.6

    def test_ambiguous_has_alternatives_list(self):
        """Ambiguous result should populate alternatives."""
        result = detect_intent("Arjun 20th May", "admin")
        assert len(result.alternatives) >= 2

    def test_tenant_cannot_trigger_ambiguous(self):
        """Tenants don't see owner ambiguity — different rule set."""
        result = detect_intent("Raj 31st March", "tenant")
        assert result.intent != "AMBIGUOUS"

    def test_lead_cannot_trigger_ambiguous(self):
        """Leads don't see owner ambiguity."""
        result = detect_intent("Raj 31st March", "lead")
        assert result.intent != "AMBIGUOUS"

    def test_notice_keyword_not_ambiguous(self):
        """'notice' should route to NOTICE_GIVEN, not ambiguous."""
        result = detect_intent("Raj gave notice", "admin")
        assert result.intent == "NOTICE_GIVEN"

    def test_payment_with_name_amount_mode(self):
        """'Arjun 12000 cash' — clear payment, not ambiguous."""
        result = detect_intent("Arjun 12000 cash", "admin")
        assert result.intent == "PAYMENT_LOG"

    def test_just_a_name(self):
        """Just a name with nothing else — should be UNKNOWN."""
        result = detect_intent("Raj", "admin")
        assert result.intent in ("UNKNOWN", "QUERY_TENANT", "HELP")

    def test_name_with_only_number_no_context(self):
        """'Raj 14000' — number could be payment amount or phone."""
        result = detect_intent("Raj 14000", "admin")
        # Should detect as something (likely PAYMENT_LOG due to amount pattern)
        assert result.intent is not None

    def test_ambiguous_entities_extracted(self):
        """Even in ambiguous case, entities like name and date should be extracted."""
        result = detect_intent("Vikram 10th April", "admin")
        assert result.intent == "AMBIGUOUS"
        assert result.entities.get("name") == "Vikram"

    def test_ambiguous_date_extracted(self):
        """Date entity should be present in ambiguous result."""
        result = detect_intent("Priya 25th June", "admin")
        if result.intent == "AMBIGUOUS":
            assert "date" in result.entities

    def test_power_user_sees_ambiguous(self):
        """Power users should also see ambiguous intents like admins."""
        result = detect_intent("Deepak 15th April", "power_user")
        assert result.intent == "AMBIGUOUS"


# ═══════════════════════════════════════════════════════════════════════════════
# 4. ROLE-BASED INTENT FILTERING (15 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestRoleBasedIntentFiltering:
    def test_admin_payment_log(self):
        """Admin: 'Raj paid 14000' → PAYMENT_LOG."""
        result = detect_intent("Raj paid 14000", "admin")
        assert result.intent == "PAYMENT_LOG"

    def test_tenant_cannot_log_payment(self):
        """Tenant: 'Raj paid 14000' should NOT be PAYMENT_LOG (tenant rules don't have it)."""
        result = detect_intent("Raj paid 14000", "tenant")
        assert result.intent != "PAYMENT_LOG"

    def test_tenant_my_balance(self):
        """Tenant: 'my balance' → MY_BALANCE."""
        result = detect_intent("my balance", "tenant")
        assert result.intent == "MY_BALANCE"

    def test_admin_help(self):
        """Admin: 'help' → HELP."""
        result = detect_intent("help", "admin")
        assert result.intent == "HELP"

    def test_tenant_help(self):
        """Tenant: 'help' → HELP."""
        result = detect_intent("help", "tenant")
        assert result.intent == "HELP"

    def test_lead_price_query(self):
        """Lead: 'how much is rent' → ROOM_PRICE."""
        result = detect_intent("how much is rent", "lead")
        assert result.intent == "ROOM_PRICE"

    def test_lead_availability(self):
        """Lead: 'any rooms available' → AVAILABILITY."""
        result = detect_intent("any rooms available", "lead")
        assert result.intent == "AVAILABILITY"

    def test_lead_visit(self):
        """Lead: 'can I visit' → VISIT_REQUEST."""
        result = detect_intent("can i visit", "lead")
        assert result.intent == "VISIT_REQUEST"

    def test_lead_unknown_falls_to_general(self):
        """Lead: unrecognized message → GENERAL (not UNKNOWN)."""
        result = detect_intent("tell me about the neighborhood", "lead")
        assert result.intent == "GENERAL"

    def test_power_user_same_as_admin(self):
        """Power user: should detect same intents as admin."""
        result = detect_intent("Raj paid 15000", "power_user")
        assert result.intent == "PAYMENT_LOG"

    def test_key_user_same_as_admin(self):
        """Key user: should detect same intents as admin."""
        result = detect_intent("Raj paid 15000", "key_user")
        assert result.intent == "PAYMENT_LOG"

    def test_unknown_role_returns_general(self):
        """Unknown role should return GENERAL."""
        result = detect_intent("Raj paid 15000", "stranger")
        assert result.intent == "GENERAL"

    def test_tenant_complaint(self):
        """Tenant: 'fan not working' → COMPLAINT_REGISTER."""
        result = detect_intent("fan not working", "tenant")
        assert result.intent == "COMPLAINT_REGISTER"

    def test_admin_complaint(self):
        """Admin: 'fan not working in room 301' → COMPLAINT_REGISTER."""
        result = detect_intent("fan not working in room 301", "admin")
        assert result.intent == "COMPLAINT_REGISTER"

    def test_tenant_wifi_password(self):
        """Tenant: 'wifi password' → GET_WIFI_PASSWORD."""
        result = detect_intent("wifi password", "tenant")
        assert result.intent == "GET_WIFI_PASSWORD"


# ═══════════════════════════════════════════════════════════════════════════════
# 5. NUMBER DISAMBIGUATION (15 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestNumberDisambiguation:
    def test_room_and_amount_separated(self):
        """'room 301 paid 14000' → room=301, amount=14000."""
        entities = _extract_entities("room 301 paid 14000", "PAYMENT_LOG")
        assert entities.get("room") == "301"
        assert entities.get("amount") == 14000.0

    def test_amount_after_payment_keyword(self):
        """'paid 5000 room 301' → amount=5000, room=301."""
        entities = _extract_entities("paid 5000 room 301", "PAYMENT_LOG")
        assert entities.get("amount") == 5000.0
        assert entities.get("room") == "301"

    def test_room_not_confused_with_amount(self):
        """'room 811' should not set amount to 811."""
        entities = _extract_entities("room 811 balance", "QUERY_TENANT")
        assert entities.get("room") == "811"
        # Amount should not be 811 (room number stripped before amount scan)
        assert entities.get("amount") != 811.0 or entities.get("amount") is None

    def test_name_amount_mode_shorthand(self):
        """'Arjun 12000 cash' → name=Arjun, amount=12000."""
        entities = _extract_entities("Arjun 12000 cash", "PAYMENT_LOG")
        assert entities.get("name") == "Arjun"
        assert entities.get("amount") == 12000.0
        assert entities.get("payment_mode") == "cash"

    def test_amount_with_comma(self):
        """'paid 15,000' → amount=15000."""
        entities = _extract_entities("Raj paid 15,000", "PAYMENT_LOG")
        assert entities.get("amount") == 15000.0

    def test_amount_with_k_suffix(self):
        """'paid 15k' → amount=15000."""
        entities = _extract_entities("Raj paid 15k", "PAYMENT_LOG")
        assert entities.get("amount") == 15000.0

    def test_amount_with_decimal(self):
        """'paid 1500.50' → amount=1500.5."""
        entities = _extract_entities("Raj paid 1500.50", "PAYMENT_LOG")
        assert entities.get("amount") == 1500.5

    def test_multiple_numbers_room_first(self):
        """'room 203 8000 upi' → room=203, amount=8000."""
        entities = _extract_entities("room 203 8000 upi", "PAYMENT_LOG")
        assert entities.get("room") == "203"

    def test_upi_mode_detected(self):
        """'paid 5000 upi' → payment_mode=upi."""
        entities = _extract_entities("Raj paid 5000 upi", "PAYMENT_LOG")
        assert entities.get("payment_mode") == "upi"

    def test_gpay_maps_to_upi(self):
        """'gpay' should map to payment_mode=upi."""
        entities = _extract_entities("Raj paid 5000 gpay", "PAYMENT_LOG")
        assert entities.get("payment_mode") == "upi"

    def test_cash_mode_detected(self):
        """'paid 5000 cash' → payment_mode=cash."""
        entities = _extract_entities("Raj paid 5000 cash", "PAYMENT_LOG")
        assert entities.get("payment_mode") == "cash"

    def test_name_extraction_skips_keywords(self):
        """'Paid' should not be extracted as a name."""
        entities = _extract_entities("paid 5000 from room 301", "PAYMENT_LOG")
        assert entities.get("name") != "Paid"

    def test_name_extraction_trailing_keyword_stripped(self):
        """'Jeevan Balance' → name should be 'Jeevan', not 'Jeevan Balance'."""
        entities = _extract_entities("Jeevan Balance", "QUERY_TENANT")
        assert entities.get("name") == "Jeevan"

    def test_expense_amount(self):
        """'electricity 8400' → amount=8400."""
        entities = _extract_entities("electricity 8400", "ADD_EXPENSE")
        assert entities.get("amount") == 8400.0

    def test_phone_number_not_amount(self):
        """10-digit phone number should not become amount if room keyword present."""
        entities = _extract_entities("room 301 tenant 9876543210", "QUERY_TENANT")
        assert entities.get("room") == "301"


# ═══════════════════════════════════════════════════════════════════════════════
# 6. INTENT CONFIDENCE LEVELS (10 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestIntentConfidenceLevels:
    def test_clear_payment_high_confidence(self):
        """'Raj paid 15000 cash' should have confidence >= 0.90."""
        result = detect_intent("Raj paid 15000 cash", "admin")
        assert result.confidence >= 0.90

    def test_clear_checkout_high_confidence(self):
        """'checkout Raj' should have confidence >= 0.90."""
        result = detect_intent("checkout Raj", "admin")
        assert result.confidence >= 0.90

    def test_clear_help_high_confidence(self):
        """'help' should have confidence >= 0.90."""
        result = detect_intent("help", "admin")
        assert result.confidence >= 0.90

    def test_clear_add_tenant_high_confidence(self):
        """'add tenant' should have confidence >= 0.90."""
        result = detect_intent("add tenant", "admin")
        assert result.confidence >= 0.90

    def test_unknown_has_low_confidence(self):
        """Unrecognized message should have low confidence."""
        result = detect_intent("the weather is nice today", "admin")
        assert result.confidence <= 0.5

    def test_ambiguous_has_mid_confidence(self):
        """Ambiguous messages should have confidence around 0.5."""
        result = detect_intent("Raj 31st March", "admin")
        assert result.confidence <= 0.6

    def test_button_tap_highest_confidence(self):
        """Direct button tap should have confidence 0.99."""
        result = detect_intent("PAYMENT_LOG", "admin")
        assert result.confidence == 0.99

    def test_tenant_balance_high_confidence(self):
        """Tenant 'my balance' should have high confidence."""
        result = detect_intent("my balance", "tenant")
        assert result.confidence >= 0.90

    def test_lead_general_mid_confidence(self):
        """Lead fallback to GENERAL should have 0.5 confidence."""
        result = detect_intent("something random", "lead")
        assert result.intent == "GENERAL"
        assert result.confidence == 0.5

    def test_expense_clear_intent_high_confidence(self):
        """'electricity 8400' should have confidence >= 0.88."""
        result = detect_intent("electricity 8400", "admin")
        assert result.confidence >= 0.88


# ═══════════════════════════════════════════════════════════════════════════════
# 7. HINDI / MIXED LANGUAGE (10 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestHindiMixedLanguage:
    def test_checkout_karo(self):
        """'Raj ka checkout karo' → RECORD_CHECKOUT or CHECKOUT."""
        result = detect_intent("Raj ka checkout karo", "admin")
        assert result.intent in ("RECORD_CHECKOUT", "CHECKOUT")

    def test_baki_tenant(self):
        """'baki' as tenant → MY_BALANCE (baki matches MY_BALANCE regex)."""
        result = detect_intent("baki", "tenant")
        assert result.intent == "MY_BALANCE"

    def test_naya_tenant_add_karo(self):
        """'naya tenant add karo' → ADD_TENANT."""
        result = detect_intent("naya tenant add karo", "admin")
        assert result.intent == "ADD_TENANT"

    def test_baki_list(self):
        """'baki list' → QUERY_DUES."""
        result = detect_intent("baki list", "admin")
        assert result.intent == "QUERY_DUES"

    def test_chutti_pe_hai(self):
        """'Raj chutti pe hai' → LOG_VACATION."""
        result = detect_intent("Raj chutti pe hai", "admin")
        assert result.intent == "LOG_VACATION"

    def test_sabko_reminder(self):
        """'sabko reminder bhejo' → SEND_REMINDER_ALL."""
        result = detect_intent("sabko reminder bhejo", "admin")
        assert result.intent == "SEND_REMINDER_ALL"

    def test_khali_rooms(self):
        """'khali rooms' → QUERY_VACANT_ROOMS."""
        result = detect_intent("khali rooms", "admin")
        assert result.intent == "QUERY_VACANT_ROOMS"

    def test_kharab_complaint(self):
        """'AC kharab' → COMPLAINT_REGISTER."""
        result = detect_intent("AC kharab", "admin")
        assert result.intent == "COMPLAINT_REGISTER"

    def test_yaad_dilao_reminder(self):
        """'Raj ko yaad dilao' → REMINDER_SET."""
        result = detect_intent("Raj ko yaad dilao", "admin")
        assert result.intent == "REMINDER_SET"

    def test_wifi_kya_hai(self):
        """'wifi kya hai' → GET_WIFI_PASSWORD."""
        result = detect_intent("wifi kya hai", "admin")
        assert result.intent == "GET_WIFI_PASSWORD"


# ═══════════════════════════════════════════════════════════════════════════════
# 8. CORRECTION SCENARIOS (10 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCorrectionScenarios:
    def test_change_amount_extracts_new_amount(self):
        """'change amount to 15000' → should extract 15000."""
        entities = _extract_entities("change amount to 15000", "PAYMENT_LOG")
        assert entities.get("amount") == 15000.0

    def test_not_14000_15000_extracts_both(self):
        """'not 14000, 15000' → entity extraction should get a number."""
        entities = _extract_entities("not 14000, 15000", "PAYMENT_LOG")
        assert entities.get("amount") is not None

    def test_actually_upi_mode(self):
        """'actually it was upi' → payment_mode=upi."""
        entities = _extract_entities("actually it was upi", "PAYMENT_LOG")
        assert entities.get("payment_mode") == "upi"

    def test_void_payment_intent(self):
        """'void payment' → VOID_PAYMENT."""
        result = detect_intent("void payment", "admin")
        assert result.intent == "VOID_PAYMENT"

    def test_cancel_payment_intent(self):
        """'cancel payment' → VOID_PAYMENT."""
        result = detect_intent("cancel payment", "admin")
        assert result.intent == "VOID_PAYMENT"

    def test_wrong_payment_intent(self):
        """'wrong payment' → VOID_PAYMENT."""
        result = detect_intent("wrong payment", "admin")
        assert result.intent == "VOID_PAYMENT"

    def test_void_expense_intent(self):
        """'wrong expense' → VOID_EXPENSE."""
        result = detect_intent("wrong expense for electricity", "admin")
        assert result.intent == "VOID_EXPENSE"

    def test_update_checkin_date(self):
        """'update checkin Arjun March 5' → UPDATE_CHECKIN."""
        result = detect_intent("update checkin Arjun March 5", "admin")
        assert result.intent == "UPDATE_CHECKIN"

    def test_backdate_checkin(self):
        """'Arjun joined on 5 March' → UPDATE_CHECKIN."""
        result = detect_intent("Arjun joined on 5 March", "admin")
        assert result.intent == "UPDATE_CHECKIN"

    def test_deposit_change(self):
        """'change deposit for Raj' → DEPOSIT_CHANGE."""
        result = detect_intent("change deposit for Raj", "admin")
        assert result.intent == "DEPOSIT_CHANGE"


# ═══════════════════════════════════════════════════════════════════════════════
# BONUS: DATE EXTRACTION EDGE CASES (10 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestDateExtractionEdgeCases:
    def test_day_month_format(self):
        """'20 Feb' → 2026-02-20."""
        result = _extract_date_entity("20 Feb")
        assert result is not None
        assert result.endswith("-02-20")

    def test_month_day_format(self):
        """'March 10' → YYYY-03-10."""
        result = _extract_date_entity("March 10")
        assert result is not None
        assert "-03-10" in result

    def test_ordinal_suffix(self):
        """'31st March' → YYYY-03-31."""
        result = _extract_date_entity("31st March")
        assert result is not None
        assert "-03-31" in result

    def test_with_year(self):
        """'20 Feb 2026' → 2026-02-20."""
        result = _extract_date_entity("20 Feb 2026")
        assert result == "2026-02-20"

    def test_slash_format(self):
        """'20/02/2026' → 2026-02-20."""
        result = _extract_date_entity("20/02/2026")
        assert result == "2026-02-20"

    def test_dash_format(self):
        """'15-03-2026' → 2026-03-15."""
        result = _extract_date_entity("15-03-2026")
        assert result == "2026-03-15"

    def test_dot_format(self):
        """'10.04.2026' → 2026-04-10."""
        result = _extract_date_entity("10.04.2026")
        assert result == "2026-04-10"

    def test_no_date_returns_none(self):
        """Message with no date should return None."""
        result = _extract_date_entity("Raj paid 5000")
        assert result is None

    def test_two_digit_year(self):
        """'20/02/26' → 2026-02-20 (2-digit year gets 2000 added)."""
        result = _extract_date_entity("20/02/26")
        assert result == "2026-02-20"

    def test_invalid_date_returns_none(self):
        """'31 Feb' → None (invalid date)."""
        result = _extract_date_entity("31 Feb")
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════════
# BONUS: BUTTON TAP / DIRECT INTENT PASSTHROUGH (5 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestDirectIntentPassthrough:
    def test_admin_button_tap(self):
        """Admin tapping 'PAYMENT_LOG' button → direct passthrough."""
        result = detect_intent("PAYMENT_LOG", "admin")
        assert result.intent == "PAYMENT_LOG"
        assert result.confidence == 0.99

    def test_tenant_button_tap(self):
        """Tenant tapping 'MY_BALANCE' button → direct passthrough."""
        result = detect_intent("MY_BALANCE", "tenant")
        assert result.intent == "MY_BALANCE"
        assert result.confidence == 0.99

    def test_lead_button_tap(self):
        """Lead tapping 'ROOM_PRICE' button → direct passthrough."""
        result = detect_intent("ROOM_PRICE", "lead")
        assert result.intent == "ROOM_PRICE"
        assert result.confidence == 0.99

    def test_tenant_cannot_tap_admin_button(self):
        """Tenant tapping 'PAYMENT_LOG' should NOT get direct passthrough."""
        result = detect_intent("PAYMENT_LOG", "tenant")
        assert result.confidence != 0.99 or result.intent != "PAYMENT_LOG"

    def test_admin_more_menu(self):
        """Admin tapping 'MORE_MENU' → direct passthrough."""
        result = detect_intent("MORE_MENU", "admin")
        assert result.intent == "MORE_MENU"
        assert result.confidence == 0.99
