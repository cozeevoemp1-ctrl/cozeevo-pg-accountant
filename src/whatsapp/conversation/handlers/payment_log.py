"""
src/whatsapp/conversation/handlers/payment_log.py
==================================================
Handlers for PAYMENT_LOG multi-turn flow.

Sub-flows:
  AWAITING_CHOICE       — user must pick tenant from a disambiguation list
  AWAITING_CONFIRMATION — user must confirm amount/mode/month via yes/no

Keeps the business logic where it is (account_handler._do_log_payment_by_ids);
this file is purely the input parsing + state transition layer.
"""
from __future__ import annotations

import json
import re

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
    if isinstance(d, str):  # legacy double-encoded
        try:
            return json.loads(d)
        except (json.JSONDecodeError, TypeError):
            return {}
    return d


@register("PAYMENT_LOG", ConversationState.AWAITING_CHOICE)
async def on_payment_log_choice(
    mem: ConversationMemory,
    inp: UserInput,
    session: AsyncSession,
) -> RouteResult:
    """User must pick a tenant number (1, 2, ...) from a disambiguation.

    Accepts:
      - exact numeric: "1", "2.", "1)" → pick that tenant
      - "all" / "both" → split payment (not yet — reject)
      - any text containing a new amount / mode → correction re-prompt
      - anything else → re-prompt with the list
    """
    choices = _choices(mem)
    action = _action_data(mem)

    if not choices:
        return RouteResult(
            reply="Pending data missing. Please start over.",
            keep_pending=False,
        )

    # 1. Numeric pick
    if inp.parsed_number is not None and 1 <= inp.parsed_number <= len(choices):
        chosen = choices[inp.parsed_number - 1]
        # Delegate to the existing business function — do not duplicate logic
        from src.whatsapp.handlers.account_handler import _do_log_payment_by_ids
        reply = await _do_log_payment_by_ids(
            tenant_id=chosen["tenant_id"],
            tenancy_id=chosen["tenancy_id"],
            amount=action.get("amount", 0),
            mode=action.get("mode", "cash"),
            ctx_name=action.get("logged_by", mem.name or "owner"),
            period_month_str=action.get("period_month", ""),
            session=session,
        )
        # The business function may return __KEEP_PENDING__ on sub-confirmation
        if reply and reply.startswith("__KEEP_PENDING__"):
            return RouteResult(
                reply=reply[len("__KEEP_PENDING__"):],
                keep_pending=True,
                next_state=ConversationState.AWAITING_CONFIRMATION,
                next_intent="CONFIRM_PAYMENT_LOG",
            )
        return RouteResult(reply=reply or "Payment logged.", keep_pending=False)

    # 2. Correction — user typed a new amount or mode while pending
    _MODE_WORDS = {
        "upi": "UPI", "cash": "Cash", "gpay": "GPay", "phonepe": "PhonePe",
        "paytm": "Paytm", "online": "Online", "bank": "Bank Transfer",
        "neft": "NEFT", "cheque": "Cheque", "imps": "IMPS",
    }
    low = inp.raw.lower()
    new_mode = next((label for word, label in _MODE_WORDS.items() if word in low), None)
    amt_m = re.search(r"\b(\d[\d,]+)\b", inp.raw)
    new_amount = float(amt_m.group(1).replace(",", "")) if amt_m else None

    corrected = False
    if new_mode and new_mode != action.get("mode"):
        action["mode"] = new_mode
        corrected = True
    if new_amount and new_amount != action.get("amount") and new_amount > 0:
        action["amount"] = new_amount
        corrected = True
    if corrected:
        mem.pending.action_data = json.dumps(action)  # type: ignore[union-attr]
        await session.flush()
        options = "\n".join(f"*{c['seq']}*. {c['label']}" for c in choices)
        return RouteResult(
            reply=(f"✏️ Updated. Which tenant for Rs.{int(action['amount']):,} "
                   f"({action.get('mode', 'Cash')})?\n\n{options}\n\nOr say *cancel* to stop."),
            keep_pending=True,
        )

    # 3. Anything else — re-prompt
    options = "\n".join(f"*{c['seq']}*. {c['label']}" for c in choices)
    return RouteResult(
        reply=f"Please reply with a number:\n{options}\n\nOr say *cancel* to stop.",
        keep_pending=True,
    )


@register("CONFIRM_PAYMENT_LOG", ConversationState.AWAITING_CONFIRMATION)
async def on_payment_confirm(
    mem: ConversationMemory,
    inp: UserInput,
    session: AsyncSession,
) -> RouteResult:
    """User confirms a staged payment via yes/no.

    Delegates to the existing CONFIRM_PAYMENT_LOG block in owner_handler
    for the heavy lifting — we just ensure input is parsed correctly
    before calling it.
    """
    # Reuse legacy path for the yes-case (big business block); we only
    # handle the clean "no" cancel here to avoid fallthrough bugs.
    if inp.parsed_no:
        return RouteResult(
            reply="❌ Cancelled. Nothing was changed.",
            keep_pending=False,
        )
    # For "yes" or anything else, fall through — returning None from route()
    # would defer to the legacy cascade. We return a RouteResult with the
    # legacy path invoked explicitly.
    from src.whatsapp.handlers.owner_handler import resolve_pending_action
    reply = await resolve_pending_action(mem.pending, inp.raw, session)  # type: ignore[arg-type]
    if reply and reply.startswith("__KEEP_PENDING__"):
        return RouteResult(
            reply=reply[len("__KEEP_PENDING__"):],
            keep_pending=True,
            next_state=ConversationState.AWAITING_CONFIRMATION,
        )
    return RouteResult(reply=reply or "Done.", keep_pending=False)
