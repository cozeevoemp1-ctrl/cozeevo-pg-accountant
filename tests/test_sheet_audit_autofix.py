"""Tests for sheet_audit.apply_fixes() and run_audit_with_db().

All gsheets I/O is mocked — no production data touched, no network calls.
"""
from __future__ import annotations

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from src.services.sheet_audit import (
    AuditResult, Diff, apply_fixes, _AUDIT_FIELD_TO_GSHEETS,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _diff(tab="TENANTS", row=5, phone="9876543210", name="Ravi Kumar",
          field_name="Agreed Rent", sheet="10000", db="12000"):
    return Diff(tab=tab, row=row, phone=phone, name=name,
                field=field_name, sheet=sheet, db=db)


def _db_state(phone="9876543210", room="304", name="Ravi Kumar"):
    return {
        "tenants": {phone: {"room": room, "name": name,
                            "agreed_rent": 12000.0, "security_deposit": 24000.0,
                            "notice_date": None, "checkout_date": None,
                            "status": "active", "checkin_date": date(2026, 1, 1),
                            "tenancy_id": 100}},
        "monthly": {},
    }


# ── Tests: apply_fixes with TENANTS diffs ─────────────────────────────────────

@pytest.mark.asyncio
async def test_apply_fixes_calls_update_tenants_tab_field():
    diff = _diff(field_name="Agreed Rent", sheet="10000", db="12000")
    result = AuditResult(tenants_diffs=[diff])
    db_state = _db_state()

    with patch("src.integrations.gsheets.update_tenants_tab_field",
               new=AsyncMock(return_value={"success": True})) as mock_update, \
         patch("src.integrations.gsheets.trigger_monthly_sheet_sync"):
        fixes = await apply_fixes(result, db_state)

    mock_update.assert_awaited_once_with("304", "Ravi Kumar", "agreed_rent", "12000")
    assert fixes["fixed"] == 1
    assert fixes["skipped"] == 0
    assert fixes["errors"] == []


@pytest.mark.asyncio
async def test_apply_fixes_multiple_diffs():
    diffs = [
        _diff(field_name="Agreed Rent", db="12000"),
        _diff(field_name="Deposit", db="24000"),
        _diff(field_name="Room", db="304"),
    ]
    result = AuditResult(tenants_diffs=diffs)
    db_state = _db_state()

    with patch("src.integrations.gsheets.update_tenants_tab_field",
               new=AsyncMock(return_value={"success": True})) as mock_update, \
         patch("src.integrations.gsheets.trigger_monthly_sheet_sync"):
        fixes = await apply_fixes(result, db_state)

    assert mock_update.await_count == 3
    assert fixes["fixed"] == 3


@pytest.mark.asyncio
async def test_apply_fixes_unknown_field_is_skipped():
    diff = _diff(field_name="UnknownField", db="whatever")
    result = AuditResult(tenants_diffs=[diff])
    db_state = _db_state()

    with patch("src.integrations.gsheets.update_tenants_tab_field",
               new=AsyncMock()) as mock_update, \
         patch("src.integrations.gsheets.trigger_monthly_sheet_sync"):
        fixes = await apply_fixes(result, db_state)

    mock_update.assert_not_awaited()
    assert fixes["skipped"] == 1
    assert fixes["fixed"] == 0


@pytest.mark.asyncio
async def test_apply_fixes_gsheets_error_recorded():
    diff = _diff(field_name="Agreed Rent", db="12000")
    result = AuditResult(tenants_diffs=[diff])
    db_state = _db_state()

    with patch("src.integrations.gsheets.update_tenants_tab_field",
               new=AsyncMock(return_value={"success": False, "error": "row not found"})), \
         patch("src.integrations.gsheets.trigger_monthly_sheet_sync"):
        fixes = await apply_fixes(result, db_state)

    assert fixes["fixed"] == 0
    assert len(fixes["errors"]) == 1
    assert "row not found" in fixes["errors"][0]


@pytest.mark.asyncio
async def test_apply_fixes_exception_is_captured():
    diff = _diff(field_name="Agreed Rent", db="12000")
    result = AuditResult(tenants_diffs=[diff])
    db_state = _db_state()

    with patch("src.integrations.gsheets.update_tenants_tab_field",
               new=AsyncMock(side_effect=Exception("network timeout"))), \
         patch("src.integrations.gsheets.trigger_monthly_sheet_sync"):
        fixes = await apply_fixes(result, db_state)

    assert fixes["fixed"] == 0
    assert "network timeout" in fixes["errors"][0]


# ── Tests: apply_fixes with monthly diffs ────────────────────────────────────

@pytest.mark.asyncio
async def test_monthly_diffs_trigger_sync_once():
    monthly_diffs = [
        Diff("April 2026", 10, "9876543210", "Ravi", "Cash", "0", "3000"),
        Diff("April 2026", 11, "9123456789", "Priya", "UPI", "0", "12000"),
    ]
    result = AuditResult(monthly_diffs=monthly_diffs)
    db_state = _db_state()

    with patch("src.integrations.gsheets.update_tenants_tab_field",
               new=AsyncMock()), \
         patch("src.integrations.gsheets.trigger_monthly_sheet_sync") as mock_sync:
        fixes = await apply_fixes(result, db_state)

    mock_sync.assert_called_once()
    # Both monthly diffs counted as fixed by the single sync call
    assert fixes["fixed"] == 2


@pytest.mark.asyncio
async def test_no_monthly_diffs_no_sync():
    result = AuditResult(tenants_diffs=[])
    db_state = _db_state()

    with patch("src.integrations.gsheets.update_tenants_tab_field",
               new=AsyncMock(return_value={"success": True})), \
         patch("src.integrations.gsheets.trigger_monthly_sheet_sync") as mock_sync:
        await apply_fixes(result, db_state)

    mock_sync.assert_not_called()


# ── Tests: empty result ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_apply_fixes_empty_result_no_calls():
    result = AuditResult()
    db_state = _db_state()

    with patch("src.integrations.gsheets.update_tenants_tab_field",
               new=AsyncMock()) as mock_update, \
         patch("src.integrations.gsheets.trigger_monthly_sheet_sync") as mock_sync:
        fixes = await apply_fixes(result, db_state)

    mock_update.assert_not_awaited()
    mock_sync.assert_not_called()
    assert fixes == {"fixed": 0, "skipped": 0, "errors": []}


# ── Tests: field mapping completeness ────────────────────────────────────────

def test_audit_field_mapping_covers_all_diff_fields():
    """Every field the diff engine emits must have a gsheets key or be deliberately absent."""
    # Fields the diff engine actually emits (from _diff_tenants):
    emitted_by_diff_engine = {"Room", "Agreed Rent", "Deposit", "Notice Date", "Checkout Date"}
    for f in emitted_by_diff_engine:
        assert f in _AUDIT_FIELD_TO_GSHEETS, (
            f"Diff field {f!r} not in _AUDIT_FIELD_TO_GSHEETS — auto-fix will skip it"
        )


def test_gsheets_keys_are_valid():
    """All mapped gsheets keys must be accepted by update_tenants_tab_field."""
    from src.integrations.gsheets import _TENANTS_FIELD_TO_HEADER
    for diff_field, gsheets_key in _AUDIT_FIELD_TO_GSHEETS.items():
        assert gsheets_key in _TENANTS_FIELD_TO_HEADER, (
            f"audit field {diff_field!r} maps to gsheets key {gsheets_key!r} "
            f"which isn't in _TENANTS_FIELD_TO_HEADER"
        )


# ── Tests: run_audit_with_db returns AuditResult + dict ──────────────────────

@pytest.mark.asyncio
async def test_run_audit_with_db_returns_tuple():
    """run_audit_with_db must return (AuditResult, dict) — test the shape without hitting sheet/DB."""
    fake_db = {"tenants": {}, "monthly": {}}

    # Patch all I/O so no network calls happen
    with patch("src.services.sheet_audit._read_sheets",
               return_value=([], [], "April 2026")), \
         patch("src.services.sheet_audit._fetch_db_state",
               new=AsyncMock(return_value=fake_db)):
        from src.services.sheet_audit import run_audit_with_db
        result, db_state = await run_audit_with_db()

    assert isinstance(result, AuditResult)
    assert isinstance(db_state, dict)
    assert "tenants" in db_state
    assert "monthly" in db_state
