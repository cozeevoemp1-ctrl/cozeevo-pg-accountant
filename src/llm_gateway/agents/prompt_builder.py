"""Builds dynamic system prompts from pg_config for ConversationAgent."""
from __future__ import annotations

# Intent catalogs per role — these are DEFAULT intents. PGs can add custom_intents via pg_config.

OWNER_INTENTS = """PAYMENT_LOG: tenant paid rent ("Raj paid 15000", "received 8k from 203")
QUERY_DUES: who hasn't paid, pending list, outstanding balances
QUERY_TENANT: balance/details of a specific tenant or room ("Raj balance", "room 203")
ADD_TENANT: add new tenant, check-in, new admission
CHECKOUT: tenant leaving/vacating NOW or today
SCHEDULE_CHECKOUT: tenant leaving on a specific FUTURE date
NOTICE_GIVEN: tenant gave advance notice of leaving (future timeframe required)
ADD_EXPENSE: log a property expense (electricity, salary, plumber)
QUERY_EXPENSES: check expenses this month
VOID_PAYMENT: cancel/reverse a payment
VOID_EXPENSE: cancel/reverse an expense
ADD_REFUND: record a deposit refund
QUERY_REFUNDS: pending refunds
REPORT: monthly summary, P&L, collection report
QUERY_VACANT_ROOMS: vacant/empty rooms, available beds
QUERY_OCCUPANCY: occupancy percentage, how full
COMPLAINT_REGISTER: report a problem (no water, broken fan)
COMPLAINT_UPDATE: resolve/close a complaint
QUERY_COMPLAINTS: check complaint status
ADD_CONTACT: add vendor/service contact with phone
QUERY_CONTACTS: look up vendor contact
REMINDER_SET: set a reminder
ACTIVITY_LOG: log an activity
QUERY_ACTIVITY: show activity log
QUERY_FLEXIBLE: any data question not covered above — "how many female tenants", "rooms with AC on floor 3", "total rent collected in March", "which rooms have single occupant"
HELP: help, menu, commands"""

TENANT_INTENTS = """MY_BALANCE: how much do I owe, my dues
MY_PAYMENTS: my payment history, receipts
MY_DETAILS: my room details, rent, check-in date
HELP: help, hi, hello"""

LEAD_INTENTS = """ROOM_PRICE: price, rent, cost, rates
AVAILABILITY: available rooms, vacancy
ROOM_TYPE: single, double, sharing, AC
VISIT_REQUEST: visit, tour, show room
GENERAL: general enquiry or conversation"""


def build_system_prompt(
    pg_config: dict,
    role: str,
    examples: list[dict],
    chat_history: str,
    pending_context: str,
) -> str:
    """Build the complete system prompt for ConversationAgent from pg_config."""

    if role in ("admin", "owner", "receptionist"):
        intents = OWNER_INTENTS
    elif role == "tenant":
        intents = TENANT_INTENTS
    else:
        intents = LEAD_INTENTS

    custom = pg_config.get("custom_intents") or []
    if custom:
        custom_text = "\n".join(f"{c['name']}: {c['description']}" for c in custom if isinstance(c, dict))
        if custom_text:
            intents += "\n" + custom_text

    buildings = pg_config.get("buildings") or []
    buildings_text = ", ".join(
        f"{b['name']} ({b.get('floors', '?')} floors, {b.get('type', 'mixed')})"
        for b in buildings if isinstance(b, dict)
    ) or "Not configured"

    if examples:
        examples_text = "\n".join(
            f'- "{ex["message"]}" -> {ex["intent"]}'
            for ex in examples[:15]
        )
    else:
        examples_text = "No examples yet — this PG is still learning."

    pricing = pg_config.get("pricing") or {}
    pricing_text = ", ".join(f"{k}: {v}" for k, v in pricing.items()) if pricing else "Not configured"

    prompt = f"""You are {pg_config['brand_name']}, an AI assistant for {pg_config['pg_name']}.
{pg_config.get('brand_voice', '')}

ROLE OF CURRENT USER: {role}

BUILDINGS: {buildings_text}
PRICING: {pricing_text}

AVAILABLE INTENTS FOR THIS USER:
{intents}

EXAMPLES OF HOW USERS AT THIS PG TALK:
{examples_text}

INSTRUCTIONS:
1. Analyze the user's message and determine if it matches an intent or is just conversation.
2. If it's an intent, classify it with confidence 0.0-1.0 and extract entities (name, amount, room, month, mode).
3. If confidence > 0.9, return action="classify" with the intent.
4. If confidence 0.6-0.9, return action="ask_options" with top 2-3 intent options and a friendly question.
5. If confidence < 0.6, return action="clarify" with a helpful question.
6. If it's just conversation (greeting, thanks, question about you, small talk), return action="converse" with a natural reply.
7. If the user is correcting a previous classification, return action="correct" with the correction details.
8. Always include reasoning for your classification — this helps the system learn.
9. Keep replies concise — this is WhatsApp, not email.
10. Never make up information. If you don't know something, say so.

CHAT HISTORY:
{chat_history or 'No prior messages.'}

PENDING ACTION:
{pending_context or 'No pending action.'}

Respond with valid JSON matching ConversationResult schema:
{{"action": "classify|ask_options|clarify|converse|correct", "intent": "INTENT_NAME or null", "confidence": 0.0-1.0, "entities": {{}}, "options": ["INTENT1","INTENT2"] or null, "correction": null, "reply": "text or null", "reasoning": "why"}}"""

    return prompt
