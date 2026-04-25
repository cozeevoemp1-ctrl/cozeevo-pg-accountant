"""Cancel node — clears pending flow state and tells the user."""
from __future__ import annotations

from langgraph.types import RunnableConfig
from ..state import AgentState


async def cancel_node(state: AgentState, config: RunnableConfig) -> dict:
    return {
        "intent": None,
        "entities": {},
        "pending_tool": None,
        "clarify_question": None,
        "reply": "Action cancelled. What else can I help with?",
    }
