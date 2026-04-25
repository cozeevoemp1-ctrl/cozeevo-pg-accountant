"""
Router node — fast path for trivial mid-flow inputs.

If we're in confirm state (pending_tool set, no open clarify_question)
and the message is a plain yes/no, skip the LLM entirely.
Everything else goes to the intent node.
"""
from __future__ import annotations

from ..state import AgentState

_YES = frozenset({"yes", "y", "yeah", "yep", "ok", "okay", "confirm", "sure", "done"})
_NO  = frozenset({"no", "n", "nope", "cancel", "stop", "abort", "nevermind", "never mind"})


def route_decision(state: AgentState) -> str:
    msg = (state.get("last_message") or "").strip().lower().rstrip(".!?,;:")

    # Fast path only when: flow in progress AND no open clarify question
    if state.get("pending_tool") and not state.get("clarify_question"):
        if msg in _YES:
            return "execute"
        if msg in _NO:
            return "cancel"

    return "intent"


async def router_node(state: AgentState) -> dict:
    return {"turn_count": state.get("turn_count", 0) + 1}
