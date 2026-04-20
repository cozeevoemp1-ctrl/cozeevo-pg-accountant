"""Tests for staff-room mark/unmark phrase classification.

Root cause of Lokesh's 2026-04-20 loop: `_update_single_room` used
`"staff room" in desc_lower` before `"not staff" in desc_lower`, so
phrases like "not staff rooms 114 and 618" or "114 not staff room"
incorrectly hit the MARK branch because "staff room" is a substring
of "staff rooms" / "not staff room".

These tests lock in the correct classification so the bug cannot
regress.
"""
import pytest

from src.whatsapp.handlers.update_handler import _classify_staff_toggle


# Phrases that must UNMARK (clear is_staff_room). The first two are the
# exact phrasings Lokesh used that silently flipped the wrong way.
@pytest.mark.parametrize("phrase", [
    "not staff rooms 114 and 618",   # multi-room, "staff room" ⊂ "staff rooms"
    "114 not staff room",            # "staff room" ⊂ "not staff room"
    "room 114 not staff",
    "room 618 not staff",
    "remove staff 114",
    "unmark staff 114",
    "no staff 114",
    "114 revenue room",
    "make 114 tenant room",
])
def test_unmark_phrases(phrase):
    assert _classify_staff_toggle(phrase) == "unmark", (
        f"expected 'unmark' for {phrase!r}"
    )


@pytest.mark.parametrize("phrase", [
    "room 114 staff room",
    "114 staff room",
    "mark staff 114",
    "room 114 is staff",
    "make staff 114",
    "set staff 114",
    "staff yes for room 114",
])
def test_mark_phrases(phrase):
    assert _classify_staff_toggle(phrase) == "mark", (
        f"expected 'mark' for {phrase!r}"
    )


@pytest.mark.parametrize("phrase", [
    "room 114 add ac",
    "room 114 under maintenance",
    "room 114 type single",
])
def test_non_staff_phrases_return_none(phrase):
    assert _classify_staff_toggle(phrase) is None
