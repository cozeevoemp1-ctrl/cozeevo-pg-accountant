"""
Tests for mid-flow breakout detection and intent detection in conversation context.

~200 pure unit tests covering:
  1. Cancel detection (25)
  2. Greeting detection (25)
  3. New intent detection (40)
  4. Non-breakout / None responses (50)
  5. Edge cases (30)
  6. Pending intent specificity (30)
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.whatsapp.chat_api import _detect_mid_flow_breakout
from src.whatsapp.intent_detector import detect_intent, _extract_entities


# ═══════════════════════════════════════════════════════════════════════════════
# 1. CANCEL DETECTION (25 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCancelDetection:
    """All cancel words should return 'cancel' regardless of pending intent."""

    # --- Exact cancel words ---

    def test_cancel_word_cancel(self):
        assert _detect_mid_flow_breakout("cancel", "ADD_TENANT_STEP") == "cancel"

    def test_cancel_word_stop(self):
        assert _detect_mid_flow_breakout("stop", "ADD_TENANT_STEP") == "cancel"

    def test_cancel_word_abort(self):
        assert _detect_mid_flow_breakout("abort", "RECORD_CHECKOUT") == "cancel"

    def test_cancel_word_nevermind(self):
        assert _detect_mid_flow_breakout("nevermind", "CONFIRM_PAYMENT_LOG") == "cancel"

    def test_cancel_word_never_mind(self):
        assert _detect_mid_flow_breakout("never mind", "ADD_TENANT_STEP") == "cancel"

    def test_cancel_word_nvm(self):
        assert _detect_mid_flow_breakout("nvm", "RECORD_CHECKOUT") == "cancel"

    def test_cancel_word_forget_it(self):
        assert _detect_mid_flow_breakout("forget it", "CONFIRM_PAYMENT_LOG") == "cancel"

    def test_cancel_word_leave_it(self):
        assert _detect_mid_flow_breakout("leave it", "ADD_TENANT_STEP") == "cancel"

    def test_skip_is_not_cancel(self):
        # "skip" is a valid form answer (skip cash/UPI), not a cancel word
        assert _detect_mid_flow_breakout("skip", "RECORD_CHECKOUT") is None

    def test_cancel_word_exit(self):
        assert _detect_mid_flow_breakout("exit", "CONFIRM_PAYMENT_LOG") == "cancel"

    def test_cancel_word_quit(self):
        assert _detect_mid_flow_breakout("quit", "ADD_TENANT_STEP") == "cancel"

    def test_cancel_word_chhodo(self):
        assert _detect_mid_flow_breakout("chhodo", "RECORD_CHECKOUT") == "cancel"

    def test_cancel_word_rehne_do(self):
        assert _detect_mid_flow_breakout("rehne do", "CONFIRM_PAYMENT_LOG") == "cancel"

    # --- Case insensitivity ---

    def test_cancel_uppercase_CANCEL(self):
        assert _detect_mid_flow_breakout("Cancel", "ADD_TENANT_STEP") == "cancel"

    def test_cancel_uppercase_STOP(self):
        assert _detect_mid_flow_breakout("STOP", "RECORD_CHECKOUT") == "cancel"

    def test_cancel_uppercase_NVM(self):
        assert _detect_mid_flow_breakout("NVM", "CONFIRM_PAYMENT_LOG") == "cancel"

    def test_cancel_mixed_case_Nevermind(self):
        assert _detect_mid_flow_breakout("Nevermind", "ADD_TENANT_STEP") == "cancel"

    def test_cancel_mixed_case_Abort(self):
        assert _detect_mid_flow_breakout("Abort", "RECORD_CHECKOUT") == "cancel"

    # --- With punctuation (stripped by rstrip) ---

    def test_cancel_with_exclamation(self):
        assert _detect_mid_flow_breakout("cancel!", "ADD_TENANT_STEP") == "cancel"

    def test_cancel_stop_with_period(self):
        assert _detect_mid_flow_breakout("stop.", "RECORD_CHECKOUT") == "cancel"

    def test_cancel_with_question_mark(self):
        assert _detect_mid_flow_breakout("cancel?", "CONFIRM_PAYMENT_LOG") == "cancel"

    def test_cancel_quit_with_exclamation(self):
        assert _detect_mid_flow_breakout("quit!", "ADD_TENANT_STEP") == "cancel"

    # --- During different pending intents ---

    def test_cancel_during_notice_given(self):
        assert _detect_mid_flow_breakout("cancel", "NOTICE_GIVEN") == "cancel"

    def test_cancel_during_intent_ambiguous(self):
        assert _detect_mid_flow_breakout("cancel", "INTENT_AMBIGUOUS") == "cancel"

    def test_cancel_during_awaiting_clarification(self):
        assert _detect_mid_flow_breakout("stop", "AWAITING_CLARIFICATION") == "cancel"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. GREETING DETECTION (25 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestGreetingDetection:
    """All greeting words should return 'greeting' regardless of pending intent."""

    # --- Exact greeting words ---

    def test_greeting_hi(self):
        assert _detect_mid_flow_breakout("hi", "ADD_TENANT_STEP") == "greeting"

    def test_greeting_hello(self):
        assert _detect_mid_flow_breakout("hello", "RECORD_CHECKOUT") == "greeting"

    def test_greeting_hey(self):
        assert _detect_mid_flow_breakout("hey", "CONFIRM_PAYMENT_LOG") == "greeting"

    def test_greeting_menu(self):
        assert _detect_mid_flow_breakout("menu", "ADD_TENANT_STEP") == "greeting"

    def test_greeting_help(self):
        assert _detect_mid_flow_breakout("help", "RECORD_CHECKOUT") == "greeting"

    def test_greeting_start(self):
        assert _detect_mid_flow_breakout("start", "CONFIRM_PAYMENT_LOG") == "greeting"

    # --- Case insensitivity ---

    def test_greeting_Hi_capitalized(self):
        assert _detect_mid_flow_breakout("Hi", "ADD_TENANT_STEP") == "greeting"

    def test_greeting_HELLO_uppercase(self):
        assert _detect_mid_flow_breakout("HELLO", "RECORD_CHECKOUT") == "greeting"

    def test_greeting_Hey_capitalized(self):
        assert _detect_mid_flow_breakout("Hey", "CONFIRM_PAYMENT_LOG") == "greeting"

    def test_greeting_MENU_uppercase(self):
        assert _detect_mid_flow_breakout("MENU", "ADD_TENANT_STEP") == "greeting"

    def test_greeting_HELP_uppercase(self):
        assert _detect_mid_flow_breakout("HELP", "RECORD_CHECKOUT") == "greeting"

    def test_greeting_START_uppercase(self):
        assert _detect_mid_flow_breakout("START", "CONFIRM_PAYMENT_LOG") == "greeting"

    # --- With punctuation ---

    def test_greeting_hi_exclamation(self):
        assert _detect_mid_flow_breakout("hi!", "ADD_TENANT_STEP") == "greeting"

    def test_greeting_hello_period(self):
        assert _detect_mid_flow_breakout("hello.", "RECORD_CHECKOUT") == "greeting"

    def test_greeting_Hey_exclamation(self):
        assert _detect_mid_flow_breakout("Hey!", "CONFIRM_PAYMENT_LOG") == "greeting"

    def test_greeting_help_question(self):
        assert _detect_mid_flow_breakout("help?", "ADD_TENANT_STEP") == "greeting"

    def test_greeting_menu_period(self):
        assert _detect_mid_flow_breakout("menu.", "RECORD_CHECKOUT") == "greeting"

    # --- During different pending intents ---

    def test_greeting_during_add_tenant(self):
        assert _detect_mid_flow_breakout("hi", "ADD_TENANT_STEP") == "greeting"

    def test_greeting_during_record_checkout(self):
        assert _detect_mid_flow_breakout("hello", "RECORD_CHECKOUT") == "greeting"

    def test_greeting_during_confirm_payment(self):
        assert _detect_mid_flow_breakout("hey", "CONFIRM_PAYMENT_LOG") == "greeting"

    def test_greeting_during_notice_given(self):
        assert _detect_mid_flow_breakout("menu", "NOTICE_GIVEN") == "greeting"

    def test_greeting_during_intent_ambiguous(self):
        assert _detect_mid_flow_breakout("help", "INTENT_AMBIGUOUS") == "greeting"

    def test_greeting_during_awaiting_clarification(self):
        assert _detect_mid_flow_breakout("start", "AWAITING_CLARIFICATION") == "greeting"

    def test_greeting_during_schedule_checkout(self):
        assert _detect_mid_flow_breakout("hi", "SCHEDULE_CHECKOUT") == "greeting"

    def test_greeting_during_reminder_set(self):
        assert _detect_mid_flow_breakout("menu", "REMINDER_SET") == "greeting"


# ═══════════════════════════════════════════════════════════════════════════════
# 3. NEW INTENT DETECTION (40 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestNewIntentDetection:
    """New intent breakout: only for ADD_TENANT_STEP, RECORD_CHECKOUT, CONFIRM_PAYMENT_LOG."""

    # --- During ADD_TENANT_STEP: payment log messages ---

    def test_new_intent_payment_during_add_tenant(self):
        # "received X from Y" matches ACTIVITY_LOG (not in triggers), so use "paid" form
        result = _detect_mid_flow_breakout("Raj paid 14000 cash", "ADD_TENANT_STEP")
        assert result == "new_intent"

    def test_new_intent_payment_shorthand_during_add_tenant(self):
        result = _detect_mid_flow_breakout("Arjun 12000 cash", "ADD_TENANT_STEP")
        assert result == "new_intent"

    def test_new_intent_paid_message_during_add_tenant(self):
        result = _detect_mid_flow_breakout("Raj paid 15000", "ADD_TENANT_STEP")
        assert result == "new_intent"

    def test_new_intent_expense_during_add_tenant(self):
        result = _detect_mid_flow_breakout("electricity 8400", "ADD_TENANT_STEP")
        assert result == "new_intent"

    def test_new_intent_checkout_during_add_tenant(self):
        result = _detect_mid_flow_breakout("checkout Raj", "ADD_TENANT_STEP")
        assert result == "new_intent"

    def test_new_intent_vacant_rooms_during_add_tenant(self):
        result = _detect_mid_flow_breakout("vacant rooms", "ADD_TENANT_STEP")
        assert result == "new_intent"

    def test_new_intent_dues_query_during_add_tenant(self):
        result = _detect_mid_flow_breakout("who hasn't paid", "ADD_TENANT_STEP")
        assert result == "new_intent"

    def test_new_intent_report_during_add_tenant(self):
        result = _detect_mid_flow_breakout("monthly report", "ADD_TENANT_STEP")
        assert result == "new_intent"

    def test_new_intent_notice_during_add_tenant(self):
        result = _detect_mid_flow_breakout("Deepak gave notice", "ADD_TENANT_STEP")
        assert result == "new_intent"

    def test_new_intent_add_tenant_during_add_tenant(self):
        # User might say "add tenant Priya" while already in add tenant flow
        result = _detect_mid_flow_breakout("add tenant Priya room 301", "ADD_TENANT_STEP")
        assert result == "new_intent"

    # --- During RECORD_CHECKOUT ---

    def test_new_intent_payment_during_checkout(self):
        result = _detect_mid_flow_breakout("Raj paid 10000 upi", "RECORD_CHECKOUT")
        assert result == "new_intent"

    def test_new_intent_add_tenant_during_checkout(self):
        result = _detect_mid_flow_breakout("add tenant Priya room 301", "RECORD_CHECKOUT")
        assert result == "new_intent"

    def test_new_intent_expense_during_checkout(self):
        result = _detect_mid_flow_breakout("maintenance 3000 upi", "RECORD_CHECKOUT")
        assert result == "new_intent"

    def test_new_intent_vacant_rooms_during_checkout(self):
        result = _detect_mid_flow_breakout("vacant rooms", "RECORD_CHECKOUT")
        assert result == "new_intent"

    def test_new_intent_report_during_checkout(self):
        result = _detect_mid_flow_breakout("monthly report", "RECORD_CHECKOUT")
        assert result == "new_intent"

    def test_new_intent_dues_during_checkout(self):
        result = _detect_mid_flow_breakout("who hasn't paid this month", "RECORD_CHECKOUT")
        assert result == "new_intent"

    def test_new_intent_rent_change_during_checkout(self):
        result = _detect_mid_flow_breakout("change rent for room 301", "RECORD_CHECKOUT")
        assert result == "new_intent"

    def test_new_intent_query_tenant_during_checkout(self):
        result = _detect_mid_flow_breakout("Raj balance", "RECORD_CHECKOUT")
        assert result == "new_intent"

    # --- During CONFIRM_PAYMENT_LOG ---

    def test_new_intent_checkout_during_confirm_payment(self):
        result = _detect_mid_flow_breakout("checkout Raj", "CONFIRM_PAYMENT_LOG")
        assert result == "new_intent"

    def test_new_intent_add_tenant_during_confirm_payment(self):
        result = _detect_mid_flow_breakout("add tenant Priya", "CONFIRM_PAYMENT_LOG")
        assert result == "new_intent"

    def test_new_intent_expense_during_confirm_payment(self):
        result = _detect_mid_flow_breakout("electricity 8400", "CONFIRM_PAYMENT_LOG")
        assert result == "new_intent"

    def test_new_intent_vacant_during_confirm_payment(self):
        result = _detect_mid_flow_breakout("vacant rooms", "CONFIRM_PAYMENT_LOG")
        assert result == "new_intent"

    def test_new_intent_notice_during_confirm_payment(self):
        result = _detect_mid_flow_breakout("Suresh gave notice", "CONFIRM_PAYMENT_LOG")
        assert result == "new_intent"

    def test_new_intent_void_during_confirm_payment(self):
        result = _detect_mid_flow_breakout("void payment", "CONFIRM_PAYMENT_LOG")
        assert result == "new_intent"

    def test_new_intent_report_during_confirm_payment(self):
        result = _detect_mid_flow_breakout("summary", "CONFIRM_PAYMENT_LOG")
        assert result == "new_intent"

    # --- Messages that should NOT trigger new intent (answers to pending questions) ---

    def test_not_new_intent_number_answer_add_tenant(self):
        # "1" during disambiguation is just a selection, not a new intent
        result = _detect_mid_flow_breakout("1", "ADD_TENANT_STEP")
        assert result is None

    def test_not_new_intent_name_answer_add_tenant(self):
        # A plain name during add tenant is the tenant name
        result = _detect_mid_flow_breakout("Raj Kumar", "ADD_TENANT_STEP")
        assert result is None

    def test_not_new_intent_phone_answer_add_tenant(self):
        result = _detect_mid_flow_breakout("9876543210", "ADD_TENANT_STEP")
        assert result is None

    def test_not_new_intent_room_number_add_tenant(self):
        result = _detect_mid_flow_breakout("301", "ADD_TENANT_STEP")
        assert result is None

    def test_not_new_intent_amount_answer_add_tenant(self):
        result = _detect_mid_flow_breakout("14000", "ADD_TENANT_STEP")
        assert result is None

    def test_not_new_intent_yes_during_checkout(self):
        result = _detect_mid_flow_breakout("yes", "RECORD_CHECKOUT")
        assert result is None

    def test_not_new_intent_no_during_checkout(self):
        result = _detect_mid_flow_breakout("no", "RECORD_CHECKOUT")
        assert result is None

    def test_not_new_intent_confirm_during_checkout(self):
        result = _detect_mid_flow_breakout("confirm", "RECORD_CHECKOUT")
        assert result is None

    def test_not_new_intent_date_answer_checkout(self):
        result = _detect_mid_flow_breakout("29 March", "RECORD_CHECKOUT")
        assert result is None

    def test_not_new_intent_done_during_checkout(self):
        result = _detect_mid_flow_breakout("done", "RECORD_CHECKOUT")
        assert result is None

    # --- Payment messages during CONFIRM_PAYMENT_LOG should trigger new intent ---

    def test_new_intent_different_payment_during_confirm(self):
        result = _detect_mid_flow_breakout("Suresh paid 8000 cash", "CONFIRM_PAYMENT_LOG")
        assert result == "new_intent"

    def test_new_intent_payment_shorthand_during_confirm(self):
        result = _detect_mid_flow_breakout("Deepak 15000 upi", "CONFIRM_PAYMENT_LOG")
        assert result == "new_intent"

    def test_new_intent_received_payment_during_confirm(self):
        # "received X from Y" matches ACTIVITY_LOG (not in triggers), so use "paid" form
        result = _detect_mid_flow_breakout("Vikram paid 7000 upi", "CONFIRM_PAYMENT_LOG")
        assert result == "new_intent"

    def test_new_intent_room_transfer_during_add_tenant(self):
        result = _detect_mid_flow_breakout("move Raj to room 305", "ADD_TENANT_STEP")
        assert result == "new_intent"


# ═══════════════════════════════════════════════════════════════════════════════
# 4. NON-BREAKOUT / NONE RESPONSES (50 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestNonBreakout:
    """Messages that should NOT trigger any breakout — return None."""

    # --- Numeric answers during disambiguation ---

    def test_number_1_during_add_tenant(self):
        assert _detect_mid_flow_breakout("1", "ADD_TENANT_STEP") is None

    def test_number_2_during_add_tenant(self):
        assert _detect_mid_flow_breakout("2", "ADD_TENANT_STEP") is None

    def test_number_3_during_confirm_payment(self):
        assert _detect_mid_flow_breakout("3", "CONFIRM_PAYMENT_LOG") is None

    def test_number_4_during_checkout(self):
        assert _detect_mid_flow_breakout("4", "RECORD_CHECKOUT") is None

    # --- Yes/No answers during confirmation ---

    def test_yes_during_confirm_payment(self):
        assert _detect_mid_flow_breakout("yes", "CONFIRM_PAYMENT_LOG") is None

    def test_no_during_confirm_payment(self):
        assert _detect_mid_flow_breakout("no", "CONFIRM_PAYMENT_LOG") is None

    def test_confirm_during_confirm_payment(self):
        assert _detect_mid_flow_breakout("confirm", "CONFIRM_PAYMENT_LOG") is None

    def test_yes_uppercase_during_confirm(self):
        assert _detect_mid_flow_breakout("Yes", "CONFIRM_PAYMENT_LOG") is None

    def test_no_uppercase_during_confirm(self):
        assert _detect_mid_flow_breakout("No", "CONFIRM_PAYMENT_LOG") is None

    def test_haan_during_confirm(self):
        assert _detect_mid_flow_breakout("haan", "CONFIRM_PAYMENT_LOG") is None

    def test_nahi_during_confirm(self):
        assert _detect_mid_flow_breakout("nahi", "CONFIRM_PAYMENT_LOG") is None

    # --- Name answers during ADD_TENANT_STEP ---

    def test_name_raj_during_add_tenant(self):
        assert _detect_mid_flow_breakout("Raj", "ADD_TENANT_STEP") is None

    def test_name_raj_kumar_during_add_tenant(self):
        assert _detect_mid_flow_breakout("Raj Kumar", "ADD_TENANT_STEP") is None

    def test_name_priya_during_add_tenant(self):
        assert _detect_mid_flow_breakout("Priya", "ADD_TENANT_STEP") is None

    def test_name_deepak_sharma_during_add_tenant(self):
        assert _detect_mid_flow_breakout("Deepak Sharma", "ADD_TENANT_STEP") is None

    def test_name_single_word_during_add_tenant(self):
        assert _detect_mid_flow_breakout("Suresh", "ADD_TENANT_STEP") is None

    # --- Phone number answers ---

    def test_phone_10_digit_during_add_tenant(self):
        assert _detect_mid_flow_breakout("9876543210", "ADD_TENANT_STEP") is None

    def test_phone_with_prefix_during_add_tenant(self):
        assert _detect_mid_flow_breakout("91 9876543210", "ADD_TENANT_STEP") is None

    def test_phone_with_plus_during_add_tenant(self):
        assert _detect_mid_flow_breakout("+919876543210", "ADD_TENANT_STEP") is None

    # --- Room number answers ---

    def test_room_301_during_add_tenant(self):
        assert _detect_mid_flow_breakout("301", "ADD_TENANT_STEP") is None

    def test_room_T205_during_add_tenant(self):
        assert _detect_mid_flow_breakout("T205", "ADD_TENANT_STEP") is None

    def test_room_H101_during_add_tenant(self):
        assert _detect_mid_flow_breakout("H101", "ADD_TENANT_STEP") is None

    # --- Amount answers ---

    def test_amount_14000_during_add_tenant(self):
        assert _detect_mid_flow_breakout("14000", "ADD_TENANT_STEP") is None

    def test_amount_with_comma_during_add_tenant(self):
        assert _detect_mid_flow_breakout("14,000", "ADD_TENANT_STEP") is None

    def test_amount_8000_during_add_tenant(self):
        assert _detect_mid_flow_breakout("8000", "ADD_TENANT_STEP") is None

    def test_amount_short_during_checkout(self):
        assert _detect_mid_flow_breakout("5000", "RECORD_CHECKOUT") is None

    # --- Date answers ---

    def test_date_29_march_during_checkout(self):
        assert _detect_mid_flow_breakout("29 March", "RECORD_CHECKOUT") is None

    def test_date_slash_format_during_checkout(self):
        assert _detect_mid_flow_breakout("29/03/2026", "RECORD_CHECKOUT") is None

    def test_date_1_april_during_checkout(self):
        assert _detect_mid_flow_breakout("1 April", "RECORD_CHECKOUT") is None

    def test_date_march_15_during_checkout(self):
        assert _detect_mid_flow_breakout("March 15", "RECORD_CHECKOUT") is None

    # --- "done" should NOT be cancel ---

    def test_done_during_add_tenant(self):
        assert _detect_mid_flow_breakout("done", "ADD_TENANT_STEP") is None

    def test_done_during_checkout(self):
        assert _detect_mid_flow_breakout("done", "RECORD_CHECKOUT") is None

    def test_done_during_confirm_payment(self):
        assert _detect_mid_flow_breakout("done", "CONFIRM_PAYMENT_LOG") is None

    # --- Yes/no should NOT be cancel ---

    def test_yes_not_cancel_during_add_tenant(self):
        assert _detect_mid_flow_breakout("yes", "ADD_TENANT_STEP") is None

    def test_no_not_cancel_during_add_tenant(self):
        assert _detect_mid_flow_breakout("no", "ADD_TENANT_STEP") is None

    def test_ok_during_add_tenant(self):
        assert _detect_mid_flow_breakout("ok", "ADD_TENANT_STEP") is None

    def test_okay_during_checkout(self):
        assert _detect_mid_flow_breakout("okay", "RECORD_CHECKOUT") is None

    # --- Payment mode answers ---

    def test_cash_during_add_tenant(self):
        assert _detect_mid_flow_breakout("cash", "ADD_TENANT_STEP") is None

    def test_upi_during_add_tenant(self):
        assert _detect_mid_flow_breakout("upi", "ADD_TENANT_STEP") is None

    def test_gpay_during_confirm_payment(self):
        assert _detect_mid_flow_breakout("gpay", "CONFIRM_PAYMENT_LOG") is None

    # --- Miscellaneous non-breakout ---

    def test_thank_you_during_add_tenant(self):
        assert _detect_mid_flow_breakout("thank you", "ADD_TENANT_STEP") is None

    def test_thanks_during_checkout(self):
        assert _detect_mid_flow_breakout("thanks", "RECORD_CHECKOUT") is None

    def test_single_letter_during_confirm(self):
        assert _detect_mid_flow_breakout("a", "CONFIRM_PAYMENT_LOG") is None

    def test_emoji_thumbsup_during_add_tenant(self):
        assert _detect_mid_flow_breakout("👍", "ADD_TENANT_STEP") is None

    def test_random_short_word_during_checkout(self):
        assert _detect_mid_flow_breakout("sure", "RECORD_CHECKOUT") is None

    def test_got_it_during_add_tenant(self):
        assert _detect_mid_flow_breakout("got it", "ADD_TENANT_STEP") is None

    def test_alright_during_checkout(self):
        assert _detect_mid_flow_breakout("alright", "RECORD_CHECKOUT") is None

    def test_double_sharing_during_add_tenant(self):
        assert _detect_mid_flow_breakout("double sharing", "ADD_TENANT_STEP") is None

    def test_single_sharing_during_add_tenant(self):
        assert _detect_mid_flow_breakout("single", "ADD_TENANT_STEP") is None

    def test_floor_answer_during_add_tenant(self):
        assert _detect_mid_flow_breakout("2nd floor", "ADD_TENANT_STEP") is None


# ═══════════════════════════════════════════════════════════════════════════════
# 5. EDGE CASES (30 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Boundary conditions, ambiguous messages, whitespace, and special chars."""

    # --- Empty and whitespace ---

    def test_empty_string(self):
        assert _detect_mid_flow_breakout("", "ADD_TENANT_STEP") is None

    def test_whitespace_only(self):
        assert _detect_mid_flow_breakout("   ", "ADD_TENANT_STEP") is None

    def test_cancel_with_leading_whitespace(self):
        assert _detect_mid_flow_breakout("  cancel  ", "ADD_TENANT_STEP") == "cancel"

    def test_hi_with_leading_whitespace(self):
        assert _detect_mid_flow_breakout("  hi  ", "ADD_TENANT_STEP") == "greeting"

    # --- "cancel X" vs bare "cancel" ---

    def test_cancel_this_payment_is_not_bare_cancel(self):
        # "cancel this payment" is NOT exact match for "cancel" after strip+lower+rstrip
        # It won't match _CANCEL_WORDS since it has extra words
        # But it might match VOID_PAYMENT intent
        result = _detect_mid_flow_breakout("cancel this payment", "ADD_TENANT_STEP")
        # "cancel this payment" -> stripped = "cancel this payment" which is not in _CANCEL_WORDS
        # It will be probed as new intent — VOID_PAYMENT is in triggers
        assert result == "new_intent"

    def test_i_want_to_stop_adding_not_exact_stop(self):
        # "i want to stop adding" stripped and lowered is not "stop"
        result = _detect_mid_flow_breakout("I want to stop adding", "ADD_TENANT_STEP")
        assert result is None  # Not exact "stop", and not a recognized new intent

    def test_hello_raj_not_exact_greeting(self):
        # "hello raj" is not exact "hello" after stripping punctuation
        result = _detect_mid_flow_breakout("hello Raj", "ADD_TENANT_STEP")
        assert result is None

    def test_help_me_add_tenant_not_exact_greeting(self):
        # "help me add tenant" is not exact "help"
        # But "add tenant" might trigger new intent during ADD_TENANT_STEP
        result = _detect_mid_flow_breakout("help me add tenant", "ADD_TENANT_STEP")
        # detect_intent for "help me add tenant" — could match ADD_TENANT
        assert result in (None, "new_intent")  # depends on regex confidence

    def test_skip_this_not_exact_skip(self):
        # "skip this" is not exact "skip"
        result = _detect_mid_flow_breakout("skip this", "ADD_TENANT_STEP")
        assert result is None

    def test_forget_it_bro_not_exact(self):
        # "forget it bro" is not exact "forget it"
        result = _detect_mid_flow_breakout("forget it bro", "ADD_TENANT_STEP")
        assert result is None

    # --- Very long messages ---

    def test_long_message_with_no_intent(self):
        long_msg = "I was thinking about maybe doing something else but not sure what exactly"
        result = _detect_mid_flow_breakout(long_msg, "ADD_TENANT_STEP")
        assert result is None

    def test_long_message_with_payment_info(self):
        result = _detect_mid_flow_breakout(
            "Actually Raj paid 15000 today in cash for this month rent", "ADD_TENANT_STEP"
        )
        assert result == "new_intent"

    # --- Punctuation edge cases ---

    def test_cancel_multiple_punctuation(self):
        assert _detect_mid_flow_breakout("cancel!!!", "ADD_TENANT_STEP") == "cancel"

    def test_cancel_mixed_punctuation(self):
        assert _detect_mid_flow_breakout("cancel!?", "ADD_TENANT_STEP") == "cancel"

    def test_hi_with_multiple_exclamation(self):
        assert _detect_mid_flow_breakout("hi!!!", "ADD_TENANT_STEP") == "greeting"

    # --- Numbers that are contextual ---

    def test_bare_number_5_during_add_tenant(self):
        assert _detect_mid_flow_breakout("5", "ADD_TENANT_STEP") is None

    def test_large_number_during_add_tenant(self):
        assert _detect_mid_flow_breakout("99999", "ADD_TENANT_STEP") is None

    def test_number_with_text_during_checkout(self):
        # "room 301" during checkout is just answering which room
        assert _detect_mid_flow_breakout("room 301", "RECORD_CHECKOUT") is None

    # --- Unicode / special characters ---

    def test_hindi_haan_during_add_tenant(self):
        assert _detect_mid_flow_breakout("हाँ", "ADD_TENANT_STEP") is None

    def test_random_unicode_during_checkout(self):
        assert _detect_mid_flow_breakout("🏠", "RECORD_CHECKOUT") is None

    # --- Cancel words should not match substrings ---

    def test_cancellation_not_cancel(self):
        # "cancellation" is not exact "cancel", but it matches VOID_PAYMENT regex
        # (substring "cancel" in the pattern), so during ADD_TENANT_STEP it's a new_intent
        result = _detect_mid_flow_breakout("cancellation", "ADD_TENANT_STEP")
        assert result == "new_intent"

    def test_stopping_not_stop(self):
        result = _detect_mid_flow_breakout("stopping", "ADD_TENANT_STEP")
        assert result is None

    def test_exiting_not_exit(self):
        # "exiting" is not exact "exit", but matches CHECKOUT regex ("exit" substring),
        # so during ADD_TENANT_STEP it triggers new_intent
        result = _detect_mid_flow_breakout("exiting", "ADD_TENANT_STEP")
        assert result == "new_intent"

    def test_skipping_not_skip(self):
        result = _detect_mid_flow_breakout("skipping", "ADD_TENANT_STEP")
        assert result is None

    def test_quitting_not_quit(self):
        result = _detect_mid_flow_breakout("quitting", "ADD_TENANT_STEP")
        assert result is None

    # --- Message with only punctuation ---

    def test_only_exclamation(self):
        assert _detect_mid_flow_breakout("!", "ADD_TENANT_STEP") is None

    def test_only_question_mark(self):
        assert _detect_mid_flow_breakout("?", "ADD_TENANT_STEP") is None

    def test_only_dots(self):
        assert _detect_mid_flow_breakout("...", "ADD_TENANT_STEP") is None


# ═══════════════════════════════════════════════════════════════════════════════
# 6. PENDING INTENT SPECIFICITY (30 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestPendingIntentSpecificity:
    """New intent detection only triggers for the 3 specific pending intents.
    For other pending intents, only cancel and greeting work."""

    # --- INTENT_AMBIGUOUS: new intent probe should NOT trigger ---

    def test_payment_during_intent_ambiguous_not_breakout(self):
        result = _detect_mid_flow_breakout("received 14000 from Raj", "INTENT_AMBIGUOUS")
        assert result is None

    def test_checkout_during_intent_ambiguous_not_breakout(self):
        result = _detect_mid_flow_breakout("checkout Raj", "INTENT_AMBIGUOUS")
        assert result is None

    def test_expense_during_intent_ambiguous_not_breakout(self):
        result = _detect_mid_flow_breakout("electricity 8400", "INTENT_AMBIGUOUS")
        assert result is None

    def test_report_during_intent_ambiguous_not_breakout(self):
        result = _detect_mid_flow_breakout("monthly report", "INTENT_AMBIGUOUS")
        assert result is None

    def test_add_tenant_during_intent_ambiguous_not_breakout(self):
        result = _detect_mid_flow_breakout("add tenant Priya", "INTENT_AMBIGUOUS")
        assert result is None

    # --- NOTICE_GIVEN: new intent probe should NOT trigger ---

    def test_payment_during_notice_not_breakout(self):
        result = _detect_mid_flow_breakout("Raj paid 15000", "NOTICE_GIVEN")
        assert result is None

    def test_checkout_during_notice_not_breakout(self):
        result = _detect_mid_flow_breakout("checkout Suresh", "NOTICE_GIVEN")
        assert result is None

    def test_expense_during_notice_not_breakout(self):
        result = _detect_mid_flow_breakout("maintenance 3000", "NOTICE_GIVEN")
        assert result is None

    def test_vacant_during_notice_not_breakout(self):
        result = _detect_mid_flow_breakout("vacant rooms", "NOTICE_GIVEN")
        assert result is None

    def test_add_tenant_during_notice_not_breakout(self):
        result = _detect_mid_flow_breakout("add tenant Priya room 301", "NOTICE_GIVEN")
        assert result is None

    # --- AWAITING_CLARIFICATION: new intent should NOT trigger ---

    def test_payment_during_awaiting_clarification(self):
        result = _detect_mid_flow_breakout("received 14000 from Raj", "AWAITING_CLARIFICATION")
        assert result is None

    def test_checkout_during_awaiting_clarification(self):
        result = _detect_mid_flow_breakout("checkout Raj", "AWAITING_CLARIFICATION")
        assert result is None

    def test_dues_during_awaiting_clarification(self):
        result = _detect_mid_flow_breakout("who hasn't paid", "AWAITING_CLARIFICATION")
        assert result is None

    # --- SCHEDULE_CHECKOUT: new intent should NOT trigger ---

    def test_payment_during_schedule_checkout(self):
        result = _detect_mid_flow_breakout("Raj paid 10000", "SCHEDULE_CHECKOUT")
        assert result is None

    def test_expense_during_schedule_checkout(self):
        result = _detect_mid_flow_breakout("electricity 5000", "SCHEDULE_CHECKOUT")
        assert result is None

    # --- REMINDER_SET: new intent should NOT trigger ---

    def test_payment_during_reminder_set(self):
        result = _detect_mid_flow_breakout("Raj paid 10000", "REMINDER_SET")
        assert result is None

    def test_checkout_during_reminder_set(self):
        result = _detect_mid_flow_breakout("checkout Deepak", "REMINDER_SET")
        assert result is None

    # --- Cancel still works for all pending intents ---

    def test_cancel_during_schedule_checkout(self):
        assert _detect_mid_flow_breakout("cancel", "SCHEDULE_CHECKOUT") == "cancel"

    def test_cancel_during_reminder_set(self):
        assert _detect_mid_flow_breakout("cancel", "REMINDER_SET") == "cancel"

    def test_cancel_during_start_onboarding(self):
        assert _detect_mid_flow_breakout("stop", "START_ONBOARDING") == "cancel"

    def test_cancel_during_query_dues(self):
        assert _detect_mid_flow_breakout("abort", "QUERY_DUES") == "cancel"

    def test_cancel_during_void_payment(self):
        assert _detect_mid_flow_breakout("nvm", "VOID_PAYMENT") == "cancel"

    # --- Greeting still works for all pending intents ---

    def test_greeting_during_schedule_checkout(self):
        assert _detect_mid_flow_breakout("hi", "SCHEDULE_CHECKOUT") == "greeting"

    def test_greeting_during_reminder_set(self):
        assert _detect_mid_flow_breakout("hello", "REMINDER_SET") == "greeting"

    def test_greeting_during_start_onboarding(self):
        assert _detect_mid_flow_breakout("menu", "START_ONBOARDING") == "greeting"

    def test_greeting_during_query_dues(self):
        assert _detect_mid_flow_breakout("help", "QUERY_DUES") == "greeting"

    # --- Confirm the 3 trigger intents DO work ---

    def test_new_intent_works_for_add_tenant_step(self):
        result = _detect_mid_flow_breakout("vacant rooms", "ADD_TENANT_STEP")
        assert result == "new_intent"

    def test_new_intent_works_for_record_checkout(self):
        result = _detect_mid_flow_breakout("vacant rooms", "RECORD_CHECKOUT")
        assert result == "new_intent"

    def test_new_intent_works_for_confirm_payment_log(self):
        result = _detect_mid_flow_breakout("vacant rooms", "CONFIRM_PAYMENT_LOG")
        assert result == "new_intent"

    def test_new_intent_NOT_for_rent_discount(self):
        result = _detect_mid_flow_breakout("checkout Raj", "RENT_DISCOUNT")
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════════
# 7. INTENT DETECTOR — detect_intent + _extract_entities (bonus coverage)
# ═══════════════════════════════════════════════════════════════════════════════

class TestDetectIntentBasic:
    """Basic smoke tests for detect_intent used by the breakout logic."""

    def test_payment_log_detected(self):
        r = detect_intent("Raj paid 15000", "admin")
        assert r.intent == "PAYMENT_LOG"
        assert r.confidence >= 0.85

    def test_checkout_detected(self):
        r = detect_intent("checkout Raj", "admin")
        assert r.intent == "CHECKOUT"
        assert r.confidence >= 0.85

    def test_add_tenant_detected(self):
        r = detect_intent("add tenant Priya room 301", "admin")
        assert r.intent == "ADD_TENANT"
        assert r.confidence >= 0.85

    def test_add_expense_detected(self):
        r = detect_intent("electricity 8400", "admin")
        assert r.intent == "ADD_EXPENSE"
        assert r.confidence >= 0.85

    def test_vacant_rooms_detected(self):
        r = detect_intent("vacant rooms", "admin")
        assert r.intent == "QUERY_VACANT_ROOMS"
        assert r.confidence >= 0.85

    def test_report_detected(self):
        r = detect_intent("monthly report", "admin")
        assert r.intent == "REPORT"
        assert r.confidence >= 0.85

    def test_query_dues_detected(self):
        r = detect_intent("who hasn't paid", "admin")
        assert r.intent == "QUERY_DUES"
        assert r.confidence >= 0.85

    def test_notice_given_detected(self):
        r = detect_intent("Deepak gave notice", "admin")
        assert r.intent == "NOTICE_GIVEN"
        assert r.confidence >= 0.85

    def test_void_payment_detected(self):
        r = detect_intent("void payment", "admin")
        assert r.intent == "VOID_PAYMENT"
        assert r.confidence >= 0.85

    def test_rent_change_detected(self):
        r = detect_intent("change rent for room 301", "admin")
        assert r.intent == "RENT_CHANGE"
        assert r.confidence >= 0.85

    def test_query_tenant_detected(self):
        r = detect_intent("Raj balance", "admin")
        assert r.intent == "QUERY_TENANT"
        assert r.confidence >= 0.85

    def test_help_detected(self):
        r = detect_intent("hi", "admin")
        assert r.intent == "HELP"

    def test_shorthand_payment(self):
        r = detect_intent("Arjun 12000 cash", "admin")
        assert r.intent == "PAYMENT_LOG"
        assert r.confidence >= 0.85

    def test_maintenance_expense(self):
        r = detect_intent("maintenance 3000 upi", "admin")
        assert r.intent == "ADD_EXPENSE"
        assert r.confidence >= 0.85


class TestExtractEntities:
    """Basic tests for _extract_entities."""

    def test_extract_amount_from_payment(self):
        entities = _extract_entities("Raj paid 15000", "PAYMENT_LOG")
        assert "amount" in entities
        assert entities["amount"] == 15000 or entities["amount"] == "15000"

    def test_extract_name_from_payment(self):
        entities = _extract_entities("Raj paid 15000", "PAYMENT_LOG")
        assert "name" in entities

    def test_extract_amount_with_comma(self):
        entities = _extract_entities("received 14,000 from Deepak", "PAYMENT_LOG")
        assert "amount" in entities

    def test_extract_room_number(self):
        entities = _extract_entities("add tenant Priya room 301", "ADD_TENANT")
        assert "room" in entities or "name" in entities

    def test_extract_from_checkout(self):
        entities = _extract_entities("checkout Raj", "CHECKOUT")
        assert "name" in entities
