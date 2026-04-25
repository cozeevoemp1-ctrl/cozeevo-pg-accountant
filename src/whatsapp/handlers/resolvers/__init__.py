"""Pending-action resolvers.

Each function here handles ONE pending.intent. They're registered in the
PENDING_RESOLVERS dict at the bottom, which `resolve_pending_action()` in
owner_handler.py uses as a dispatch table.

Rules:
- Each resolver takes the same signature: `(pending, reply_text, session,
  action_data, choices, *, media_id, media_type, media_mime) -> Optional[str]`.
- Return the final bot reply string, or `None` if the reply wasn't a valid
  choice. Return `"__KEEP_PENDING__<msg>"` to keep the pending active.
- Never swallow exceptions silently — either handle or let them bubble.
- No nested function definitions. Helpers go to module scope (or _common.py
  if shared).

Plan: docs/superpowers/plans/2026-04-23-phase2-handler-refactor.md
"""
from __future__ import annotations

from .onboarding import (
    resolve_approve_onboarding,
    resolve_checkin_arrival_payment,
    resolve_confirm_checkin_arrival,
)

# Intents not yet in the dispatch table fall back to the legacy if/elif chain
# in owner_handler.resolve_pending_action. Phase 2B/2C migrate the rest.
PENDING_RESOLVERS: dict = {
    "APPROVE_ONBOARDING":        resolve_approve_onboarding,
    "CHECKIN_ARRIVAL_PAYMENT":   resolve_checkin_arrival_payment,
    "CONFIRM_CHECKIN_ARRIVAL":   resolve_confirm_checkin_arrival,
}
