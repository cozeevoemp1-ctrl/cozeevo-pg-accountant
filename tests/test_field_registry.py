"""Parity tests for src/database/field_registry.py.

These lock in the registry's derived outputs against the current
hardcoded structures in gsheets.py. If you intentionally change a
header or add a column, update the EXPECTED_* literals below in the
same commit so the diff is visible on review.
"""

import pytest

from src.database.field_registry import (
    FIELDS, Field,
    field_to_col,
    monthly_headers,
    tenants_field_to_header,
    tenants_headers,
)


# ── Snapshot of every derived structure ──────────────────────────────────────
# These are compared against the current gsheets.py hardcoded values
# (plus the one intentional addition: "Emergency Contact Phone").

EXPECTED_MONTHLY = [
    "Room", "Name", "Phone", "Building", "Sharing",
    "Rent", "Deposit", "Rent Due",
    "Cash", "UPI", "Total Paid", "Balance",
    "Status", "Check-in", "Notice Date",
    "Event", "Notes", "Prev Due", "Entered By",
]


# Current gsheets.py TENANTS_HEADERS + one new additive column.
EXPECTED_TENANTS = [
    "Room", "Name", "Phone", "Gender", "Building", "Floor",
    "Sharing", "Check-in", "Status", "Agreed Rent", "Deposit",
    "Booking", "Maintenance", "Notice Date", "Expected Exit", "Checkout Date",
    "Refund Status", "Refund Amount",
    "DOB", "Father Name", "Father Phone", "Address",
    "Emergency Contact", "Emergency Contact Phone",
    "Emergency Relationship", "Email",
    "Occupation", "Education", "Office Address", "Office Phone",
    "ID Type", "ID Number", "Food Pref", "Notes", "Event",
]


# Current gsheets.py _TENANTS_FIELD_TO_HEADER plus new entries the
# registry introduces (emergency_contact_name/_phone + refund fields
# + agreed_rent resolves via its alias 'rent' same as before).
EXPECTED_TENANTS_FIELD_TO_HEADER_SUBSET = {
    "room": "Room",
    "room_number": "Room",
    "deposit": "Deposit",
    "security_deposit": "Deposit",
    "agreed_rent": "Agreed Rent",
    "rent": "Agreed Rent",
    "maintenance": "Maintenance",
    "maintenance_fee": "Maintenance",
    "booking": "Booking",
    "booking_amount": "Booking",
    "sharing": "Sharing",
    "sharing_type": "Sharing",
    "phone": "Phone",
    "status": "Status",
    "notice_date": "Notice Date",
    "expected_exit": "Expected Exit",
    "expected_checkout": "Expected Exit",
    "checkout_date": "Checkout Date",
    "notes": "Notes",
    "gender": "Gender",
    "food_pref": "Food Pref",
    "food_preference": "Food Pref",
}


# Current gsheets.py _FIELD_TO_COL (monthly columns by index).
EXPECTED_FIELD_TO_COL_SUBSET = {
    "sharing_type": 4,
    "sharing": 4,
    "deposit": 6,
    "security_deposit": 6,
    "agreed_rent": 5,
    "rent": 5,
    "phone": 2,
    "notes": 16,
    "status": 12,
}


# ── Tests ────────────────────────────────────────────────────────────────────


def test_monthly_headers_parity():
    assert monthly_headers() == EXPECTED_MONTHLY


def test_tenants_headers_parity():
    assert tenants_headers() == EXPECTED_TENANTS


def test_tenants_field_to_header_contains_all_legacy_entries():
    got = tenants_field_to_header()
    for k, v in EXPECTED_TENANTS_FIELD_TO_HEADER_SUBSET.items():
        assert got.get(k) == v, (
            f"registry maps {k!r} → {got.get(k)!r}, expected {v!r}"
        )


def test_field_to_col_contains_all_legacy_entries():
    got = field_to_col()
    for k, v in EXPECTED_FIELD_TO_COL_SUBSET.items():
        assert got.get(k) == v, (
            f"registry maps {k!r} → {got.get(k)!r}, expected {v!r}"
        )


def test_field_keys_are_unique():
    keys = [f.key for f in FIELDS]
    assert len(keys) == len(set(keys)), (
        f"duplicate keys: {[k for k in keys if keys.count(k) > 1]}"
    )


def test_field_aliases_dont_collide_with_keys():
    keys = {f.key for f in FIELDS}
    for f in FIELDS:
        for alias in f.aliases:
            assert alias not in keys or alias == f.key, (
                f"field {f.key} has alias {alias!r} that collides with "
                f"another field's key"
            )


def test_select_fields_have_options():
    for f in FIELDS:
        if f.type == "select":
            assert f.options, f"select field {f.key!r} missing options"


def test_non_computed_fields_have_db_attr():
    for f in FIELDS:
        if f.source != "computed":
            assert f.db_attr, (
                f"field {f.key!r} from {f.source!r} needs db_attr"
            )


def test_every_monthly_header_is_claimed_once():
    claimers = {}
    for f in FIELDS:
        if f.monthly_header:
            claimers.setdefault(f.monthly_header, []).append(f.key)
    dupes = {h: keys for h, keys in claimers.items() if len(keys) > 1}
    assert not dupes, f"monthly_header claimed by multiple fields: {dupes}"


def test_every_tenants_header_is_claimed_once():
    claimers = {}
    for f in FIELDS:
        if f.tenants_header:
            claimers.setdefault(f.tenants_header, []).append(f.key)
    dupes = {h: keys for h, keys in claimers.items() if len(keys) > 1}
    assert not dupes, f"tenants_header claimed by multiple fields: {dupes}"
