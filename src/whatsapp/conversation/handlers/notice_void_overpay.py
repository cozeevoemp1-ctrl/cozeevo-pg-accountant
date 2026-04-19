"""
src/whatsapp/conversation/handlers/notice_void_overpay.py
==========================================================
State handlers for:
  NOTICE_GIVEN         — tenant disambig for recording formal notice
  VOID_WHICH           — pick payment from a void candidate list
  VOID_PAYMENT         — yes/no confirm on voiding a specific payment
  OVERPAYMENT_RESOLVE  — 1-4 choice for surplus cash (advance/deposit/credit/note)

All four delegate to the legacy resolve_pending_action for the heavy
business logic. The framework layer's job is to validate the input is
a valid numeric choice in range, route cleanly, and prevent cross-
intent fallthrough bugs.
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


async def _delegate(
    mem: ConversationMemory, inp: UserInput, session: AsyncSession,
    *, choices_len_override: int | None = None,
) -> RouteResult:
    """Validate numeric choice, then call legacy resolver.

    choices_len_override: some intents (VOID_PAYMENT) expect exactly 2
    choices (yes/no) even if pending.choices is empty — pass a length
    so we accept "1" or "2".
    """
    choices = _choices(mem)
    max_choice = choices_len_override if choices_len_override is not None else len(choices)

    if inp.parsed_number is None or not (1 <= inp.parsed_number <= max_choice):
        if choices:
            options = "\n".join(f"*{c['seq']}*. {c['label']}" for c in choices)
            return RouteResult(
                reply=f"Please reply with a number:\n{options}\n\nOr say *cancel* to stop.",
                keep_pending=True,
            )
        return RouteResult(
            reply=f"Please reply with a number from 1 to {max_choice}, or *cancel*.",
            keep_pending=True,
        )

    # Valid numeric choice — delegate to legacy resolver which handles the rest
    from src.whatsapp.handlers.owner_handler import resolve_pending_action
    reply = await resolve_pending_action(mem.pending, inp.raw, session)  # type: ignore[arg-type]
    if reply and reply.startswith("__KEEP_PENDING__"):
        return RouteResult(reply=reply[len("__KEEP_PENDING__"):], keep_pending=True)
    return RouteResult(reply=reply or "Done.", keep_pending=False)


@register("NOTICE_GIVEN", ConversationState.AWAITING_CHOICE)
async def on_notice_given(mem, inp, session):
    return await _delegate(mem, inp, session)


@register("VOID_WHICH", ConversationState.AWAITING_CHOICE)
async def on_void_which(mem, inp, session):
    return await _delegate(mem, inp, session)


@register("VOID_PAYMENT", ConversationState.AWAITING_CHOICE)
async def on_void_payment_confirm(mem, inp, session):
    # VOID_PAYMENT after VOID_WHICH has 2 choices (Yes/No, seq 1/2).
    # The choices list is populated, so _delegate works as-is.
    return await _delegate(mem, inp, session, choices_len_override=2)


@register("OVERPAYMENT_RESOLVE", ConversationState.AWAITING_CHOICE)
async def on_overpayment_resolve(mem, inp, session):
    # OVERPAYMENT_RESOLVE has 4 fixed choices (advance/deposit/credit/note).
    # Even when pending.choices list is empty (legacy), the seq values
    # 1-4 are accepted by the business logic.
    return await _delegate(mem, inp, session, choices_len_override=4)
