"""
LangGraph reasoning router for PG Accountant.

Flow:
  WhatsApp message / file ingestion
    → detect_intent  (AI, ~3% of calls)
    → route_task
    → [ingest | classify | reconcile | report | respond]
    → format_response

Guardrails:
  - max_iterations = 2
  - no recursive loops
  - timeout = 30s
  - all heavy work is deterministic Python
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Optional

from langchain_core.messages import BaseMessage
from langgraph.graph import StateGraph, END

from loguru import logger


# ── State ──────────────────────────────────────────────────────────────────

@dataclass
class PGState:
    # Input
    message: str = ""
    file_path: Optional[str] = None
    sender_phone: Optional[str] = None

    # Routing
    intent: str = "unknown"
    period: Optional[str] = None
    export_format: str = "text"
    category_filter: Optional[str] = None

    # Processing results
    parsed_transactions: list[dict] = field(default_factory=list)
    classified_transactions: list[dict] = field(default_factory=list)
    deduplication_stats: dict = field(default_factory=dict)
    reconciliation_result: Optional[dict] = None
    report_path: Optional[str] = None
    dashboard_url: Optional[str] = None

    # Pending approvals
    pending_entities: list[dict] = field(default_factory=list)

    # Output
    response_text: str = ""
    error: Optional[str] = None

    # Guardrails
    iterations: int = 0
    max_iterations: int = 2


# ── Node functions ─────────────────────────────────────────────────────────

async def node_detect_intent(state: PGState) -> PGState:
    """Use AI to detect WhatsApp message intent (only for text messages)."""
    if not state.message:
        return state

    # Try rules-based intent first (fast, free)
    from src.agents.intent_detector import detect_intent_rules
    result = detect_intent_rules(state.message)

    if result["confidence"] < 0.75:
        # Fallback to Claude (~3% of messages)
        from src.llm_gateway.claude_client import get_claude_client
        claude = get_claude_client()
        result = await claude.detect_intent(state.message)
        logger.info(f"[LangGraph] AI intent: {result['intent']} conf={result.get('confidence')}")
    else:
        logger.info(f"[LangGraph] Rules intent: {result['intent']} conf={result['confidence']}")

    state.intent         = result.get("intent", "unknown")
    state.period         = result.get("period")
    state.export_format  = result.get("format") or "text"
    state.category_filter = result.get("category")
    state.iterations    += 1
    return state


async def node_ingest_file(state: PGState) -> PGState:
    """Parse file, deduplicate, classify, queue unknown entities."""
    if not state.file_path:
        return state

    from src.parsers.dispatcher import parse_file
    from src.rules.deduplication import batch_deduplicate
    from src.rules.categorization_rules import classify_batch

    raw = parse_file(state.file_path)
    unique, dupes = batch_deduplicate(raw)
    classified = classify_batch(unique)

    state.parsed_transactions      = classified
    state.deduplication_stats      = {"total": len(raw), "unique": len(unique), "duplicates": len(dupes)}
    state.classified_transactions  = classified
    logger.info(f"[LangGraph] Ingested: {len(unique)} unique, {len(dupes)} dupes")
    return state


async def node_classify(state: PGState) -> PGState:
    """AI classification for transactions that need_ai_review."""
    if not state.classified_transactions:
        return state

    from src.llm_gateway.claude_client import get_claude_client
    from src.database.db_manager import get_all_categories

    ai_needed = [t for t in state.classified_transactions if t.get("needs_ai_review")]
    if not ai_needed:
        return state

    claude     = get_claude_client()
    categories = [c.name for c in await get_all_categories()]

    for txn in ai_needed:
        result = await claude.classify_merchant(
            description=txn.get("description", ""),
            merchant=txn.get("merchant", ""),
            date=str(txn.get("date", "")),
            amount=float(txn.get("amount", 0)),
            txn_type=txn.get("txn_type", "expense"),
            categories=categories,
        )
        txn["category"]       = result["category"]
        txn["confidence"]     = result["confidence"]
        txn["ai_classified"]  = True
        txn["needs_ai_review"] = False

    logger.info(f"[LangGraph] AI classified {len(ai_needed)} transactions")
    return state


async def node_persist(state: PGState) -> PGState:
    """Save classified transactions to database."""
    if not state.classified_transactions:
        return state

    from src.database.db_manager import upsert_transaction, get_category_by_name, queue_pending_entity

    saved = skipped = 0
    for txn in state.classified_transactions:
        # Resolve category ID
        cat = await get_category_by_name(txn.get("category", "Miscellaneous"))
        if cat:
            txn["category_id"] = cat.id

        # Strip non-model fields
        txn_clean = {k: v for k, v in txn.items() if k in [
            "date", "amount", "txn_type", "source", "description",
            "upi_reference", "merchant", "category_id", "unique_hash",
            "raw_data", "ai_classified", "confidence",
        ]}

        _, is_new = await upsert_transaction(txn_clean)
        if is_new:
            saved += 1
        else:
            skipped += 1

    state.deduplication_stats["saved"]   = saved
    state.deduplication_stats["skipped"] = skipped
    logger.info(f"[LangGraph] Persisted: {saved} saved, {skipped} skipped")
    return state


async def node_reconcile(state: PGState) -> PGState:
    """Run reconciliation for the requested period."""
    from src.reports.reconciliation import ReconciliationEngine
    engine = ReconciliationEngine()

    period = state.period or "monthly"
    now    = datetime.now()

    if period in ("month", "monthly") or (state.period and len(state.period) > 3):
        result = await engine.monthly_reconcile(now.year, now.month)
    elif period in ("week", "weekly"):
        result = await engine.weekly_reconcile()
    else:
        result = await engine.daily_reconcile()

    state.reconciliation_result = result
    return state


async def node_report(state: PGState) -> PGState:
    """Generate report in requested format."""
    from src.reports.report_generator import ReportGenerator
    gen = ReportGenerator()

    data   = state.reconciliation_result or {}
    fmt    = state.export_format or "text"
    period = state.period or "monthly"

    if fmt == "dashboard":
        url = await gen.generate_dashboard(data, period)
        state.dashboard_url  = url
        state.response_text  = f"Dashboard ready: {url}\n(Auto-deletes in 24h)"
    elif fmt == "csv":
        path = await gen.export_csv(data, period)
        state.report_path   = path
        state.response_text = f"CSV exported to: {path}"
    elif fmt == "excel":
        path = await gen.export_excel(data, period)
        state.report_path   = path
        state.response_text = f"Excel exported to: {path}"
    else:
        state.response_text = gen.format_text_summary(data, period)

    return state


async def node_respond(state: PGState) -> PGState:
    """Format final WhatsApp response."""
    from src.whatsapp.response_formatter import format_response
    if not state.response_text and state.error:
        state.response_text = f"Error: {state.error}"
    elif not state.response_text:
        state.response_text = "Done! ✓"
    state.response_text = format_response(state.response_text)
    return state


# ── Routing logic ──────────────────────────────────────────────────────────

def route_after_intent(state: PGState) -> str:
    if state.iterations >= state.max_iterations:
        return "respond"
    if state.file_path:
        return "ingest_file"
    intent = state.intent
    if intent in ("summary", "rent_status", "expense_query"):
        return "reconcile"
    if intent == "export":
        return "reconcile"
    if intent == "add_transaction":
        return "respond"
    return "respond"


def route_after_ingest(state: PGState) -> str:
    needs_ai = any(t.get("needs_ai_review") for t in state.classified_transactions)
    return "classify" if needs_ai else "persist"


# ── Build graph ────────────────────────────────────────────────────────────

def build_graph() -> StateGraph:
    graph = StateGraph(PGState)

    graph.add_node("detect_intent", node_detect_intent)
    graph.add_node("ingest_file",   node_ingest_file)
    graph.add_node("classify",      node_classify)
    graph.add_node("persist",       node_persist)
    graph.add_node("reconcile",     node_reconcile)
    graph.add_node("report",        node_report)
    graph.add_node("respond",       node_respond)

    graph.set_entry_point("detect_intent")

    graph.add_conditional_edges("detect_intent", route_after_intent, {
        "ingest_file": "ingest_file",
        "reconcile":   "reconcile",
        "respond":     "respond",
    })
    graph.add_conditional_edges("ingest_file", route_after_ingest, {
        "classify": "classify",
        "persist":  "persist",
    })
    graph.add_edge("classify", "persist")
    graph.add_edge("persist",  "respond")
    graph.add_edge("reconcile","report")
    graph.add_edge("report",   "respond")
    graph.add_edge("respond",  END)

    return graph.compile()


# ── Public API ─────────────────────────────────────────────────────────────

_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


async def run(
    message: str = "",
    file_path: Optional[str] = None,
    sender_phone: Optional[str] = None,
    export_format: str = "text",
) -> PGState:
    """
    Main entry point. Returns the final PGState.
    Timeout = 30s enforced by caller.
    """
    state = PGState(
        message=message,
        file_path=file_path,
        sender_phone=sender_phone,
        export_format=export_format,
        max_iterations=int(os.getenv("LANGGRAPH_MAX_ITERATIONS", "2")),
    )
    graph = get_graph()
    result = await graph.ainvoke(state)
    return result
