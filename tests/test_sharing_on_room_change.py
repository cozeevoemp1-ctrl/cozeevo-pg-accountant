"""Regression tests for resolve_sharing_on_room_change.

Guards the "premium phantom-bed" bug: a whole-room (premium) tenant must keep
sharing_type='premium' across any room change. Before the fix, the PWA Edit-Tenant
endpoint blindly set sharing_type to the destination room's physical room_type,
silently downgrading premium tenants to 'double' on every room move.
"""
import pytest

from services.room_transfer import resolve_sharing_on_room_change
from src.database.models import SharingType, RoomType


def test_premium_preserved_across_room_change():
    """A premium (whole-room) tenant keeps premium — never downgraded to the room type."""
    new_sharing, changed = resolve_sharing_on_room_change(SharingType.premium, RoomType.double)
    assert new_sharing == SharingType.premium
    assert changed is False


def test_premium_preserved_even_into_triple():
    new_sharing, changed = resolve_sharing_on_room_change(SharingType.premium, RoomType.triple)
    assert new_sharing == SharingType.premium
    assert changed is False


def test_triple_rederived_to_double():
    """A non-premium tenant IS re-derived so occupancy math stays correct."""
    new_sharing, changed = resolve_sharing_on_room_change(SharingType.triple, RoomType.double)
    assert new_sharing == SharingType.double
    assert changed is True


def test_double_to_double_no_change():
    new_sharing, changed = resolve_sharing_on_room_change(SharingType.double, RoomType.double)
    assert new_sharing == SharingType.double
    assert changed is False


def test_none_derived_from_room_type():
    new_sharing, changed = resolve_sharing_on_room_change(None, RoomType.double)
    assert new_sharing == SharingType.double
    assert changed is True


def test_accepts_room_type_value_string():
    """Helper tolerates either the enum or its .value string."""
    new_sharing, changed = resolve_sharing_on_room_change(SharingType.single, "double")
    assert new_sharing == SharingType.double
    assert changed is True


def test_premium_preserved_with_string_room_type():
    new_sharing, changed = resolve_sharing_on_room_change(SharingType.premium, "double")
    assert new_sharing == SharingType.premium
    assert changed is False
