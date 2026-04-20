"""
Tenant / tenancy field registry — single source of truth.

Every attribute of a tenant + their tenancy that is visible to the
receptionist (sheet, onboarding form, PWA, bot audit logs) is declared
once here. All derived structures — sheet headers, bot→sheet field
maps, API schemas — are generated from FIELDS.

Scope for Phase 1: tenant + tenancy + the couple of read-only
monthly-tab summary cells. Rooms, payments, expenses live elsewhere
and join this registry via FK, not as entries.

Why Python (not a DB table): SQLAlchemy models are already the
schema-of-record for DB columns. A DB-backed metadata table would
duplicate and drift. This Python file is importable by FastAPI
endpoints (PWA) and other services without a DB round-trip.

Adding a field:
  1. Add a Field(...) entry below.
  2. If it belongs on either sheet tab, set tenants_header / monthly_header.
  3. Add it to the tenants_row / monthly_row dict in
     gsheets.py:_sync_tenant_all_fields_sync so the value gets pushed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional


FieldSource = Literal["tenant", "tenancy", "room", "property", "computed"]

FieldType = Literal[
    "text", "textarea",
    "money", "number",
    "date",
    "phone", "email",
    "select",
    "enum_status",
]


@dataclass(frozen=True)
class Field:
    """One observable attribute of a tenant/tenancy.

    `key`               stable machine identifier (audit logs, API payloads,
                        bot-side field-update aliases).
    `display`           short human label (form labels + diff messages).
    `source`            which model owns the canonical value (or "computed"
                        if derived — e.g. refund status from Refund table).
    `db_attr`           attribute name on the source model, or None when
                        source == "computed".
    `tenants_header`    exact header string in the TENANTS master sheet tab,
                        or None if the field isn't displayed there.
    `monthly_header`    exact header string in a per-month sheet tab, or None.
    `type`              rendering/validation hint.
    `options`           choices for type == "select" (None otherwise).
    `editable_via_bot`  receptionist can change this via WhatsApp bot.
    `editable_via_form` tenant can submit/change this via onboarding form.
    `aliases`           secondary bot-side keys that map to the same field
                        (e.g. 'deposit' aliases 'security_deposit').
    """

    key: str
    display: str
    source: FieldSource
    db_attr: Optional[str]
    tenants_header: Optional[str]
    monthly_header: Optional[str]
    type: FieldType
    options: Optional[tuple[str, ...]] = None
    editable_via_bot: bool = False
    editable_via_form: bool = False
    aliases: tuple[str, ...] = ()


# ── Registry ─────────────────────────────────────────────────────────────────
# Keep declarations grouped by semantic cluster for readability. Sheet
# column ORDER is controlled by the explicit layout lists below
# (`_MONTHLY_ORDER`, `_TENANTS_ORDER`) — not by declaration order —
# because the TENANTS tab has a fixed historical column order we must
# preserve exactly (callers of T_REFUND_* rely on positional indices).

FIELDS: tuple[Field, ...] = (
    # ── Identity / location ────────────────────────────────────────────────
    Field("room_number", "Room", "room", "room_number",
          "Room", "Room", "text",
          aliases=("room",), editable_via_bot=True),
    Field("name", "Name", "tenant", "name",
          "Name", "Name", "text",
          editable_via_form=True),
    Field("phone", "Phone", "tenant", "phone",
          "Phone", "Phone", "phone",
          editable_via_bot=True, editable_via_form=True),
    Field("gender", "Gender", "tenant", "gender",
          "Gender", None, "select",
          options=("male", "female", "other"),
          editable_via_form=True),
    Field("building", "Building", "property", "name",
          "Building", "Building", "text"),
    Field("floor", "Floor", "room", "floor",
          "Floor", None, "text"),

    # ── Tenancy terms ──────────────────────────────────────────────────────
    Field("sharing_type", "Sharing", "tenancy", "sharing_type",
          "Sharing", "Sharing", "select",
          options=("single", "double", "triple", "premium"),
          aliases=("sharing",),
          editable_via_bot=True, editable_via_form=True),
    Field("checkin_date", "Check-in", "tenancy", "checkin_date",
          "Check-in", "Check-in", "date",
          aliases=("checkin",), editable_via_form=True),
    Field("status", "Status", "tenancy", "status",
          "Status", "Status", "enum_status"),
    # agreed_rent has DIFFERENT header names on the two tabs:
    #   TENANTS → "Agreed Rent"   (long-form),
    #   MONTHLY → "Rent"          (terse summary).
    Field("agreed_rent", "Agreed Rent", "tenancy", "agreed_rent",
          "Agreed Rent", "Rent", "money",
          aliases=("rent",),
          editable_via_bot=True, editable_via_form=True),
    Field("security_deposit", "Deposit", "tenancy", "security_deposit",
          "Deposit", "Deposit", "money",
          aliases=("deposit",),
          editable_via_bot=True, editable_via_form=True),
    Field("booking_amount", "Booking", "tenancy", "booking_amount",
          "Booking", None, "money",
          aliases=("booking",),
          editable_via_form=True),
    Field("maintenance_fee", "Maintenance", "tenancy", "maintenance_fee",
          "Maintenance", None, "money",
          aliases=("maintenance",),
          editable_via_form=True),
    Field("notice_date", "Notice Date", "tenancy", "notice_date",
          "Notice Date", "Notice Date", "date",
          editable_via_bot=True),
    Field("expected_checkout", "Expected Exit", "tenancy", "expected_checkout",
          "Expected Exit", None, "date",
          aliases=("expected_exit",)),
    Field("checkout_date", "Checkout Date", "tenancy", "checkout_date",
          "Checkout Date", None, "date"),

    # ── Refunds (computed from Refund table — latest per tenancy) ──────────
    Field("refund_status", "Refund Status", "computed", None,
          "Refund Status", None, "text"),
    Field("refund_amount", "Refund Amount", "computed", None,
          "Refund Amount", None, "money"),

    # ── Tenant KYC ─────────────────────────────────────────────────────────
    Field("date_of_birth", "DOB", "tenant", "date_of_birth",
          "DOB", None, "date",
          aliases=("dob",), editable_via_form=True),
    Field("father_name", "Father Name", "tenant", "father_name",
          "Father Name", None, "text",
          editable_via_form=True),
    Field("father_phone", "Father Phone", "tenant", "father_phone",
          "Father Phone", None, "phone",
          editable_via_form=True),
    Field("permanent_address", "Address", "tenant", "permanent_address",
          "Address", None, "textarea",
          aliases=("address",), editable_via_form=True),
    # Emergency contact: NAME keeps the legacy "Emergency Contact" column
    # so the sheet doesn't need migrating. PHONE is an additive new column
    # — gets populated once "Emergency Contact Phone" exists in the sheet.
    # Until then sync_tenant_all_fields silently skips it.
    Field("emergency_contact_name", "Emergency Contact",
          "tenant", "emergency_contact_name",
          "Emergency Contact", None, "text",
          editable_via_form=True),
    Field("emergency_contact_phone", "Emergency Contact Phone",
          "tenant", "emergency_contact_phone",
          "Emergency Contact Phone", None, "phone",
          editable_via_form=True),
    Field("emergency_contact_relationship", "Emergency Relationship",
          "tenant", "emergency_contact_relationship",
          "Emergency Relationship", None, "text",
          editable_via_form=True),
    Field("email", "Email", "tenant", "email",
          "Email", None, "email",
          editable_via_form=True),
    Field("occupation", "Occupation", "tenant", "occupation",
          "Occupation", None, "text",
          editable_via_form=True),
    Field("educational_qualification", "Education",
          "tenant", "educational_qualification",
          "Education", None, "text",
          aliases=("education",), editable_via_form=True),
    Field("office_address", "Office Address", "tenant", "office_address",
          "Office Address", None, "textarea",
          editable_via_form=True),
    Field("office_phone", "Office Phone", "tenant", "office_phone",
          "Office Phone", None, "phone",
          editable_via_form=True),
    Field("id_proof_type", "ID Type", "tenant", "id_proof_type",
          "ID Type", None, "select",
          options=("Aadhar", "Passport", "DL", "Voter", "PAN"),
          aliases=("id_type",), editable_via_form=True),
    Field("id_proof_number", "ID Number", "tenant", "id_proof_number",
          "ID Number", None, "text",
          aliases=("id_number",), editable_via_form=True),
    Field("food_preference", "Food Pref", "tenant", "food_preference",
          "Food Pref", None, "select",
          options=("veg", "non-veg", "egg"),
          aliases=("food_pref",), editable_via_form=True),

    # ── Notes + event ──────────────────────────────────────────────────────
    Field("notes", "Notes", "tenancy", "notes",
          "Notes", "Notes", "textarea",
          editable_via_bot=True, editable_via_form=True),
    Field("event", "Event", "computed", None,
          "Event", "Event", "text"),

    # ── Monthly-only computed cells (reporting) ────────────────────────────
    Field("rent_due", "Rent Due", "computed", None,
          None, "Rent Due", "money"),
    Field("cash", "Cash", "computed", None,
          None, "Cash", "money"),
    Field("upi", "UPI", "computed", None,
          None, "UPI", "money"),
    Field("total_paid", "Total Paid", "computed", None,
          None, "Total Paid", "money"),
    Field("balance", "Balance", "computed", None,
          None, "Balance", "money"),
    Field("prev_due", "Prev Due", "computed", None,
          None, "Prev Due", "money"),
    Field("entered_by", "Entered By", "computed", None,
          None, "Entered By", "text"),
)


# ── Canonical column layouts ─────────────────────────────────────────────────
# Column order for both sheet tabs. Keep in sync with the Google Sheet.
# Every header here must correspond to exactly one Field with the matching
# monthly_header / tenants_header.

_MONTHLY_ORDER: tuple[str, ...] = (
    "Room", "Name", "Phone", "Building", "Sharing",
    "Rent", "Deposit", "Rent Due",
    "Cash", "UPI", "Total Paid", "Balance",
    "Status", "Check-in", "Notice Date",
    "Event", "Notes", "Prev Due", "Entered By",
)

_TENANTS_ORDER: tuple[str, ...] = (
    "Room", "Name", "Phone", "Gender", "Building", "Floor",
    "Sharing", "Check-in", "Status", "Agreed Rent", "Deposit",
    "Booking", "Maintenance", "Notice Date", "Expected Exit", "Checkout Date",
    "Refund Status", "Refund Amount",
    "DOB", "Father Name", "Father Phone", "Address",
    "Emergency Contact", "Emergency Contact Phone",
    "Emergency Relationship", "Email",
    "Occupation", "Education", "Office Address", "Office Phone",
    "ID Type", "ID Number", "Food Pref", "Notes", "Event",
)


# ── Derivation helpers ───────────────────────────────────────────────────────

def monthly_headers() -> list[str]:
    """Header row for every per-month tab, in column order.

    Raises if the canonical order references a header that no Field in
    FIELDS claims — that's a sign the registry is out of sync with the
    sheet layout.
    """
    claimed = {f.monthly_header for f in FIELDS if f.monthly_header}
    missing = [h for h in _MONTHLY_ORDER if h not in claimed]
    if missing:
        raise RuntimeError(
            f"monthly_headers: no Field claims these headers: {missing}"
        )
    return list(_MONTHLY_ORDER)


def tenants_headers() -> list[str]:
    """Header row for the TENANTS master tab, in column order."""
    claimed = {f.tenants_header for f in FIELDS if f.tenants_header}
    missing = [h for h in _TENANTS_ORDER if h not in claimed]
    if missing:
        raise RuntimeError(
            f"tenants_headers: no Field claims these headers: {missing}"
        )
    return list(_TENANTS_ORDER)


def tenants_field_to_header() -> dict[str, str]:
    """Legacy {lowercase_field_key: TENANTS_header_name} alias map.

    Used by the bot-side helper
    `update_tenants_tab_field(room, name, field, value)` so a handler can
    say `field='deposit'` without knowing the exact sheet column title.
    Also exposes `aliases` for backwards-compat (e.g. 'security_deposit'
    → 'Deposit').
    """
    out: dict[str, str] = {}
    for f in FIELDS:
        if not f.tenants_header:
            continue
        out[f.key.lower()] = f.tenants_header
        for alias in f.aliases:
            out[alias.lower()] = f.tenants_header
    return out


def field_to_col() -> dict[str, int]:
    """Legacy {bot_field_key: monthly_tab_column_index_0_based} map.

    Used by `update_tenant_field()` for single-cell writes on the
    CURRENT monthly tab. Alias keys (e.g. 'rent' → 'agreed_rent') resolve
    to the same column index as the canonical key.
    """
    headers = monthly_headers()
    out: dict[str, int] = {}
    for f in FIELDS:
        if not f.monthly_header:
            continue
        idx = headers.index(f.monthly_header)
        out[f.key.lower()] = idx
        for alias in f.aliases:
            out[alias.lower()] = idx
    return out


# ── Introspection helpers for future API endpoint ────────────────────────────

def fields_for_pwa() -> list[dict]:
    """JSON-serializable field list for `GET /api/v2/app/field-registry`.

    One entry per field. PWA reads this on boot to render forms
    dynamically (no hardcoded <input> lists).
    """
    out: list[dict] = []
    for f in FIELDS:
        sheet_columns: list[str] = []
        if f.tenants_header:
            sheet_columns.append(f"TENANTS.{f.tenants_header}")
        if f.monthly_header:
            sheet_columns.append(f"MONTHLY.{f.monthly_header}")
        out.append({
            "key": f.key,
            "display": f.display,
            "source": f.source,
            "db_attr": f.db_attr,
            "type": f.type,
            "options": list(f.options) if f.options else None,
            "sheet_columns": sheet_columns,
            "editable_via_bot": f.editable_via_bot,
            "editable_via_form": f.editable_via_form,
        })
    return out
