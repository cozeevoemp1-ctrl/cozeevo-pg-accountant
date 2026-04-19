"""
src/whatsapp/conversation/router.py
====================================
State-based dispatcher.

Given a ConversationMemory + UserInput, route to the correct handler.
Dispatch table is (intent, state) -> coroutine. No if-elif cascade.

Handlers register themselves via the @register decorator:

    @register("PAYMENT_LOG", ConversationState.AWAITING_CHOICE)
    async def on_payment_log_choice(mem, inp, session):
        ...

Result type
-----------
Handlers return a RouteResult:
  - `reply`   : str to send to user
  - `keep_pending` : bool — True = don't mark pending resolved
                     (used for correction re-prompts)
  - `next_state`   : Optional[ConversationState] — if set, update pending.state
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from .state import ConversationState, UserInput
from .memory import ConversationMemory


@dataclass
class RouteResult:
    """What a handler returns."""
    reply: str
    keep_pending: bool = False          # True: pending stays unresolved (re-prompt)
    next_state: Optional[ConversationState] = None  # if set, mutate pending.state
    next_intent: Optional[str] = None   # if set, mutate pending.intent


# handler signature: async (mem, inp, session) -> RouteResult
Handler = Callable[[ConversationMemory, UserInput, AsyncSession], Awaitable[RouteResult]]


_REGISTRY: dict[tuple[str, ConversationState], Handler] = {}


def register(intent: str, state: ConversationState):
    """Decorator — bind a handler to (intent, state)."""
    def wrap(fn: Handler) -> Handler:
        key = (intent.upper(), state)
        if key in _REGISTRY:
            raise RuntimeError(f"handler already registered for {key}")
        _REGISTRY[key] = fn
        return fn
    return wrap


def is_framework_intent(intent: Optional[str], state: Optional[str]) -> bool:
    """True if (intent, state) has a handler registered here.

    Used by chat_api to decide: route through new framework, or fall
    back to legacy resolve_pending_action.
    """
    if not intent:
        return False
    st = ConversationState.from_str(state) if state else None
    if st is None:
        return False
    return (intent.upper(), st) in _REGISTRY


async def route(
    mem: ConversationMemory,
    inp: UserInput,
    session: AsyncSession,
) -> Optional[RouteResult]:
    """Look up the handler for the current (intent, state) and run it.

    Returns None if no handler is registered — caller should fall back
    to legacy path.

    Global short-circuits applied here (NOT per-handler):
      - "cancel" → resolve pending, return cancellation message
    """
    if not mem.has_pending():
        return None
    intent = mem.pending_intent() or ""
    state_str = mem.pending_state()
    state = ConversationState.from_str(state_str)

    # Global cancel — any pending, any state
    if inp.parsed_cancel:
        return RouteResult(
            reply="❌ Cancelled. Nothing was changed.",
            keep_pending=False,
        )

    handler = _REGISTRY.get((intent.upper(), state))
    if handler is None:
        return None

    return await handler(mem, inp, session)


# Import all handlers here so they self-register at module load.
# Keep this import list in sync with files under handlers/.
from .handlers import payment_log          # noqa: E402,F401
from .handlers import checkout             # noqa: E402,F401
from .handlers import confirm_add_tenant   # noqa: E402,F401
from .handlers import confirm_add_expense  # noqa: E402,F401
from .handlers import notice_void_overpay  # noqa: E402,F401
