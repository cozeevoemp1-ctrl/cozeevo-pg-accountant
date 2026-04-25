"""
Intent node — calls run_conversation_agent() and maps its output into AgentState.

Does NOT replace conversation_agent.py — calls it and normalises the result.
"""
from __future__ import annotations

from langgraph.types import RunnableConfig

from ..state import AgentState
from src.llm_gateway.agents.conversation_agent import run_conversation_agent

# Required entities per intent. All must be present before routing to confirm.
# NOTE: tenancy_id is injected by _resolve_tenant_entities after DB lookup;
#       the LLM never produces it directly.
_REQUIRED: dict[str, set[str]] = {
    "CHECKOUT":    {"tenancy_id"},
    "PAYMENT_LOG": {"tenancy_id", "amount"},
}

# Maps intent name → tool name in execute registry
_TOOL_MAP = {
    "CHECKOUT":    "checkout",
    "PAYMENT_LOG": "payment",
}

# Intents that need tenant resolution (name → tenancy_id)
_NEEDS_TENANT_RESOLUTION = {"CHECKOUT", "PAYMENT_LOG"}


async def _resolve_tenant_entities(name: str, session, existing_entities: dict) -> dict:
    """
    Look up active tenant by name and inject tenant_id + tenancy_id into entities.

    Returns an update dict with one of:
    - 1 match  → {"entities": {..., tenant_id, tenancy_id}, "clarify_question": None}
    - 0 matches → {"clarify_question": "No active tenant named '...' found."}
    - N matches → {"entities": {..., choices: [...]}, "clarify_question": "Found N..."}
    """
    from src.whatsapp.handlers._shared import _find_active_tenants_by_name, _make_choices

    rows = await _find_active_tenants_by_name(name, session)

    if len(rows) == 1:
        tenant, tenancy, room = rows[0]
        from datetime import date as _date
        return {
            "entities": {
                **existing_entities,
                "tenant_id":    tenant.id,
                "tenancy_id":   tenancy.id,
                "tenant_name":  tenant.name,
                "room":         room.room_number if room else "",
                "checkout_date": existing_entities.get("checkout_date") or _date.today().isoformat(),
            },
            "clarify_question": None,
        }
    elif len(rows) == 0:
        return {
            "clarify_question": f"No active tenant named '{name}' found. Please check the name.",
        }
    else:
        choices = _make_choices(rows)
        labels = "\n".join(f"{c['seq']}. {c['label']}" for c in choices)
        return {
            "entities": {**existing_entities, "choices": choices},
            "clarify_question": (
                f"Found multiple tenants named '{name}':\n{labels}\nReply with the number."
            ),
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

    # ── Fast path: resolve stored disambiguation choice ──────────────────────
    choices = (state.get("entities") or {}).get("choices")
    if choices:
        msg = (state.get("last_message") or "").strip()
        if msg.isdigit():
            idx = int(msg) - 1
            if 0 <= idx < len(choices):
                chosen = choices[idx]
                merged = {k: v for k, v in (state.get("entities") or {}).items() if k != "choices"}
                merged["tenant_id"]  = chosen["tenant_id"]
                merged["tenancy_id"] = chosen["tenancy_id"]
                return {
                    "entities":        merged,
                    "clarify_question": None,
                    "pending_tool":    _TOOL_MAP.get(state.get("intent") or "", None),
                }

    # ── Pass previous clarify question + user reply as context to the LLM ───
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

        # ── Tenant resolution: name → tenancy_id ─────────────────────────────
        if result.intent in _NEEDS_TENANT_RESOLUTION:
            tenant_name = merged.get("tenant_name") or merged.get("name")
            if tenant_name and "tenancy_id" not in merged:
                resolution = await _resolve_tenant_entities(
                    name=tenant_name,
                    session=session,
                    existing_entities=merged,
                )
                if "entities" in resolution:
                    update["entities"] = resolution["entities"]
                if "clarify_question" in resolution:
                    update["clarify_question"] = resolution["clarify_question"]
                    if resolution["clarify_question"]:
                        # If we need to clarify, don't advance to confirm yet
                        update["reply"] = resolution["clarify_question"]

    elif result.action in ("clarify", "ask_options") and result.reply:
        update["clarify_question"] = result.reply
        update["reply"]            = result.reply
        update["pending_tool"]     = None   # don't carry stale tool across clarify rounds

    elif result.action == "converse" and result.reply:
        update["reply"]        = result.reply
        update["intent"]       = "CONVERSE"
        update["pending_tool"] = None
        update["entities"]     = {}

    return update
