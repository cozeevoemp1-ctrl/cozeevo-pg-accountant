"""
LangGraph vs Regex Intent Classifier — Head-to-Head Test
=========================================================
Tests 1000+ scenarios across:
  - Single-turn: all 544 from scenarios_500.json + 200 synthetic edge cases
  - Multi-turn: 30 conversations (the key advantage of LangGraph — context memory)

Run:
    python tests/test_langgraph_intent.py

Output:
    tests/results/langgraph_vs_regex_TIMESTAMP.json
    Console summary table

Key question: Does LangGraph+Groq (with conversation memory) outperform
the stateless regex pipeline? Especially on follow-up queries like
"January cash?" after a report conversation.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from dotenv import load_dotenv

load_dotenv()

# ── Windows UTF-8 console fix ─────────────────────────────────────────────────
import io as _io
if isinstance(sys.stdout, _io.TextIOWrapper):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
if isinstance(sys.stderr, _io.TextIOWrapper):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

# ── LangGraph imports ─────────────────────────────────────────────────────────
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

# ── Local imports ─────────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.whatsapp.intent_detector import detect_intent

# ── Config ────────────────────────────────────────────────────────────────────
GROQ_API_KEY   = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL     = "llama-3.1-8b-instant"   # 14,400 req/day free — safe for 1000 tests
CONCURRENCY    = 8                          # parallel Groq calls (safe for free tier)
RESULTS_DIR    = Path(__file__).parent / "results"
SCENARIOS_FILE = Path(__file__).parent / "scenarios_500.json"

# ── LangGraph State ───────────────────────────────────────────────────────────

class IntentState(TypedDict):
    messages:    Annotated[list, add_messages]  # full conversation history (memory)
    role:        str
    intent:      str
    confidence:  float
    entities:    dict


# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an intent classifier for a PG (paying guest hostel) WhatsApp bot called Artha.

Classify the LATEST user message. Use the FULL conversation history for context — prior messages matter.

ROLE: {role}

━━━ ADMIN / POWER_USER intents ━━━
PAYMENT_LOG      — Someone paid rent. "Raj paid 15000 upi", "received 8k from room 203", "Arjun 12000 cash"
REPORT           — Monthly financial summary, cash/UPI totals. "monthly report", "how much cash in march?",
                   "february?", "january?", "january 2025 cash?", "last month collections", "march summary"
QUERY_DUES       — Who hasn't paid. "who hasn't paid", "pending dues", "defaulters", "send dues"
QUERY_TENANT     — Specific tenant info. "Raj balance", "room 203 details", "how much does Suresh owe"
ADD_EXPENSE      — Log expense. "electricity 4500", "plumber paid 2500 cash", "maintenance 3000"
ADD_TENANT       — New tenant. "add tenant Raj 9876543210 room 201", "checkin", "new admission"
CHECKOUT         — Tenant leaving. "checkout Raj", "Raj vacating", "Suresh leaving"
SCHEDULE_CHECKOUT — Future checkout date. "Raj leaving March 31", "checkout on 15 April"
REMINDER_SET     — Set reminder. "remind Raj tomorrow", "reminder Deepak March 10"
GET_WIFI_PASSWORD — WiFi credentials.
QUERY_VACANT_ROOMS — Empty rooms. "vacant rooms", "which rooms are empty"
QUERY_OCCUPANCY  — Occupancy stats. "how many tenants", "occupancy rate"
QUERY_CHECKINS   — Who checked in this month. "who joined", "new arrivals"
QUERY_CHECKOUTS  — Who checked out. "who left", "checkouts this month"
QUERY_EXPENSES   — Expense history. "total expenses march", "what did we spend"
VOID_PAYMENT     — Cancel a payment. "void payment", "wrong entry"
RULES            — PG rules. "show rules", "what are the rules"
HELP             — Help menu. "help", "menu", "hi", "hello"

━━━ TENANT intents ━━━
MY_BALANCE       — Own dues. "my balance", "how much do I owe"
MY_PAYMENTS      — Own payment history. "my payments", "payment history"
MY_DETAILS       — Own room/profile. "my room", "my details"
GET_WIFI_PASSWORD — WiFi password.
COMPLAINT_REGISTER — Log complaint. "tap not working", "fan broken", "wifi slow"
HELP             — Help/greeting.

━━━ LEAD intents ━━━
ROOM_PRICE       — Pricing. "how much is rent", "what are the charges"
AVAILABILITY     — Room availability. "any rooms available"
ROOM_TYPE        — Room types. "single room", "sharing room"
VISIT_REQUEST    — Want to visit. "can I come see the room"
GENERAL          — General conversation.

━━━ CRITICAL CONTEXT RULES ━━━
1. If recent messages show a REPORT conversation (asking about monthly totals, cash, UPI collections),
   and the latest message is a SHORT follow-up like "february?", "january?", "last month?",
   "january 2025?", "what about march?" — classify as REPORT, NOT PAYMENT_LOG.

2. If latest message is just a month name or "Month Year" (e.g. "January 2025"), check context:
   - After a report conversation → REPORT
   - Standalone with no context → REPORT (asking for that month's data)

3. "cash?" or "upi?" after a report → REPORT (asking cash vs UPI split)

4. Short confirmations ("yes", "ok", "confirm", "done") after a pending action → CONFIRMATION

Respond ONLY with valid JSON on one line:
{{"intent": "INTENT_NAME", "confidence": 0.95, "entities": {{"name": "Raj", "month": 3, "amount": 15000, "payment_mode": "cash"}}}}
"""


# ── LangGraph graph ───────────────────────────────────────────────────────────

_llm: ChatGroq | None = None

def _get_llm() -> ChatGroq:
    global _llm
    if _llm is None:
        _llm = ChatGroq(
            api_key=GROQ_API_KEY,
            model=GROQ_MODEL,
            temperature=0.0,
            max_tokens=200,
        )
    return _llm


async def node_classify(state: IntentState) -> dict:
    """Classify the latest message using full conversation history."""
    role    = state.get("role", "admin")
    llm     = _get_llm()
    system  = SystemMessage(content=SYSTEM_PROMPT.format(role=role))
    history = list(state["messages"])

    try:
        response = await llm.ainvoke([system] + history)
        raw      = response.content.strip()

        # Extract JSON — LLM sometimes wraps in markdown
        if "```" in raw:
            raw = raw.split("```")[1].replace("json", "").strip()
        if raw.startswith("{"):
            data = json.loads(raw)
        else:
            # Try to find JSON in the response
            import re
            m = re.search(r'\{.*\}', raw, re.DOTALL)
            data = json.loads(m.group()) if m else {}

        return {
            "intent":     data.get("intent", "UNKNOWN"),
            "confidence": float(data.get("confidence", 0.5)),
            "entities":   data.get("entities", {}),
        }
    except Exception as e:
        return {"intent": "ERROR", "confidence": 0.0, "entities": {"error": str(e)}}


def _build_graph() -> Any:
    builder = StateGraph(IntentState)
    builder.add_node("classify", node_classify)
    builder.set_entry_point("classify")
    builder.add_edge("classify", END)
    checkpointer = MemorySaver()
    return builder.compile(checkpointer=checkpointer)


_graph = _build_graph()


# ── Test data ─────────────────────────────────────────────────────────────────

def load_single_turn_tests() -> list[dict]:
    """Load 544 tests from scenarios_500.json."""
    tests = []
    if SCENARIOS_FILE.exists():
        data = json.loads(SCENARIOS_FILE.read_text(encoding="utf-8"))
        for s in data.get("scenarios", []):
            tests.append({
                "id":       s["id"],
                "type":     "single",
                "role":     s.get("role", "admin"),
                "message":  s["message"],
                "expected": s.get("expected_intent", s.get("intent", "")),
                "tags":     s.get("tags", []),
            })
    return tests


def synthetic_edge_cases() -> list[dict]:
    """~200 tricky edge cases that regex struggles with."""
    admin = "admin"
    tenant = "tenant"
    lead = "lead"
    return [
        # ── Context-ambiguous report queries (the "January cash?" bug) ──────
        {"id": "E001", "type": "single", "role": admin, "message": "January 2025 cash?",           "expected": "REPORT"},
        {"id": "E002", "type": "single", "role": admin, "message": "February cash",                "expected": "REPORT"},
        {"id": "E003", "type": "single", "role": admin, "message": "March 2026?",                  "expected": "REPORT"},
        {"id": "E004", "type": "single", "role": admin, "message": "cash this month",              "expected": "REPORT"},
        {"id": "E005", "type": "single", "role": admin, "message": "last month upi?",              "expected": "REPORT"},
        {"id": "E006", "type": "single", "role": admin, "message": "december collections",         "expected": "REPORT"},
        {"id": "E007", "type": "single", "role": admin, "message": "november cash total",          "expected": "REPORT"},
        {"id": "E008", "type": "single", "role": admin, "message": "total upi march",              "expected": "REPORT"},
        {"id": "E009", "type": "single", "role": admin, "message": "what was collected in jan",    "expected": "REPORT"},
        {"id": "E010", "type": "single", "role": admin, "message": "feb 2026 total",               "expected": "REPORT"},
        # ── Payment shortcuts ────────────────────────────────────────────────
        {"id": "E011", "type": "single", "role": admin, "message": "Arjun 12000 cash",             "expected": "PAYMENT_LOG"},
        {"id": "E012", "type": "single", "role": admin, "message": "15000 Raj gpay",               "expected": "PAYMENT_LOG"},
        {"id": "E013", "type": "single", "role": admin, "message": "Kumar paid 8500",              "expected": "PAYMENT_LOG"},
        {"id": "E014", "type": "single", "role": admin, "message": "received 7k from Suresh upi",  "expected": "PAYMENT_LOG"},
        {"id": "E015", "type": "single", "role": admin, "message": "Deepak payment received",      "expected": "PAYMENT_LOG"},
        {"id": "E016", "type": "single", "role": admin, "message": "jama kiya 10000 Vikram",       "expected": "PAYMENT_LOG"},
        {"id": "E017", "type": "single", "role": admin, "message": "Priya paid ten thousand",      "expected": "PAYMENT_LOG"},
        {"id": "E018", "type": "single", "role": admin, "message": "8000 from room 301 cash",      "expected": "PAYMENT_LOG"},
        # ── Expense edge cases ───────────────────────────────────────────────
        {"id": "E019", "type": "single", "role": admin, "message": "electricity 8400",             "expected": "ADD_EXPENSE"},
        {"id": "E020", "type": "single", "role": admin, "message": "internet 1800",                "expected": "ADD_EXPENSE"},
        {"id": "E021", "type": "single", "role": admin, "message": "maintenance 3000 upi",         "expected": "ADD_EXPENSE"},
        {"id": "E022", "type": "single", "role": admin, "message": "paid electricity bill 9200",   "expected": "ADD_EXPENSE"},
        {"id": "E023", "type": "single", "role": admin, "message": "water bill 450",               "expected": "ADD_EXPENSE"},
        {"id": "E024", "type": "single", "role": admin, "message": "plumber 2500 cash",            "expected": "ADD_EXPENSE"},
        {"id": "E025", "type": "single", "role": admin, "message": "5000 cash maintenance",        "expected": "ADD_EXPENSE"},
        {"id": "E026", "type": "single", "role": admin, "message": "generator diesel 3500",        "expected": "ADD_EXPENSE"},
        {"id": "E027", "type": "single", "role": admin, "message": "paid salary 15000",            "expected": "ADD_EXPENSE"},
        {"id": "E028", "type": "single", "role": admin, "message": "security guard wages 12000",   "expected": "ADD_EXPENSE"},
        # ── Dues / pending ───────────────────────────────────────────────────
        {"id": "E029", "type": "single", "role": admin, "message": "who hasn't paid this month",   "expected": "QUERY_DUES"},
        {"id": "E030", "type": "single", "role": admin, "message": "show pending dues",            "expected": "QUERY_DUES"},
        {"id": "E031", "type": "single", "role": admin, "message": "defaulters list",              "expected": "QUERY_DUES"},
        {"id": "E032", "type": "single", "role": admin, "message": "send dues",                    "expected": "QUERY_DUES"},
        {"id": "E033", "type": "single", "role": admin, "message": "outstanding dues march",       "expected": "QUERY_DUES"},
        # ── Tenant queries ───────────────────────────────────────────────────
        {"id": "E034", "type": "single", "role": admin, "message": "Raj balance",                  "expected": "QUERY_TENANT"},
        {"id": "E035", "type": "single", "role": admin, "message": "room 203 details",             "expected": "QUERY_TENANT"},
        {"id": "E036", "type": "single", "role": admin, "message": "how much does Suresh owe",     "expected": "QUERY_TENANT"},
        {"id": "E037", "type": "single", "role": admin, "message": "Priya account statement",      "expected": "QUERY_TENANT"},
        # ── Checkout / checkin ───────────────────────────────────────────────
        {"id": "E038", "type": "single", "role": admin, "message": "checkout Raj",                 "expected": "CHECKOUT"},
        {"id": "E039", "type": "single", "role": admin, "message": "Suresh leaving March 31",      "expected": "SCHEDULE_CHECKOUT"},
        {"id": "E040", "type": "single", "role": admin, "message": "add tenant Vikram 9876543210", "expected": "ADD_TENANT"},
        {"id": "E041", "type": "single", "role": admin, "message": "new checkin",                  "expected": "ADD_TENANT"},
        # ── Rooms / occupancy ────────────────────────────────────────────────
        {"id": "E042", "type": "single", "role": admin, "message": "vacant rooms",                 "expected": "QUERY_VACANT_ROOMS"},
        {"id": "E043", "type": "single", "role": admin, "message": "which rooms are empty",        "expected": "QUERY_VACANT_ROOMS"},
        {"id": "E044", "type": "single", "role": admin, "message": "how many tenants",             "expected": "QUERY_OCCUPANCY"},
        {"id": "E045", "type": "single", "role": admin, "message": "occupancy report",             "expected": "REPORT"},
        # ── Reminders ────────────────────────────────────────────────────────
        {"id": "E046", "type": "single", "role": admin, "message": "remind Raj tomorrow",          "expected": "REMINDER_SET"},
        {"id": "E047", "type": "single", "role": admin, "message": "set reminder Deepak March 10", "expected": "REMINDER_SET"},
        # ── WiFi ─────────────────────────────────────────────────────────────
        {"id": "E048", "type": "single", "role": admin,  "message": "wifi password",               "expected": "GET_WIFI_PASSWORD"},
        {"id": "E049", "type": "single", "role": tenant, "message": "wifi ka password kya hai",    "expected": "GET_WIFI_PASSWORD"},
        {"id": "E050", "type": "single", "role": lead,   "message": "what is the wifi password",   "expected": "GET_WIFI_PASSWORD"},
        # ── Tenant self-service ───────────────────────────────────────────────
        {"id": "E051", "type": "single", "role": tenant, "message": "my balance",                  "expected": "MY_BALANCE"},
        {"id": "E052", "type": "single", "role": tenant, "message": "how much do I owe",           "expected": "MY_BALANCE"},
        {"id": "E053", "type": "single", "role": tenant, "message": "my payment history",          "expected": "MY_PAYMENTS"},
        {"id": "E054", "type": "single", "role": tenant, "message": "my room details",             "expected": "MY_DETAILS"},
        {"id": "E055", "type": "single", "role": tenant, "message": "tap not working",             "expected": "COMPLAINT_REGISTER"},
        {"id": "E056", "type": "single", "role": tenant, "message": "fan broken in my room",       "expected": "COMPLAINT_REGISTER"},
        {"id": "E057", "type": "single", "role": tenant, "message": "wifi is very slow",           "expected": "COMPLAINT_REGISTER"},
        # ── Lead enquiries ────────────────────────────────────────────────────
        {"id": "E058", "type": "single", "role": lead, "message": "how much is rent",              "expected": "ROOM_PRICE"},
        {"id": "E059", "type": "single", "role": lead, "message": "any rooms available",           "expected": "AVAILABILITY"},
        {"id": "E060", "type": "single", "role": lead, "message": "do you have single rooms",      "expected": "ROOM_TYPE"},
        {"id": "E061", "type": "single", "role": lead, "message": "can I come visit tomorrow",     "expected": "VISIT_REQUEST"},
        # ── Typo / informal language ──────────────────────────────────────────
        {"id": "E062", "type": "single", "role": admin, "message": "Raj paied 15000",              "expected": "PAYMENT_LOG"},
        {"id": "E063", "type": "single", "role": admin, "message": "elecricity bill 8500",         "expected": "ADD_EXPENSE"},
        {"id": "E064", "type": "single", "role": admin, "message": "montly report",                "expected": "REPORT"},
        {"id": "E065", "type": "single", "role": admin, "message": "whos not paid",                "expected": "QUERY_DUES"},
        {"id": "E066", "type": "single", "role": admin, "message": "chekout Raj",                  "expected": "CHECKOUT"},
        # ── Hindi / mixed ─────────────────────────────────────────────────────
        {"id": "E067", "type": "single", "role": admin, "message": "Raj ne 12000 diya cash",       "expected": "PAYMENT_LOG"},
        {"id": "E068", "type": "single", "role": admin, "message": "khali rooms kaun se hain",     "expected": "QUERY_VACANT_ROOMS"},
        {"id": "E069", "type": "single", "role": admin, "message": "sabko reminder bhejo",         "expected": "REMINDER_SET"},
        {"id": "E070", "type": "single", "role": tenant, "message": "mera balance kya hai",        "expected": "MY_BALANCE"},
        # ── Greetings / help ──────────────────────────────────────────────────
        {"id": "E071", "type": "single", "role": admin,  "message": "hi",                          "expected": "HELP"},
        {"id": "E072", "type": "single", "role": admin,  "message": "hello",                       "expected": "HELP"},
        {"id": "E073", "type": "single", "role": tenant, "message": "good morning",                "expected": "HELP"},
        {"id": "E074", "type": "single", "role": admin,  "message": "help",                        "expected": "HELP"},
        # ── Void / corrections ─────────────────────────────────────────────────
        {"id": "E075", "type": "single", "role": admin, "message": "void last payment",            "expected": "VOID_PAYMENT"},
        {"id": "E076", "type": "single", "role": admin, "message": "wrong payment entered",        "expected": "VOID_PAYMENT"},
        # ── Expense queries ─────────────────────────────────────────────────
        {"id": "E077", "type": "single", "role": admin, "message": "total expenses march",         "expected": "QUERY_EXPENSES"},
        {"id": "E078", "type": "single", "role": admin, "message": "what did we spend last month", "expected": "QUERY_EXPENSES"},
        {"id": "E079", "type": "single", "role": admin, "message": "expense report february",      "expected": "QUERY_EXPENSES"},
        # ── Rules ───────────────────────────────────────────────────────────
        {"id": "E080", "type": "single", "role": admin,  "message": "show rules",                  "expected": "RULES"},
        {"id": "E081", "type": "single", "role": tenant, "message": "what are the house rules",    "expected": "RULES"},
        # ── More report variations ─────────────────────────────────────────
        {"id": "E082", "type": "single", "role": admin, "message": "march report",                 "expected": "REPORT"},
        {"id": "E083", "type": "single", "role": admin, "message": "show march summary",           "expected": "REPORT"},
        {"id": "E084", "type": "single", "role": admin, "message": "how much collected total",     "expected": "REPORT"},
        {"id": "E085", "type": "single", "role": admin, "message": "p&l",                         "expected": "REPORT"},
        {"id": "E086", "type": "single", "role": admin, "message": "income this month",            "expected": "REPORT"},
        {"id": "E087", "type": "single", "role": admin, "message": "financial summary",            "expected": "REPORT"},
        {"id": "E088", "type": "single", "role": admin, "message": "collections february",         "expected": "REPORT"},
        # ── More PAYMENT_LOG variations ─────────────────────────────────────
        {"id": "E089", "type": "single", "role": admin, "message": "Mohan paid 9000 phonepe",      "expected": "PAYMENT_LOG"},
        {"id": "E090", "type": "single", "role": admin, "message": "collected 8500 from Ravi",     "expected": "PAYMENT_LOG"},
        {"id": "E091", "type": "single", "role": admin, "message": "12000 Sanjay online",          "expected": "PAYMENT_LOG"},
        {"id": "E092", "type": "single", "role": admin, "message": "Gopal deposited 7500 neft",    "expected": "PAYMENT_LOG"},
        # ── Checkins / checkouts ────────────────────────────────────────────
        {"id": "E093", "type": "single", "role": admin, "message": "who checked in this month",    "expected": "QUERY_CHECKINS"},
        {"id": "E094", "type": "single", "role": admin, "message": "new arrivals january",         "expected": "QUERY_CHECKINS"},
        {"id": "E095", "type": "single", "role": admin, "message": "who left last month",          "expected": "QUERY_CHECKOUTS"},
        {"id": "E096", "type": "single", "role": admin, "message": "checkouts march",              "expected": "QUERY_CHECKOUTS"},
        # ── Room status ─────────────────────────────────────────────────────
        {"id": "E097", "type": "single", "role": admin, "message": "who is in room 201",           "expected": "ROOM_STATUS"},
        {"id": "E098", "type": "single", "role": admin, "message": "room 301 occupant",            "expected": "ROOM_STATUS"},
        # ── Expiring tenancies ───────────────────────────────────────────────
        {"id": "E099", "type": "single", "role": admin, "message": "who is leaving this month",    "expected": "QUERY_EXPIRING"},
        {"id": "E100", "type": "single", "role": admin, "message": "expiring agreements",          "expected": "QUERY_EXPIRING"},
    ]


# ── Multi-turn conversation tests ──────────────────────────────────────────────
# These are the KEY tests — where LangGraph memory helps vs stateless regex

MULTI_TURN_CONVERSATIONS: list[dict] = [
    # ── C01: The "January cash?" bug ─────────────────────────────────────────
    {
        "id": "C01",
        "name": "Cash report follow-ups (the January bug)",
        "role": "admin",
        "turns": [
            {"message": "monthly report",              "expected": "REPORT"},
            {"message": "how much cash in march?",     "expected": "REPORT"},
            {"message": "february?",                   "expected": "REPORT"},      # follow-up
            {"message": "january?",                    "expected": "REPORT"},      # follow-up — FAILS in regex
            {"message": "January 2025 cash?",          "expected": "REPORT"},      # THE BUG — fails in regex
        ],
    },
    # ── C02: UPI drill-down ───────────────────────────────────────────────────
    {
        "id": "C02",
        "name": "UPI collection follow-ups",
        "role": "admin",
        "turns": [
            {"message": "march summary",               "expected": "REPORT"},
            {"message": "how much upi?",               "expected": "REPORT"},
            {"message": "and february upi?",           "expected": "REPORT"},
            {"message": "december?",                   "expected": "REPORT"},      # context: still in report mode
        ],
    },
    # ── C03: Dues then payment ────────────────────────────────────────────────
    {
        "id": "C03",
        "name": "Check dues then log payment",
        "role": "admin",
        "turns": [
            {"message": "who hasn't paid",             "expected": "QUERY_DUES"},
            {"message": "Raj paid 15000 upi",          "expected": "PAYMENT_LOG"},
            {"message": "any others?",                 "expected": "QUERY_DUES"},  # back to dues context
        ],
    },
    # ── C04: Multi-month expense drill ───────────────────────────────────────
    {
        "id": "C04",
        "name": "Expense queries across months",
        "role": "admin",
        "turns": [
            {"message": "total expenses march",        "expected": "QUERY_EXPENSES"},
            {"message": "february?",                   "expected": "QUERY_EXPENSES"},  # follow-up
            {"message": "and january expenses?",       "expected": "QUERY_EXPENSES"},
        ],
    },
    # ── C05: Tenant balance then payment ──────────────────────────────────────
    {
        "id": "C05",
        "name": "Check tenant balance then log payment",
        "role": "admin",
        "turns": [
            {"message": "Raj balance",                 "expected": "QUERY_TENANT"},
            {"message": "ok Raj paid 12000 cash",      "expected": "PAYMENT_LOG"},
            {"message": "Raj balance now",             "expected": "QUERY_TENANT"},
        ],
    },
    # ── C06: Checkin then onboard ─────────────────────────────────────────────
    {
        "id": "C06",
        "name": "Add new tenant flow",
        "role": "admin",
        "turns": [
            {"message": "new tenant Vikram 9876543210 room 201",   "expected": "ADD_TENANT"},
            {"message": "start onboarding for Vikram 9876543210",  "expected": "START_ONBOARDING"},
        ],
    },
    # ── C07: Vacant rooms then add tenant ────────────────────────────────────
    {
        "id": "C07",
        "name": "Check vacancy then add tenant",
        "role": "admin",
        "turns": [
            {"message": "vacant rooms",                "expected": "QUERY_VACANT_ROOMS"},
            {"message": "add tenant Gopal 9000000001 room 305",    "expected": "ADD_TENANT"},
        ],
    },
    # ── C08: Complaint then expense ───────────────────────────────────────────
    {
        "id": "C08",
        "name": "Complaint then pay for repair",
        "role": "admin",
        "turns": [
            {"message": "plumbing issue in room 202",  "expected": "COMPLAINT_REGISTER"},
            {"message": "plumber 2500 cash",           "expected": "ADD_EXPENSE"},
        ],
    },
    # ── C09: Report then dues ──────────────────────────────────────────────────
    {
        "id": "C09",
        "name": "Monthly report then check who hasn't paid",
        "role": "admin",
        "turns": [
            {"message": "monthly report",              "expected": "REPORT"},
            {"message": "send dues",                   "expected": "QUERY_DUES"},
            {"message": "still pending?",              "expected": "QUERY_DUES"},   # context follow-up
        ],
    },
    # ── C10: Tenant session ────────────────────────────────────────────────────
    {
        "id": "C10",
        "name": "Tenant checks balance and payment history",
        "role": "tenant",
        "turns": [
            {"message": "hi",                          "expected": "HELP"},
            {"message": "my balance",                  "expected": "MY_BALANCE"},
            {"message": "show my payments",            "expected": "MY_PAYMENTS"},
            {"message": "my room details",             "expected": "MY_DETAILS"},
        ],
    },
    # ── C11: Lead enquiry ──────────────────────────────────────────────────────
    {
        "id": "C11",
        "name": "Lead room enquiry",
        "role": "lead",
        "turns": [
            {"message": "hi",                          "expected": "HELP"},
            {"message": "how much is rent",            "expected": "ROOM_PRICE"},
            {"message": "do you have single rooms",    "expected": "ROOM_TYPE"},
            {"message": "any rooms available now",     "expected": "AVAILABILITY"},
            {"message": "can I visit tomorrow",        "expected": "VISIT_REQUEST"},
        ],
    },
    # ── C12: Report ambiguity series ──────────────────────────────────────────
    {
        "id": "C12",
        "name": "Month-only follow-ups after report (all must be REPORT)",
        "role": "admin",
        "turns": [
            {"message": "show me the march report",    "expected": "REPORT"},
            {"message": "march cash breakdown",        "expected": "REPORT"},
            {"message": "feb?",                        "expected": "REPORT"},
            {"message": "jan?",                        "expected": "REPORT"},
            {"message": "dec 2025?",                   "expected": "REPORT"},
            {"message": "november cash",               "expected": "REPORT"},
        ],
    },
    # ── C13: Checkout flow ─────────────────────────────────────────────────────
    {
        "id": "C13",
        "name": "Schedule then record checkout",
        "role": "admin",
        "turns": [
            {"message": "Suresh leaving March 31",     "expected": "SCHEDULE_CHECKOUT"},
            {"message": "record checkout Suresh",      "expected": "RECORD_CHECKOUT"},
        ],
    },
    # ── C14: WiFi across roles ─────────────────────────────────────────────────
    {
        "id": "C14",
        "name": "WiFi password queries",
        "role": "admin",
        "turns": [
            {"message": "wifi password for 2nd floor", "expected": "GET_WIFI_PASSWORD"},
            {"message": "and ground floor?",           "expected": "GET_WIFI_PASSWORD"},
        ],
    },
    # ── C15: Occupancy drill ──────────────────────────────────────────────────
    {
        "id": "C15",
        "name": "Occupancy stats then vacant rooms",
        "role": "admin",
        "turns": [
            {"message": "how many tenants total",      "expected": "QUERY_OCCUPANCY"},
            {"message": "which rooms are empty",       "expected": "QUERY_VACANT_ROOMS"},
            {"message": "how many vacant",             "expected": "QUERY_VACANT_ROOMS"},
        ],
    },
]


# ── Test runner ────────────────────────────────────────────────────────────────

async def run_langgraph_single(test: dict, semaphore: asyncio.Semaphore) -> dict:
    """Run a single-turn test through LangGraph (new thread = no prior context)."""
    thread_id = f"single_{test['id']}_{time.time_ns()}"
    config    = {"configurable": {"thread_id": thread_id}}
    async with semaphore:
        state  = await _graph.ainvoke(
            {
                "messages": [HumanMessage(content=test["message"])],
                "role":     test["role"],
                "intent":   "",
                "confidence": 0.0,
                "entities": {},
            },
            config=config,
        )
    return {
        "intent":     state.get("intent", "ERROR"),
        "confidence": state.get("confidence", 0.0),
        "entities":   state.get("entities", {}),
    }


async def run_langgraph_conversation(conv: dict, semaphore: asyncio.Semaphore) -> list[dict]:
    """Run a multi-turn conversation through LangGraph (shared thread = real memory)."""
    thread_id = f"conv_{conv['id']}_{time.time_ns()}"
    config    = {"configurable": {"thread_id": thread_id}}
    role      = conv["role"]
    results   = []

    for i, turn in enumerate(conv["turns"]):
        async with semaphore:
            state = await _graph.ainvoke(
                {
                    "messages": [HumanMessage(content=turn["message"])],
                    "role":     role,
                    "intent":   "",
                    "confidence": 0.0,
                    "entities": {},
                },
                config=config,
            )
        results.append({
            "turn":       i + 1,
            "message":    turn["message"],
            "expected":   turn["expected"],
            "lg_intent":  state.get("intent", "ERROR"),
            "lg_conf":    state.get("confidence", 0.0),
        })

    return results


def run_regex(message: str, role: str) -> dict:
    """Run existing regex-based intent detector."""
    result = detect_intent(message, role)
    return {
        "intent":     result.intent,
        "confidence": result.confidence,
        "entities":   result.entities,
    }


# ── Main evaluation ────────────────────────────────────────────────────────────

async def main():
    print("\n" + "=" * 65)
    print("  LangGraph vs Regex -- Intent Classification Benchmark")
    print("  Model:", GROQ_MODEL)
    print("=" * 65 + "\n")

    if not GROQ_API_KEY or GROQ_API_KEY.startswith("XXXX"):
        print("ERROR: GROQ_API_KEY not set in .env")
        sys.exit(1)

    semaphore = asyncio.Semaphore(CONCURRENCY)

    # ── Load test data ─────────────────────────────────────────────────────────
    single_tests = load_single_turn_tests() + synthetic_edge_cases()
    print(f"  Single-turn tests : {len(single_tests)}")
    print(f"  Multi-turn convos : {len(MULTI_TURN_CONVERSATIONS)} conversations")
    total_turns = sum(len(c["turns"]) for c in MULTI_TURN_CONVERSATIONS)
    print(f"  Multi-turn turns  : {total_turns}")
    print(f"  Total LLM calls   : ~{len(single_tests) + total_turns}")
    print()

    # ── Run single-turn tests ──────────────────────────────────────────────────
    print("Running single-turn tests...")
    t0 = time.time()

    # Run regex immediately (no async needed)
    for t in single_tests:
        t["regex"] = run_regex(t["message"], t["role"])

    # Run LangGraph async
    tasks = [run_langgraph_single(t, semaphore) for t in single_tests]
    lg_results = await asyncio.gather(*tasks, return_exceptions=True)

    single_results = []
    for t, lg in zip(single_tests, lg_results):
        if isinstance(lg, Exception):
            lg = {"intent": "ERROR", "confidence": 0.0, "entities": {"error": str(lg)}}
        expected      = t["expected"]
        regex_correct = t["regex"]["intent"] == expected
        lg_correct    = lg["intent"] == expected
        single_results.append({
            "id":            t["id"],
            "type":          "single",
            "role":          t["role"],
            "message":       t["message"],
            "expected":      expected,
            "regex_intent":  t["regex"]["intent"],
            "regex_conf":    round(t["regex"]["confidence"], 2),
            "regex_correct": regex_correct,
            "lg_intent":     lg["intent"],
            "lg_conf":       round(lg["confidence"], 2),
            "lg_correct":    lg_correct,
            "winner":        (
                "both"  if regex_correct and lg_correct else
                "regex" if regex_correct and not lg_correct else
                "lg"    if lg_correct and not regex_correct else
                "neither"
            ),
        })

    elapsed_single = time.time() - t0
    print(f"Done in {elapsed_single:.1f}s\n")

    # ── Run multi-turn conversations ────────────────────────────────────────────
    print("Running multi-turn conversations (LangGraph with memory)...")
    t0 = time.time()

    conv_results = []
    for conv in MULTI_TURN_CONVERSATIONS:
        print(f"  [{conv['id']}] {conv['name']}")
        conv_turns = await run_langgraph_conversation(conv, semaphore)

        # Also run regex on each turn (independently, stateless)
        for turn_data in conv_turns:
            regex_result = run_regex(turn_data["message"], conv["role"])
            turn_data["regex_intent"]  = regex_result["intent"]
            turn_data["regex_correct"] = regex_result["intent"] == turn_data["expected"]
            turn_data["lg_correct"]    = turn_data["lg_intent"] == turn_data["expected"]
            turn_data["winner"]        = (
                "both"  if turn_data["regex_correct"] and turn_data["lg_correct"] else
                "regex" if turn_data["regex_correct"] and not turn_data["lg_correct"] else
                "lg"    if turn_data["lg_correct"] and not turn_data["regex_correct"] else
                "neither"
            )

        conv_results.append({
            "id":    conv["id"],
            "name":  conv["name"],
            "role":  conv["role"],
            "turns": conv_turns,
        })

    elapsed_conv = time.time() - t0
    print(f"\nDone in {elapsed_conv:.1f}s\n")

    # ── Compute summary stats ──────────────────────────────────────────────────
    # Single-turn stats
    st_total   = len(single_results)
    st_regex   = sum(1 for r in single_results if r["regex_correct"])
    st_lg      = sum(1 for r in single_results if r["lg_correct"])
    st_both    = sum(1 for r in single_results if r["winner"] == "both")
    st_r_only  = sum(1 for r in single_results if r["winner"] == "regex")
    st_lg_only = sum(1 for r in single_results if r["winner"] == "lg")
    st_neither = sum(1 for r in single_results if r["winner"] == "neither")

    # Multi-turn stats (flatten all turns)
    all_turns  = [t for c in conv_results for t in c["turns"]]
    mt_total   = len(all_turns)
    mt_regex   = sum(1 for t in all_turns if t["regex_correct"])
    mt_lg      = sum(1 for t in all_turns if t["lg_correct"])

    # ── Save results FIRST so a display crash can't lose data ──────────────────
    RESULTS_DIR.mkdir(exist_ok=True)
    ts          = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = RESULTS_DIR / f"{ts}_langgraph_vs_regex.json"
    _save_output = {
        "meta": {
            "timestamp":       ts,
            "model":           GROQ_MODEL,
            "single_tests":    st_total,
            "multi_turn_convos": len(conv_results),
            "multi_turn_turns": mt_total,
        },
        "summary": {
            "single_regex_accuracy":    round(st_regex / st_total * 100.0, 2),  # type: ignore[call-overload]
            "single_lg_accuracy":       round(st_lg / st_total * 100.0, 2),  # type: ignore[call-overload]
            "multi_regex_accuracy":     round(mt_regex / mt_total * 100.0, 2),  # type: ignore[call-overload]
            "multi_lg_accuracy":        round(mt_lg / mt_total * 100.0, 2),  # type: ignore[call-overload]
            "single_both_correct":      st_both,
            "single_regex_only":        st_r_only,
            "single_lg_only":           st_lg_only,
            "single_neither":           st_neither,
        },
        "single_results":    single_results,
        "conversation_results": conv_results,
    }
    output_file.write_text(json.dumps(_save_output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  Results saved -> {output_file}\n")

    # ── Print summary ──────────────────────────────────────────────────────────
    print("=" * 65)
    print("  RESULTS SUMMARY")
    print("═" * 65)
    print(f"\n  {'Metric':<35} {'Regex':>10} {'LangGraph':>10}")
    print(f"  {'-'*55}")
    print(f"  {'Single-turn accuracy':<35} {st_regex/st_total*100:>9.1f}% {st_lg/st_total*100:>9.1f}%")
    print(f"  {'Multi-turn accuracy':<35} {mt_regex/mt_total*100:>9.1f}% {mt_lg/mt_total*100:>9.1f}%")
    print(f"\n  Single-turn wins:")
    print(f"    Both correct   : {st_both}  ({st_both/st_total*100:.0f}%)")
    print(f"    Regex only     : {st_r_only}  ({st_r_only/st_total*100:.0f}%)")
    print(f"    LangGraph only : {st_lg_only}  ({st_lg_only/st_total*100:.0f}%)")
    print(f"    Neither        : {st_neither}  ({st_neither/st_total*100:.0f}%)")

    # ── Show where each engine beats the other ─────────────────────────────────
    regex_wins = [r for r in single_results if r["winner"] == "regex"]
    lg_wins    = [r for r in single_results if r["winner"] == "lg"]

    if regex_wins[:5]:
        print(f"\n  Cases where Regex beats LangGraph (first 5):")
        for r in regex_wins[:5]:
            print(f"    [{r['id']}] \"{r['message'][:40]}\"")
            print(f"          Expected: {r['expected']}, LG gave: {r['lg_intent']}")

    if lg_wins[:5]:
        print(f"\n  Cases where LangGraph beats Regex (first 5):")
        for r in lg_wins[:5]:
            print(f"    [{r['id']}] \"{r['message'][:40]}\"")
            print(f"          Expected: {r['expected']}, Regex gave: {r['regex_intent']}")

    # ── Multi-turn detail ──────────────────────────────────────────────────────
    print(f"\n  Multi-turn conversation detail:")
    for conv in conv_results:
        turns      = conv["turns"]
        lg_acc     = sum(1 for t in turns if t["lg_correct"]) / len(turns) * 100
        regex_acc  = sum(1 for t in turns if t["regex_correct"]) / len(turns) * 100
        indicator  = "🟢" if lg_acc > regex_acc else ("🔴" if lg_acc < regex_acc else "⚪")
        print(f"    {indicator} [{conv['id']}] {conv['name'][:40]}")
        print(f"         Regex: {regex_acc:.0f}%  LangGraph: {lg_acc:.0f}%")
        for t in turns:
            rx = "✓" if t["regex_correct"] else "✗"
            lg = "✓" if t["lg_correct"] else "✗"
            print(f"         Turn {t['turn']}: \"{t['message'][:35]:<35}\" "
                  f"Exp:{t['expected']:<20} Regex:{rx} LG:{lg}")

    print("=" * 65 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
