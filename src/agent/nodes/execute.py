"""
Execute node — looks up the confirmed tool in the registry and calls it.
Tools are registered by importing their module (see end of this file).
"""
from __future__ import annotations

from typing import Any

from langgraph.types import RunnableConfig
from ..state import AgentState

_TOOL_REGISTRY: dict[str, Any] = {}


def register_tool(name: str, fn) -> None:
    _TOOL_REGISTRY[name] = fn


async def execute_node(state: AgentState, config: RunnableConfig) -> dict:
    tool_name = state.get("pending_tool")
    if not tool_name or tool_name not in _TOOL_REGISTRY:
        return {
            "reply": f"Internal error: tool '{tool_name}' not registered. Please try again.",
            "pending_tool": None,
            "intent": None,
            "entities": {},
            "clarify_question": None,
            "error": f"tool_not_found:{tool_name}",
        }

    session  = config["configurable"]["session"]
    tool_fn  = _TOOL_REGISTRY[tool_name]
    entities = state.get("entities") or {}

    try:
        result = await tool_fn(entities, session)
        return {
            "reply": result.reply,
            "pending_tool": None,
            "intent": None,
            "entities": {},
            "clarify_question": None,
            "error": None,
        }
    except Exception as exc:
        return {
            "reply": f"Something went wrong: {exc}. Please try again.",
            "pending_tool": None,
            "intent": None,
            "entities": {},
            "clarify_question": None,
            "error": str(exc),
        }


def _register_all() -> None:
    from src.agent.tools import checkout as _ct
    from src.agent.tools import payment as _pt
    register_tool("checkout", _ct.run_checkout)
    register_tool("payment",  _pt.run_payment)


try:
    _register_all()
except (ImportError, ModuleNotFoundError):
    pass  # tools registered later once Tasks 8-10 create the modules
