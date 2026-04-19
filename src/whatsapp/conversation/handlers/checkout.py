"""
src/whatsapp/conversation/handlers/checkout.py
===============================================
Handler for CHECKOUT + SCHEDULE_CHECKOUT disambiguation.

When user says "checkout Raj" and multiple Raj match, bot asks 1/2/3.
This handler takes the numeric reply, picks the tenant, and routes to:
  - `_do_checkout` if checkout date is in the future (schedule only)
  - `RECORD_CHECKOUT` pending (checklist) if checkout is today/past
"""
from __future__ import annotations

import json
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from ..memory import ConversationMemory
from ..state import ConversationState, UserInput
from ..router import RouteResult, register


def _choices(mem: ConversationMemory) -> list[dict]:
    try:
        return json.loads(mem.pending.choices or "[]")  # type: ignore[union-attr]
    except (json.JSONDecodeError, TypeError):
        return []


def _action_data(mem: ConversationMemory) -> dict:
    try:
        d = json.loads(mem.pending.action_data or "{}")  # type: ignore[union-attr]
    except (json.JSONDecodeError, TypeError):
        return {}
    return d if isinstance(d, dict) else {}


async def _handle(
    mem: ConversationMemory,
    inp: UserInput,
    session: AsyncSession,
) -> RouteResult:
    choices = _choices(mem)
    action = _action_data(mem)

    if not choices:
        return RouteResult(reply="Pending data missing. Please start over.", keep_pending=False)

    # Numeric choice
    if inp.parsed_number is None or not (1 <= inp.parsed_number <= len(choices)):
        options = "\n".join(f"*{c['seq']}*. {c['label']}" for c in choices)
        return RouteResult(
            reply=f"Please reply with a number:\n{options}\n\nOr say *cancel* to stop.",
            keep_pending=True,
        )

    chosen = choices[inp.parsed_number - 1]

    # Parse checkout date from action_data
    date_str = action.get("checkout_date", "")
    try:
        checkout_date_val = date.fromisoformat(date_str) if date_str else date.today()
    except ValueError:
        checkout_date_val = date.today()

    if checkout_date_val > date.today():
        # Future date → schedule only (no checklist)
        from src.whatsapp.handlers.owner_handler import _do_checkout
        reply = await _do_checkout(
            tenancy_id=chosen["tenancy_id"],
            tenant_name=chosen["label"],
            checkout_date_val=checkout_date_val,
            session=session,
        )
        return RouteResult(reply=reply, keep_pending=False)

    # Today/past → transition to RECORD_CHECKOUT checklist
    # Use legacy _save_pending (no state — RECORD_CHECKOUT still in cascade)
    from src.whatsapp.handlers._shared import _save_pending
    from src.whatsapp.handlers.owner_handler import _calc_outstanding_dues
    from src.database.models import Tenancy

    new_action = {
        "step": "ask_cupboard_key",
        "tenancy_id": chosen["tenancy_id"],
        "tenant_name": chosen["label"],
        "checkout_date": date_str,
    }
    await _save_pending(mem.phone, "RECORD_CHECKOUT", new_action, [], session)

    tenancy = await session.get(Tenancy, chosen["tenancy_id"])
    deposit = int(tenancy.security_deposit or 0) if tenancy else 0
    o_rent, o_maint = await _calc_outstanding_dues(chosen["tenancy_id"], session)
    notice_status = "On record" if (tenancy and tenancy.notice_date) else "No notice given"

    reply = (
        f"*Checkout — {chosen['label']}*\n\n"
        f"Deposit held: Rs.{deposit:,}\n"
        f"Unpaid rent: Rs.{int(o_rent):,}\n"
        f"Unpaid maintenance: Rs.{int(o_maint):,}\n"
        f"Notice: {notice_status}\n\n"
        "*Please complete the checklist:*\n\n"
        "*Q1/5* Was the *cupboard/almirah key* returned?\n"
        "Reply: *yes* or *no*"
    )
    # The new RECORD_CHECKOUT pending is already saved (legacy-cascade).
    # Return with keep_pending=False because our CHECKOUT pending is done.
    return RouteResult(reply=reply, keep_pending=False)


# Both intents share identical resolution
register("CHECKOUT", ConversationState.AWAITING_CHOICE)(_handle)
register("SCHEDULE_CHECKOUT", ConversationState.AWAITING_CHOICE)(_handle)
