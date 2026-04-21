"""Regression: ensure staff-room mark phrases don't collide with ADD_PARTNER.

Bug: receptionist sent "G20 add staff room" and got "Only admin can add partners"
because ADD_PARTNER's `add\\s+staff\\b` pattern caught it.
Fix: ADD_PARTNER now has negative lookahead `(?!\\s+room)`, and UPDATE_ROOM
covers id-first staff-mark variants.
"""
import pytest
from src.whatsapp.intent_detector import detect_intent


@pytest.mark.parametrize("msg", [
    "G20 add staff room",
    "mark G20 staff",
    "G20 not staff",
    "add staff room G20",
    "G20 staff room",
    "mark room G20 staff",
    "set G20 as staff room",
    "G20 is staff room",
])
def test_staff_room_mark_routes_to_update_room(msg):
    r = detect_intent(msg, "receptionist")
    assert r.intent == "UPDATE_ROOM", f"{msg!r} -> {r.intent}"


@pytest.mark.parametrize("msg", [
    "add partner Kiran 9876543210",
    "add staff Lokesh",
    "add power user",
    "new admin 9876543210",
    "give access to 9876543210",
])
def test_add_partner_still_works(msg):
    r = detect_intent(msg, "admin")
    assert r.intent == "ADD_PARTNER", f"{msg!r} -> {r.intent}"
