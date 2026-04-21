"""Tests for DEPOSIT_CHANGE confirm gate.

Regression: during E2E testing "1" was interpreted as a new deposit
value and corrupted Pooja's deposit (6500 -> 1) because
DEPOSIT_CHANGE_AMT had no confirm gate. Now the amount step must
transition to a DEPOSIT_CHANGE pending (Yes/1 confirm) before any
DB write. These tests lock in:

  (a) confirm "yes" on DEPOSIT_CHANGE applies the change
  (b) confirm "1" on DEPOSIT_CHANGE applies the change
  (c) "cancel" on DEPOSIT_CHANGE aborts without DB write
  (d) numeric reply on DEPOSIT_CHANGE_AMT saves a confirm pending
      instead of writing immediately

All tests use mocks / stubs — no real DB is touched.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.whatsapp.handlers.owner_handler import resolve_pending_action


def _make_pending(intent: str, action_data: dict, choices: list | None = None):
    return SimpleNamespace(
        id=1,
        phone="+917845952289",
        intent=intent,
        action_data=json.dumps(action_data),
        choices=json.dumps(choices or []),
        resolved=False,
    )


def _make_session_with_tenancy(deposit: int = 6500, room_number: str = "201"):
    """Fake AsyncSession whose .get(Tenancy, id) returns a stub, .get(Room, id) too."""
    tenancy = SimpleNamespace(id=42, security_deposit=deposit, room_id=7)
    room = SimpleNamespace(id=7, room_number=room_number)

    async def _get(model, id_):
        name = getattr(model, "__name__", str(model))
        if name == "Tenancy":
            return tenancy
        if name == "Room":
            return room
        return None

    session = MagicMock()
    session.get = AsyncMock(side_effect=_get)
    session.add = MagicMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    return session, tenancy


@pytest.mark.asyncio
async def test_confirm_yes_applies_change():
    # Empty choices so text "yes" falls through the numeric-choice gate
    # into the DEPOSIT_CHANGE text handler. (With 2 choices, the resolver
    # re-prompts for a numeric 1/2 — users either tap 1 or type the word.)
    pending = _make_pending(
        "DEPOSIT_CHANGE",
        {"tenancy_id": 42, "tenant_name": "Pooja",
         "new_amount": 15000, "old_amount": 6500},
        [],
    )
    session, _ = _make_session_with_tenancy()

    with patch(
        "src.whatsapp.handlers.account_handler._do_deposit_change",
        new=AsyncMock(return_value="Deposit updated -> Rs.15,000"),
    ) as m:
        reply = await resolve_pending_action(pending, "yes", session)

    m.assert_awaited_once()
    kwargs = m.await_args.kwargs
    assert kwargs["tenancy_id"] == 42
    assert kwargs["new_amount"] == 15000
    assert kwargs["tenant_name"] == "Pooja"
    assert "Deposit updated" in reply


@pytest.mark.asyncio
async def test_confirm_numeric_one_applies_change():
    """Regression: "1" on a DEPOSIT_CHANGE confirm pending must mean YES."""
    pending = _make_pending(
        "DEPOSIT_CHANGE",
        {"tenancy_id": 42, "tenant_name": "Pooja",
         "new_amount": 15000, "old_amount": 6500},
        [{"seq": 1, "label": "Yes, update"}, {"seq": 2, "label": "No, cancel"}],
    )
    session, _ = _make_session_with_tenancy()

    with patch(
        "src.whatsapp.handlers.account_handler._do_deposit_change",
        new=AsyncMock(return_value="Deposit updated -> Rs.15,000"),
    ) as m:
        reply = await resolve_pending_action(pending, "1", session)

    m.assert_awaited_once()
    assert m.await_args.kwargs["new_amount"] == 15000


@pytest.mark.asyncio
async def test_cancel_aborts_without_db_write():
    pending = _make_pending(
        "DEPOSIT_CHANGE",
        {"tenancy_id": 42, "tenant_name": "Pooja",
         "new_amount": 15000, "old_amount": 6500},
        [{"seq": 1, "label": "Yes, update"}, {"seq": 2, "label": "No, cancel"}],
    )
    session, tenancy = _make_session_with_tenancy()

    with patch(
        "src.whatsapp.handlers.account_handler._do_deposit_change",
        new=AsyncMock(),
    ) as m:
        reply = await resolve_pending_action(pending, "cancel", session)

    m.assert_not_awaited()
    assert tenancy.security_deposit == 6500  # untouched
    assert "ancel" in reply  # "Cancelled" or similar


@pytest.mark.asyncio
async def test_amount_step_saves_confirm_pending_not_immediate_write():
    """The core bug fix: DEPOSIT_CHANGE_AMT + numeric reply must NOT
    call _do_deposit_change immediately — it must save a DEPOSIT_CHANGE
    confirm pending for a follow-up yes/no.
    """
    pending = _make_pending(
        "DEPOSIT_CHANGE_AMT",
        {"tenancy_id": 42, "tenant_name": "Pooja"},
        [],
    )
    session, tenancy = _make_session_with_tenancy(deposit=6500)

    save_pending_mock = AsyncMock()

    with patch(
        "src.whatsapp.handlers.account_handler._do_deposit_change",
        new=AsyncMock(),
    ) as m_do, patch(
        "src.whatsapp.handlers._shared._save_pending",
        new=save_pending_mock,
    ):
        reply = await resolve_pending_action(pending, "1", session)

    # Critical: no DB write happened.
    m_do.assert_not_awaited()
    assert tenancy.security_deposit == 6500

    # A DEPOSIT_CHANGE confirm pending was saved with the amount 1.
    save_pending_mock.assert_awaited_once()
    args, kwargs = save_pending_mock.await_args
    # _save_pending(phone, intent, action_data, choices, session)
    assert args[1] == "DEPOSIT_CHANGE"
    assert args[2]["new_amount"] == 1
    assert args[2]["old_amount"] == 6500
    # Confirm prompt echoes old and new.
    assert "6,500" in reply or "6500" in reply
    assert "confirm" in reply.lower()
