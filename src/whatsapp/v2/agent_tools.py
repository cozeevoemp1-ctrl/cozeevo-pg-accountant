"""
src/whatsapp/v2/agent_tools.py
───────────────────────────────
Thin wrappers that call v1 handlers from the v2 LangGraph pipeline.

The Supervisor Agent outputs (agent, topic, intent_type) which get mapped
to a v1 intent string, then the matching v1 handler is called directly.
All DB logic, formatting, and business rules stay in the v1 handlers.

Mapping table: TOPIC_INTENT_MAP
    key:   (agent, topic, intent_type)
    value: v1 intent string (e.g. "PAYMENT_LOG")
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.whatsapp.intent_detector import _extract_entities

# ── topic → v1 intent mapping ─────────────────────────────────────────────────
# Key: (agent, topic, intent_type)   intent_type: ACTION | QUERY | COMPLAINT | FOLLOW_UP | GREETING
# Value: v1 intent string passed to handle_account / handle_owner / etc.

TOPIC_INTENT_MAP: dict[tuple[str, str, str], str] = {
    # Finance agent
    ("finance", "payment",       "ACTION"):   "PAYMENT_LOG",
    ("finance", "payment",       "QUERY"):    "QUERY_TENANT",
    ("finance", "dues",          "QUERY"):    "QUERY_DUES",
    ("finance", "dues",          "ACTION"):   "QUERY_DUES",
    ("finance", "report",        "QUERY"):    "REPORT",
    ("finance", "report",        "ACTION"):   "REPORT",
    ("finance", "expense",       "ACTION"):   "ADD_EXPENSE",
    ("finance", "expense",       "QUERY"):    "QUERY_EXPENSES",
    ("finance", "refund",        "ACTION"):   "ADD_REFUND",
    ("finance", "refund",        "QUERY"):    "QUERY_REFUNDS",
    ("finance", "void",          "ACTION"):   "VOID_PAYMENT",
    ("finance", "rent",          "ACTION"):   "RENT_CHANGE",
    ("finance", "discount",      "ACTION"):   "RENT_DISCOUNT",
    ("finance", "general",       "QUERY"):    "QUERY_DUES",
    # Operations agent
    ("operations", "complaint",  "COMPLAINT"):"COMPLAINT_REGISTER",
    ("operations", "complaint",  "ACTION"):   "COMPLAINT_REGISTER",
    ("operations", "checkout",   "ACTION"):   "CHECKOUT",
    ("operations", "checkin",    "ACTION"):   "ADD_TENANT",
    ("operations", "wifi",       "QUERY"):    "GET_WIFI_PASSWORD",
    ("operations", "occupancy",  "QUERY"):    "QUERY_OCCUPANCY",
    ("operations", "vacant",     "QUERY"):    "QUERY_VACANT_ROOMS",
    ("operations", "expiring",   "QUERY"):    "QUERY_EXPIRING",
    ("operations", "checkins",   "QUERY"):    "QUERY_CHECKINS",
    ("operations", "checkouts",  "QUERY"):    "QUERY_CHECKOUTS",
    ("operations", "vacation",   "ACTION"):   "LOG_VACATION",
    ("operations", "notice",     "ACTION"):   "NOTICE_GIVEN",
    ("operations", "room_status","QUERY"):    "ROOM_STATUS",
    ("operations", "general",    "QUERY"):    "QUERY_OCCUPANCY",
    # Tenant agent
    ("tenant", "dues",           "QUERY"):    "MY_BALANCE",
    ("tenant", "payment",        "QUERY"):    "MY_PAYMENTS",
    ("tenant", "details",        "QUERY"):    "MY_DETAILS",
    ("tenant", "wifi",           "QUERY"):    "GET_WIFI_PASSWORD",
    ("tenant", "complaint",      "COMPLAINT"):"COMPLAINT_REGISTER",
    ("tenant", "complaint",      "ACTION"):   "COMPLAINT_REGISTER",
    ("tenant", "checkout",       "ACTION"):   "CHECKOUT_NOTICE",
    ("tenant", "vacation",       "ACTION"):   "VACATION_NOTICE",
    ("tenant", "general",        "QUERY"):    "MY_BALANCE",
    # Lead agent
    ("lead", "price",            "QUERY"):    "ROOM_PRICE",
    ("lead", "availability",     "QUERY"):    "AVAILABILITY",
    ("lead", "visit",            "ACTION"):   "VISIT_REQUEST",
    ("lead", "room_type",        "QUERY"):    "ROOM_TYPE",
    ("lead", "general",          "QUERY"):    "GENERAL",
}

# Fallback intents per agent when no topic+intent_type match is found
AGENT_FALLBACK: dict[str, str] = {
    "finance":    "QUERY_DUES",
    "operations": "HELP",
    "tenant":     "MY_BALANCE",
    "lead":       "GENERAL",
    "general":    "HELP",
}


def resolve_v1_intent(agent: str, topic: str, intent_type: str) -> str:
    """Map supervisor output (agent, topic, intent_type) to a v1 intent string.

    Falls back to AGENT_FALLBACK[agent] if exact key not found.
    """
    key = (agent, topic, intent_type)
    if key in TOPIC_INTENT_MAP:
        return TOPIC_INTENT_MAP[key]
    # Try without intent_type (topic-only match, any action type)
    for itype in ("ACTION", "QUERY", "COMPLAINT", "FOLLOW_UP"):
        alt = TOPIC_INTENT_MAP.get((agent, topic, itype))
        if alt:
            return alt
    return AGENT_FALLBACK.get(agent, "HELP")


async def run_finance_agent(
    v1_intent: str,
    message: str,
    ctx,
    session: AsyncSession,
) -> str:
    """Extract entities from message and call account_handler.handle_account()."""
    from src.whatsapp.handlers.account_handler import handle_account
    entities = _extract_entities(message, v1_intent)
    return await handle_account(v1_intent, entities, ctx, session)


async def run_operations_agent(
    v1_intent: str,
    message: str,
    ctx,
    session: AsyncSession,
) -> str:
    """Extract entities from message and call owner_handler.handle_owner()."""
    from src.whatsapp.handlers.owner_handler import handle_owner
    entities = _extract_entities(message, v1_intent)
    return await handle_owner(v1_intent, entities, ctx, session)


async def run_tenant_agent(
    v1_intent: str,
    message: str,
    ctx,
    session: AsyncSession,
) -> str:
    """Extract entities from message and call tenant_handler.handle_tenant()."""
    from src.whatsapp.handlers.tenant_handler import handle_tenant
    entities = _extract_entities(message, v1_intent)
    return await handle_tenant(v1_intent, entities, ctx, session)


async def run_lead_agent(
    v1_intent: str,
    message: str,
    ctx,
    session: AsyncSession,
) -> str:
    """Call lead_handler.handle_lead() (no entity extraction needed for leads)."""
    from src.whatsapp.handlers.lead_handler import handle_lead
    return await handle_lead(v1_intent, message, ctx, session)
