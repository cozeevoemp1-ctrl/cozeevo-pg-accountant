"""
Confirm node — formats a human-readable summary of the proposed action.
Asks the user to reply yes/no. Ends the turn.
Next turn: router sees pending_tool + no clarify_question → yes→execute, no→cancel.
"""
from __future__ import annotations

from langgraph.types import RunnableConfig
from ..state import AgentState

_TEMPLATES: dict[str, str] = {
    "CHECKOUT": (
        "Checking out *{tenant_name}* from room *{room}* on *{checkout_date}*.\n\n"
        "Reply *yes* to confirm or *no* to cancel."
    ),
    "PAYMENT_LOG": (
        "Logging payment of *₹{amount}* for *{tenant_name}* (room {room}) "
        "via *{mode}* for *{month}*.\n\n"
        "Reply *yes* to confirm or *no* to cancel."
    ),
}

_FALLBACK = (
    "Proceeding with: {intent}\n\n"
    "Reply *yes* to confirm or *no* to cancel."
)


async def confirm_node(state: AgentState, config: RunnableConfig) -> dict:
    intent   = state.get("intent") or ""
    entities = state.get("entities") or {}
    template = _TEMPLATES.get(intent, _FALLBACK)
    try:
        reply = template.format(intent=intent, **entities)
    except KeyError:
        reply = _FALLBACK.format(intent=intent)
    return {"reply": reply, "clarify_question": None}
