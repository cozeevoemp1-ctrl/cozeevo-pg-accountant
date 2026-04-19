"""
src/whatsapp/conversation/handlers/confirm_add_tenant.py
=========================================================
Yes/No confirmation for adding a new tenant.

On "yes" → delegate to the legacy resolver (CONFIRM_ADD_TENANT block in
owner_handler) which calls `_do_add_tenant` and handles KYC extras.
On "no"  → clean cancel.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ..memory import ConversationMemory
from ..state import ConversationState, UserInput
from ..router import RouteResult, register


@register("CONFIRM_ADD_TENANT", ConversationState.AWAITING_CONFIRMATION)
async def on_confirm_add_tenant(
    mem: ConversationMemory,
    inp: UserInput,
    session: AsyncSession,
) -> RouteResult:
    if inp.parsed_no:
        return RouteResult(
            reply="Tenant check-in cancelled. Nothing was saved.",
            keep_pending=False,
        )
    if inp.parsed_yes:
        # Delegate to legacy block for the full happy-path (tenant create +
        # KYC save + agreement generate). Big business surface — not
        # duplicating here. The legacy block returns a finished reply.
        from src.whatsapp.handlers.owner_handler import resolve_pending_action
        reply = await resolve_pending_action(mem.pending, inp.raw, session)  # type: ignore[arg-type]
        if reply and reply.startswith("__KEEP_PENDING__"):
            return RouteResult(reply=reply[len("__KEEP_PENDING__"):], keep_pending=True)
        return RouteResult(reply=reply or "Done.", keep_pending=False)

    # Neither yes nor no — re-prompt
    return RouteResult(
        reply="Reply *Yes* to add tenant, or *No* to cancel.",
        keep_pending=True,
    )
