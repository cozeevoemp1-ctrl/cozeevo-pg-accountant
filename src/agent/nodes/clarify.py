"""
Clarify node — sends the clarifying question (already set by intent node) as the reply.
Ends the turn. Next turn: router sees clarify_question is set → routes to intent.
"""
from __future__ import annotations

from langgraph.types import RunnableConfig
from ..state import AgentState


async def clarify_node(state: AgentState, config: RunnableConfig) -> dict:
    question = state.get("clarify_question") or "Could you clarify?"
    return {"reply": question}
