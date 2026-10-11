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

    # Single source with the legacy cascade: schedule (future), day-stay exit, or
    # RECORD_CHECKOUT checklist (today/past, carries exit_date).
    from src.whatsapp.handlers.owner_handler import _resolve_checkout_choice
    reply = await _resolve_checkout_choice(chosen, action, mem.phone, session)
    # A checklist start saves its own RECORD_CHECKOUT pending; this one is done.
    return RouteResult(reply=reply, keep_pending=False)


# Both intents share identical resolution
register("CHECKOUT", ConversationState.AWAITING_CHOICE)(_handle)
register("SCHEDULE_CHECKOUT", ConversationState.AWAITING_CHOICE)(_handle)
