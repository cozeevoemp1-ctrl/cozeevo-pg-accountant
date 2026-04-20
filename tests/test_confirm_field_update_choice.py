"""Tests for the CONFIRM_FIELD_UPDATE yes/no/number parser.

Root cause of the Partner 2026-04-20 16:42 bug: the resolver in
`owner_handler.py` did `choice = reply_text.strip()` (no `.lower()`),
then compared against `("1", "yes", "y")`. A capital-Y "Yes" didn't
match, fell to the `else` → "Update cancelled."

These tests lock in that "Yes" / "YES" / common confirm variants and
"1" all count as confirm, and "No" / "2" count as cancel.
"""
import pytest

from src.whatsapp.handlers.update_handler import _is_confirm_choice


@pytest.mark.parametrize("text", [
    "1", "1.", " 1 ",
    "yes", "Yes", "YES", "y", "Y",
    "confirm", "ok", "yeah", "sure",
])
def test_confirm_variants(text):
    assert _is_confirm_choice(text) is True


@pytest.mark.parametrize("text", [
    "2", "2.", " 2 ",
    "no", "No", "NO", "n", "cancel", "stop",
])
def test_cancel_variants(text):
    assert _is_confirm_choice(text) is False


@pytest.mark.parametrize("text", [
    "", "maybe", "something else", "3",
])
def test_ambiguous_returns_false(text):
    # Unknown text should NOT be treated as confirm (safe default: cancel).
    assert _is_confirm_choice(text) is False
