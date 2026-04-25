"""
Intent node — calls run_conversation_agent() and maps its output into AgentState.

Does NOT replace conversation_agent.py — calls it and normalises the result.
"""
from __future__ import annotations

from langgraph.types import RunnableConfig

from ..state import AgentState
from src.llm_gateway.agents.conversation_agent import run_conversation_agent

# Required entities per intent. All must be present before routing to confirm.
_REQUIRED: dict[str, set[str]] = {
    "CHECKOUT":    {"tenant_id"},
    "PAYMENT_LOG": {"tenant_id", "amount"},
}

# Maps intent name → tool name in execute registry
_TOOL_MAP = {
    "CHECKOUT":    "checkout",
    "PAYMENT_LOG": "payment",
}


def route_from_intent(state: AgentState) -> str:
    if state.get("clarify_question"):
        return "clarify"

    intent = state.get("intent")
    if not intent:
        return "__end__"

    required = _REQUIRED.get(intent, set())
    entities = state.get("entities") or {}
    missing  = required - set(entities.keys())

    if missing:
        return "clarify"

    if state.get("pending_tool"):
        return "confirm"

    return "__end__"


async def intent_node(state: AgentState, config: RunnableConfig) -> dict:
    session = config["configurable"]["session"]
    pg_id   = config["configurable"].get("pg_id", "")

    # Pass previous clarify question + user reply as context to the LLM
    pending_ctx = ""
    if state.get("clarify_question"):
        pending_ctx = (
            f"Bot asked: {state['clarify_question']}\n"
            f"User replied: {state['last_message']}"
        )

    result = await run_conversation_agent(
        message=state["last_message"],
        role=state["role"],
        phone=state["user_id"].replace("wa:", ""),
        pg_id=pg_id,
        session=session,
        chat_history="",
        pending_context=pending_ctx,
    )

    update: dict = {}

    if result.action == "classify" and result.intent:
        merged = dict(state.get("entities") or {})
        merged.update(result.entities or {})
        update["intent"]           = result.intent
        update["entities"]         = merged
        update["clarify_question"] = None
        if result.intent in _TOOL_MAP:
            update["pending_tool"] = _TOOL_MAP[result.intent]

    elif result.action in ("clarify", "ask_options") and result.reply:
        update["clarify_question"] = result.reply
        update["reply"]            = result.reply

    elif result.action == "converse" and result.reply:
        update["reply"]  = result.reply
        update["intent"] = "CONVERSE"

    return update
