"""
src/whatsapp/v2/supervisor.py
──────────────────────────────
LangGraph Supervisor Agent for Kozzy/Artha v2.

Every inbound WhatsApp message runs through this graph:

    START
      → load_context          (user profile + conversation history from DB)
      → supervisor_classify   (Groq LLM → intent_type, topic, agent, confidence)
      → route_agent           (conditional edge: STATEMENT skips agent_executor)
      → agent_executor        (calls the matching v1 handler)
      → save_memory           (writes turn to conversation_history)
      → END

Model:  Groq llama-3.1-70b-versatile
State:  PGState (TypedDict)
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

from langchain_groq import ChatGroq
from langgraph.graph import StateGraph, END
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing_extensions import TypedDict

from src.database.models import Tenant
from src.whatsapp.v2.agent_tools import (
    resolve_v1_intent,
    run_finance_agent,
    run_operations_agent,
    run_tenant_agent,
    run_lead_agent,
)
from src.whatsapp.v2.memory import get_history

# ── LLM ───────────────────────────────────────────────────────────────────────
_GROQ_MODEL = "llama-3.3-70b-versatile"

def _get_llm() -> ChatGroq:
    """Return a zero-temperature Groq client for deterministic classification."""
    return ChatGroq(
        model=_GROQ_MODEL,
        temperature=0,
        api_key=os.getenv("GROQ_API_KEY", ""),
    )


# ── State ─────────────────────────────────────────────────────────────────────

class PGState(TypedDict):
    # ── Input (set by chat_api_v2 before calling the graph)
    user_id:    str    # phone number
    role:       str    # admin | power_user | tenant | lead
    message:    str    # current inbound message
    ctx:        Any    # CallerContext object (not serialised, passed in-memory)
    session:    Any    # AsyncSession (not serialised, passed in-memory)

    # ── Loaded by load_context node
    user_name:  str    # tenant display name (empty for leads)
    history:    list   # [{sent_by, message, intent, role}, ...]

    # ── Supervisor output (Groq LLM)
    intent_type:      str    # QUERY | ACTION | COMPLAINT | STATEMENT | GREETING | FOLLOW_UP
    topic:            str    # payment | wifi | complaint | dues | checkout | report | general | …
    agent:            str    # finance | operations | tenant | lead | general
    action_required:  bool
    confidence:       float

    # ── Agent execution output
    v1_intent:   str   # resolved v1 intent string (e.g. PAYMENT_LOG)
    raw_result:  str   # text reply from v1 handler

    # ── Final
    response:    str   # message to send back on WhatsApp


# ── Humanizer system prompt ───────────────────────────────────────────────────
_HUMANIZER_PROMPT = """\
You are Artha, the AI assistant for Kozzy PG (paying guest hostel).
You speak warmly, naturally, and like a helpful human colleague — not a robot.

User: {name} | Role: {role}
{history_block}

User just said: "{message}"
Topic: {topic} | Type: {intent_type}

Bot's raw answer to convey:
{raw_result}

Rewrite the raw answer as a warm, natural WhatsApp message.
Rules:
- Keep ALL facts exactly as given (amounts ₹, dates, names, balances)
- Owner/admin: professional but friendly, use their first name occasionally
- Tenant: warm and supportive — they live here, make them feel at home
- Lead: enthusiastic and helpful — make the PG sound welcoming
- Max 2 emojis per message — only where they genuinely add warmth
- Use *bold* for key numbers, names, amounts
- Be concise — no padding, no "As an AI...", no disclaimers
- Match the user's language (Hindi / English / Hinglish — match what they wrote)
- If raw answer is empty (GREETING), generate a warm personalised greeting using their name and conversation history
- Reference prior context naturally if relevant (e.g. "like we discussed earlier...")

Reply ONLY with the final WhatsApp message — no preamble, no quotes around it."""


# ── Supervisor system prompt ───────────────────────────────────────────────────
_SYSTEM_PROMPT = """\
You are the Artha PG management assistant supervisor.
Your job is to classify incoming WhatsApp messages from PG (paying guest hostel) users.

User role: {role}
{history_block}
Current message: "{message}"

Classify the message and respond with ONLY a valid JSON object — no extra text.

Valid intent_type values:
  QUERY      — user wants information
  ACTION     — user wants to do something (log payment, file complaint, checkout)
  COMPLAINT  — user is reporting a problem
  STATEMENT  — acknowledgement, thanks, "ok", "got it" — no response needed
  GREETING   — hello, hi, good morning
  FOLLOW_UP  — continuation of a previous topic

Valid topic values:
  payment | dues | report | expense | refund | void | rent | discount
  complaint | checkout | checkin | wifi | occupancy | vacant | expiring
  checkins | checkouts | vacation | notice | room_status | price
  availability | visit | room_type | details | general

Valid agent values:
  finance    — for: payment, dues, report, expense, refund, void, rent, discount
  operations — for: complaint, checkout, checkin, wifi, occupancy, vacant,
                    expiring, checkins, checkouts, vacation, notice, room_status
  tenant     — ONLY when role == "tenant": dues, payment, wifi, complaint, checkout, vacation, details
  lead       — ONLY when role == "lead":   price, availability, visit, room_type
  general    — fallback when none of the above fit

Rules:
- If role is "tenant", agent must be "tenant" (tenants cannot access financial/admin data)
- If role is "lead", agent must be "lead" (leads cannot access internal data)
- If intent_type is STATEMENT or GREETING, set action_required to false
- Be conservative: when unsure, default intent_type to QUERY

Respond ONLY with valid JSON:
{{
  "intent_type": "...",
  "topic": "...",
  "agent": "...",
  "action_required": true or false,
  "confidence": 0.0 to 1.0
}}"""


def _build_history_block(history: list[dict]) -> str:
    """Format conversation history list into a readable block for the prompt."""
    if not history:
        return "Conversation history: (none — first message)"
    lines = ["Conversation history (oldest first):"]
    for turn in history:
        who = "User" if turn["sent_by"] == "user" else "Artha"
        intent = f" [{turn['intent']}]" if turn.get("intent") else ""
        lines.append(f"  {who}{intent}: {turn['message']}")
    return "\n".join(lines)


def _parse_supervisor_json(text: str) -> dict:
    """Extract JSON from supervisor LLM output, handling markdown fences."""
    # Strip markdown code fences if present
    cleaned = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`")
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Fallback: extract first {...} block
        m = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if m:
            return json.loads(m.group())
        raise


# ── Graph nodes ───────────────────────────────────────────────────────────────

async def load_context(state: PGState) -> dict:
    """Load user display name and conversation history from DB."""
    session: AsyncSession = state["session"]
    phone = state["user_id"]

    # Get tenant display name (empty string for leads / unknown)
    user_name = ""
    try:
        result = await session.execute(
            select(Tenant.name).where(Tenant.phone == phone)
        )
        row = result.scalar()
        if row:
            user_name = row
    except Exception:
        pass

    history = await get_history(phone, session, limit=10)
    return {"user_name": user_name, "history": history}


async def supervisor_classify(state: PGState) -> dict:
    """Call Groq LLM to classify the message with conversation context.

    Returns updated state keys: intent_type, topic, agent, action_required, confidence.
    Falls back to safe defaults if the LLM call fails or returns malformed JSON.
    """
    history_block = _build_history_block(state.get("history", []))
    prompt = _SYSTEM_PROMPT.format(
        role=state["role"],
        history_block=history_block,
        message=state["message"],
    )

    defaults = {
        "intent_type":     "QUERY",
        "topic":           "general",
        "agent":           _role_to_default_agent(state["role"]),
        "action_required": False,
        "confidence":      0.5,
    }

    try:
        llm = _get_llm()
        response = await llm.ainvoke(prompt)
        parsed = _parse_supervisor_json(response.content)
        # Enforce role constraints
        parsed = _enforce_role_constraints(parsed, state["role"])
        return {
            "intent_type":     parsed.get("intent_type",     defaults["intent_type"]),
            "topic":           parsed.get("topic",           defaults["topic"]),
            "agent":           parsed.get("agent",           defaults["agent"]),
            "action_required": parsed.get("action_required", defaults["action_required"]),
            "confidence":      float(parsed.get("confidence", defaults["confidence"])),
        }
    except Exception:
        return defaults


def _role_to_default_agent(role: str) -> str:
    """Return the safe default agent for a given role."""
    if role == "tenant":
        return "tenant"
    if role == "lead":
        return "lead"
    return "operations"


def _enforce_role_constraints(parsed: dict, role: str) -> dict:
    """Ensure the LLM doesn't route tenants/leads to privileged agents."""
    if role == "tenant":
        parsed["agent"] = "tenant"
    elif role == "lead":
        parsed["agent"] = "lead"
    return parsed


async def agent_executor(state: PGState) -> dict:
    """Map (agent, topic, intent_type) → v1 intent, then call the v1 handler.

    Returns updated state keys: v1_intent, raw_result, response.
    """
    agent      = state["agent"]
    topic      = state["topic"]
    intent_type = state["intent_type"]
    v1_intent  = resolve_v1_intent(agent, topic, intent_type)

    session: AsyncSession = state["session"]
    ctx    = state["ctx"]
    msg    = state["message"]

    try:
        if agent == "finance":
            result = await run_finance_agent(v1_intent, msg, ctx, session)
        elif agent == "operations":
            result = await run_operations_agent(v1_intent, msg, ctx, session)
        elif agent == "tenant":
            result = await run_tenant_agent(v1_intent, msg, ctx, session)
        else:  # lead / general
            result = await run_lead_agent(v1_intent, msg, ctx, session)
    except Exception as exc:
        result = f"Sorry, something went wrong. Please try again. ({type(exc).__name__})"

    return {"v1_intent": v1_intent, "raw_result": result, "response": result}


async def humanize_response(state: PGState) -> dict:
    """Call Groq to rewrite the raw v1 handler result as a warm, contextual reply.

    For GREETING with no raw_result, Groq generates a personalised greeting from scratch.
    Falls back to raw_result unchanged if the LLM call fails.
    """
    raw = state.get("raw_result", "") or ""
    # Don't humanize very short canned replies (already human enough) or empty
    # — but DO humanize greetings (raw may be empty for GREETING)
    intent_type = state.get("intent_type", "")

    history_block = _build_history_block(state.get("history", []))
    prompt = _HUMANIZER_PROMPT.format(
        name=state.get("user_name") or "there",
        role=state.get("role", ""),
        history_block=history_block,
        message=state.get("message", ""),
        topic=state.get("topic", ""),
        intent_type=intent_type,
        raw_result=raw if raw else "(no data — generate warm greeting)",
    )

    try:
        llm = _get_llm()
        resp = await llm.ainvoke(prompt)
        humanized = resp.content.strip()
        if humanized:
            return {"response": humanized}
    except Exception:
        pass  # fall back to raw_result

    return {"response": raw}


async def save_memory_node(state: PGState) -> dict:
    """For STATEMENT / GREETING intents: set a canned response and return.

    For all other intents this node is reached after agent_executor already
    set state['response'], so nothing extra is needed — just return as-is.
    The actual DB write happens in chat_api_v2.py (after the graph finishes)
    so the session.commit() is handled in one place.
    """
    if state["intent_type"] in ("STATEMENT", "GREETING") and not state.get("response"):
        return {"response": "", "v1_intent": "STATEMENT", "raw_result": ""}
    return {"response": state.get("response", "")}


# ── Conditional edge ──────────────────────────────────────────────────────────

def route_after_classify(state: PGState) -> str:
    """Skip agent_executor for statements/greetings — no DB action needed, go straight to humanizer."""
    if state["intent_type"] in ("STATEMENT", "GREETING"):
        return "humanize_response"
    return "agent_executor"


# ── Graph assembly ────────────────────────────────────────────────────────────

def build_graph() -> StateGraph:
    """Compile the LangGraph supervisor graph and return it ready for .ainvoke()."""
    graph = StateGraph(PGState)

    graph.add_node("load_context",        load_context)
    graph.add_node("supervisor_classify", supervisor_classify)
    graph.add_node("agent_executor",      agent_executor)
    graph.add_node("humanize_response",   humanize_response)
    graph.add_node("save_memory",         save_memory_node)

    graph.set_entry_point("load_context")
    graph.add_edge("load_context", "supervisor_classify")
    graph.add_conditional_edges(
        "supervisor_classify",
        route_after_classify,
        {
            "agent_executor":   "agent_executor",
            "humanize_response": "humanize_response",
        },
    )
    graph.add_edge("agent_executor",    "humanize_response")
    graph.add_edge("humanize_response", "save_memory")
    graph.add_edge("save_memory", END)

    return graph.compile()


# Singleton compiled graph — built once at import time
_graph = build_graph()


async def run_supervisor_graph(
    user_id: str,
    role: str,
    message: str,
    history: list,
    ctx: Any,
    session: AsyncSession,
) -> PGState:
    """Run the supervisor graph and return the final state dict."""
    initial_state: PGState = {
        "user_id":        user_id,
        "role":           role,
        "message":        message,
        "ctx":            ctx,
        "session":        session,
        "history":        history,
        "user_name":      "",
        "intent_type":    "",
        "topic":          "",
        "agent":          "",
        "action_required": False,
        "confidence":     0.0,
        "v1_intent":      "",
        "raw_result":     "",
        "response":       "",
    }
    result = await _graph.ainvoke(initial_state)
    return result
