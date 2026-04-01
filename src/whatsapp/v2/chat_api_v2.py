"""
src/whatsapp/v2/chat_api_v2.py
────────────────────────────────
FastAPI router for the v2 Supervisor Agent pipeline.

Endpoint:  POST /api/v2/whatsapp/process
Input:     InboundMessage(phone, message, message_id)
Output:    OutboundReply(reply, intent, role, confidence, skip)

Flow:
    1. !learn command intercept (admin/power_user only)
    2. Rate limit + role detection (same DB tables as v1)
    3. Active onboarding check (reuses v1 tenant_handler logic)
    4. Pending action check (disambiguation / correction flows — reuses v1 logic)
    5. Load conversation history
    6. Run LangGraph supervisor graph (Groq llama-3.1-70b-versatile)
    7. Save turn to conversation_history
    8. Return reply
"""
from __future__ import annotations

import json as _json
import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.db_manager import get_db_session as get_session
from src.database.models import PendingAction, WhatsappLog, MessageDirection, CallerRole
from src.whatsapp.intent_detector import _extract_entities
from src.whatsapp.role_service import get_caller_context
from src.whatsapp.handlers.owner_handler import resolve_pending_action, handle_learn_command
from src.whatsapp.handlers.tenant_handler import get_active_onboarding, handle_onboarding_step, resolve_tenant_complaint
from src.whatsapp.v2.memory import save_turn
from src.whatsapp.v2.supervisor import run_supervisor_graph

router = APIRouter(prefix="/api/v2/whatsapp", tags=["whatsapp-v2"])


# ── Schemas (same as v1 for drop-in compatibility) ────────────────────────────

class InboundMessage(BaseModel):
    phone:      str
    message:    str
    message_id: Optional[str] = None


class OutboundReply(BaseModel):
    reply:      str
    intent:     str
    role:       str
    confidence: float = 0.0
    skip:       bool  = False


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_active_pending(phone: str, session: AsyncSession) -> Optional[PendingAction]:
    """Return the most recent unresolved pending action for this phone, if not expired."""
    return await session.scalar(
        select(PendingAction).where(
            and_(
                PendingAction.phone == phone,
                PendingAction.resolved == False,      # noqa: E712
                PendingAction.expires_at > datetime.utcnow(),
            )
        ).order_by(PendingAction.created_at.desc())
    )


_ROLE_MAP = {
    "admin":        CallerRole.owner,
    "owner":        CallerRole.owner,
    "receptionist": CallerRole.owner,
    "tenant":       CallerRole.tenant,
    "lead":         CallerRole.lead,
    "blocked":      CallerRole.blocked,
}

async def _log(
    session: AsyncSession,
    phone: str,
    inbound: str,
    role: str,
    intent: str,
    reply: Optional[str],
) -> None:
    """Write inbound + outbound rows to whatsapp_log (same audit trail as v1)."""
    cr = _ROLE_MAP.get(role, CallerRole.unknown)
    wa_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
    session.add(WhatsappLog(
        direction=MessageDirection.inbound,
        caller_role=cr,
        from_number=phone,
        to_number=wa_id,
        message_text=inbound,
        intent=intent,
    ))
    if reply:
        session.add(WhatsappLog(
            direction=MessageDirection.outbound,
            caller_role=cr,
            from_number=wa_id,
            to_number=phone,
            message_text=reply,
            intent=intent,
        ))


def _learn_from_selection(original_msg: str, intent: str) -> None:
    """Persist exact-message → intent mapping to data/learned_rules.json."""
    import re as _re
    from pathlib import Path
    rules_path = Path("data/learned_rules.json")
    try:
        rules: list = _json.loads(rules_path.read_text(encoding="utf-8")) if rules_path.exists() else []
    except Exception:
        rules = []
    escaped = _re.escape(original_msg)
    for rule in rules:
        if rule.get("pattern") == escaped:
            rule["intent"] = intent
            rules_path.write_text(_json.dumps(rules, indent=2, ensure_ascii=False), encoding="utf-8")
            return
    rules.append({"pattern": escaped, "intent": intent, "confidence": 0.97, "applies_to": "owner", "active": True})
    rules_path.parent.mkdir(parents=True, exist_ok=True)
    rules_path.write_text(_json.dumps(rules, indent=2, ensure_ascii=False), encoding="utf-8")


# ── Main endpoint ─────────────────────────────────────────────────────────────

@router.post("/process", response_model=OutboundReply)
async def process_message_v2(
    body: InboundMessage,
    session: AsyncSession = Depends(get_session),
):
    """Process one inbound WhatsApp message via the v2 LangGraph supervisor pipeline."""
    try:
        return await _process_v2_inner(body, session)
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Unhandled error in process_message_v2")
        return OutboundReply(
            reply="Sorry, something went wrong. Please try again in a moment.",
            intent="ERROR", role="unknown",
        )


async def _process_v2_inner(
    body: InboundMessage,
    session: AsyncSession,
) -> OutboundReply:
    phone   = body.phone.strip()
    message = body.message.strip()

    # ── 0. !learn command — admin/power_user shortcut ─────────────────────
    if message.startswith("!learn"):
        ctx_quick = await get_caller_context(phone, session)
        if ctx_quick.role in ("admin", "owner"):
            reply = await handle_learn_command(message, ctx_quick, session)
            await _log(session, phone, message, ctx_quick.role, "LEARN_COMMAND", reply)
            await session.commit()
            return OutboundReply(reply=reply, intent="LEARN_COMMAND", role=ctx_quick.role)

    # ── 1. Rate limit + role detection ───────────────────────────────────
    ctx = await get_caller_context(phone, session)

    if ctx.is_blocked:
        await _log(session, phone, message, "blocked", "BLOCKED", None)
        await session.commit()
        return OutboundReply(reply="", intent="BLOCKED", role="blocked", skip=True)

    # ── 2a. Active onboarding session (tenant KYC) ────────────────────────
    if ctx.role == "tenant" and ctx.tenant_id:
        ob = await get_active_onboarding(ctx.tenant_id, session)
        if ob:
            data = _json.loads(ob.collected_data or "{}")
            name = data.get("name", ctx.name)
            if ob.step == "ask_gender" and message.lower() in ("hi", "hello", "hey", "start", ""):
                reply = (
                    f"*Welcome to the PG, {name}!*\n\n"
                    "Please answer a few quick questions to complete your check-in.\n\n"
                    "*Step 1 of 5*\n"
                    "What is your *gender*?\nReply: *male* / *female* / *other*"
                )
            else:
                reply = await handle_onboarding_step(ob, message, ctx, session)
            await _log(session, phone, message, ctx.role, "ONBOARDING", reply)
            await session.commit()
            return OutboundReply(reply=reply, intent="ONBOARDING", role=ctx.role)

    # ── 2b. Pending disambiguation / correction (owner roles) ────────────
    if ctx.role in ("admin", "owner", "receptionist"):
        pending = await _get_active_pending(phone, session)
        if pending:
            if pending.intent == "INTENT_AMBIGUOUS":
                choice       = message.strip().rstrip(".")
                choices_data = _json.loads(pending.choices or "[]")
                action_data  = _json.loads(pending.action_data or "{}")
                if choice.isdigit():
                    idx = int(choice) - 1
                    if 0 <= idx < len(choices_data):
                        selected_intent   = choices_data[idx]["intent"]
                        original_msg      = action_data.get("original_message", message)
                        resolved_entities = _extract_entities(original_msg, selected_intent)
                        _learn_from_selection(original_msg, selected_intent)
                        if "description" not in resolved_entities:
                            resolved_entities["description"] = original_msg
                        from src.whatsapp.gatekeeper import route
                        amb_reply = await route(selected_intent, resolved_entities, ctx, original_msg, session)
                        pending.resolved = True
                        await _log(session, phone, message, ctx.role, selected_intent, amb_reply)
                        await save_turn(phone, ctx.role, message, amb_reply, selected_intent, session)
                        await session.commit()
                        return OutboundReply(reply=amb_reply, intent=selected_intent, role=ctx.role)
                options   = "\n".join(f"*{c['seq']}*. {c['label']}" for c in choices_data)
                re_prompt = f"Please reply with a number:\n{options}"
                await _log(session, phone, message, ctx.role, "AMBIGUOUS", re_prompt)
                await session.commit()
                return OutboundReply(reply=re_prompt, intent="AMBIGUOUS", role=ctx.role)

            resolved_reply = await resolve_pending_action(pending, message, session)
            if resolved_reply:
                if resolved_reply.startswith("__KEEP_PENDING__"):
                    clean_reply = resolved_reply[len("__KEEP_PENDING__"):]
                    await _log(session, phone, message, ctx.role, "CONFIRMATION", clean_reply)
                    await session.commit()
                    return OutboundReply(reply=clean_reply, intent="CONFIRMATION", role=ctx.role)
                pending.resolved = True
                await _log(session, phone, message, ctx.role, "CONFIRMATION", resolved_reply)
                await session.commit()
                return OutboundReply(reply=resolved_reply, intent="CONFIRMATION", role=ctx.role)
            pending.resolved = True

    # ── 2c. Tenant complaint follow-up ───────────────────────────────────
    if ctx.role == "tenant":
        pending = await _get_active_pending(phone, session)
        if pending and pending.intent == "COMPLAINT_REGISTER":
            resolved_reply = await resolve_tenant_complaint(pending, message, session)
            pending.resolved = True
            await _log(session, phone, message, ctx.role, "COMPLAINT_REGISTER", resolved_reply)
            await save_turn(phone, ctx.role, message, resolved_reply, "COMPLAINT_REGISTER", session)
            await session.commit()
            return OutboundReply(reply=resolved_reply, intent="COMPLAINT_REGISTER", role=ctx.role)

    # ── 3. Run LangGraph supervisor ───────────────────────────────────────
    state = await run_supervisor_graph(
        user_id=phone,
        role=ctx.role,
        message=message,
        history=[],   # graph's load_context node loads history from DB directly
        ctx=ctx,
        session=session,
    )

    reply      = state.get("response") or ""
    v1_intent  = state.get("v1_intent") or "UNKNOWN"
    confidence = float(state.get("confidence") or 0.0)

    # ── 4. Persist turn + audit log ───────────────────────────────────────
    if reply:   # don't save empty bot responses (STATEMENT skips agent)
        await save_turn(phone, ctx.role, message, reply, v1_intent, session)
    await _log(session, phone, message, ctx.role, v1_intent, reply or None)
    await session.commit()

    return OutboundReply(
        reply=reply,
        intent=v1_intent,
        role=ctx.role,
        confidence=confidence,
    )
