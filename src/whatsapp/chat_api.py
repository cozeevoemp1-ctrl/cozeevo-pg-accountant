"""
FastAPI router: POST /api/whatsapp/process

Called by n8n after every inbound WhatsApp message.
n8n sends: { phone, message, message_id }
We return:  { reply, intent, role, skip }

Flow:
  1. Rate limit + role detection
  2. Check pending confirmation (disambiguation waiting for reply)  ← NEW
  3. Detect intent based on role
  4. Route to correct handler
  5. Log to whatsapp_log
  6. Return reply text to n8n
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

import logging
import re
import re as _re

from src.database.db_manager import get_db_session as get_session
from src.database.models import PendingAction, PendingLearning, WhatsappLog, MessageDirection, CallerRole, ChatMessage
from src.whatsapp.role_service import get_caller_context
from src.whatsapp.intent_detector import detect_intent, IntentResult, _extract_entities, _INTENT_LABELS
from src.whatsapp.gatekeeper import route
from src.whatsapp.handlers.owner_handler import resolve_pending_action, handle_learn_command
from src.whatsapp.handlers.tenant_handler import get_active_onboarding, handle_onboarding_step, resolve_tenant_complaint
from src.llm_gateway.claude_client import get_claude_client

# PydanticAI agent system (feature flag controlled)
_USE_PYDANTIC_AGENTS = os.getenv("USE_PYDANTIC_AGENTS", "false").lower() == "true"
_DEFAULT_PG_ID = os.getenv("DEFAULT_PG_ID", "")

_chat_logger = logging.getLogger(__name__)


async def _resolve_pg_id(session) -> str:
    """Get the active pg_id. Returns DEFAULT_PG_ID or first active PG."""
    if _DEFAULT_PG_ID:
        return _DEFAULT_PG_ID
    from src.database.models import PgConfig
    from sqlalchemy import select as _sel
    result = await session.execute(
        _sel(PgConfig).where(PgConfig.is_active == True).limit(1)
    )
    pg = result.scalars().first()
    return str(pg.id) if pg else ""


router = APIRouter(prefix="/api/whatsapp", tags=["whatsapp"])


class InboundMessage(BaseModel):
    phone:      str
    message:    str
    message_id: Optional[str] = None
    media_type: Optional[str] = None      # "image", "document", "video"
    media_id:   Optional[str] = None      # WhatsApp media ID
    media_url:  Optional[str] = None      # direct URL if available
    media_mime: Optional[str] = None      # "image/jpeg", "application/pdf"
    media_filename: Optional[str] = None


class OutboundReply(BaseModel):
    reply:               str
    intent:              str
    role:                str
    confidence:          float = 0.0
    skip:                bool  = False          # True = don't send reply (spam / non-text)
    interactive_payload: Optional[dict] = None  # set for button/list messages

# Intents that are safe to pass through even at low confidence
_LOW_CONF_PASSTHROUGH = frozenset({"HELP", "GENERAL", "SYSTEM_HARD_UNKNOWN", "BLOCKED", "ONBOARDING", "CONFIRMATION", "COMPLAINT_REGISTER", "AMBIGUOUS", "AI_CONVERSE"})


@router.post("/process", response_model=OutboundReply)
async def process_message(
    body: InboundMessage,
    session: AsyncSession = Depends(get_session),
):
    try:
        return await _process_message_inner(body, session)
    except Exception as _exc:
        import logging, traceback
        logging.getLogger(__name__).exception("Unhandled error in process_message")
        traceback.print_exc()  # ensure it goes to stderr
        return OutboundReply(
            reply="Sorry, something went wrong. Please try again in a moment.",
            intent="ERROR", role="unknown",
        )


async def _process_message_inner(
    body: InboundMessage,
    session: AsyncSession,
) -> OutboundReply:
    phone   = body.phone.strip()
    message = body.message.strip()

    # ── 0. Admin !learn command — intercept before any other processing ──
    if message.startswith("!learn"):
        ctx_quick = await get_caller_context(phone, session)
        if ctx_quick.role in ("admin", "owner"):
            reply = await handle_learn_command(message, ctx_quick, session)
            await _log(session, phone, message, ctx_quick.role, "LEARN_COMMAND", reply)
            await session.commit()
            return OutboundReply(reply=reply, intent="LEARN_COMMAND", role=ctx_quick.role)

    # ── 1. Rate limit + role ──────────────────────────────────────────────
    ctx = await get_caller_context(phone, session)

    if ctx.is_blocked:
        await _log(session, phone, message, "blocked", "BLOCKED", None)
        await session.commit()
        return OutboundReply(reply="", intent="BLOCKED", role="blocked", skip=True)

    # ── 1b. Load chat context for this phone ──────────────────────────────
    try:
        chat_context = await _load_chat_context(phone, session)
    except Exception:
        chat_context = ""

    # ── 2a. Check active onboarding session (tenant role) ────────────────
    if ctx.role == "tenant" and ctx.tenant_id:
        ob = await get_active_onboarding(ctx.tenant_id, session)
        if ob:
            import json as _json
            data = _json.loads(ob.collected_data or "{}")
            name = data.get("name", ctx.name)
            # First contact: send welcome + Q1 without consuming their message as an answer
            if ob.step == "ask_dob" and message.lower() in ("hi", "hello", "hey", "start", ""):
                total_steps = len([s for s in ["ask_dob", "ask_father_name", "ask_father_phone", "ask_address", "ask_email", "ask_occupation", "ask_gender", "ask_emergency_name", "ask_emergency_relationship", "ask_emergency_phone", "ask_id_type", "ask_id_number", "ask_id_photo", "ask_selfie"]])
                reply = (
                    f"*Welcome to Cozeevo, {name}!*\n\n"
                    "Please answer a few quick questions to complete your check-in.\n"
                    "Type *skip* for any field you want to skip.\n\n"
                    f"*Step 1 of {total_steps}*\n"
                    "Your *date of birth*? (DD/MM/YYYY)\nOr type *skip*."
                )
            else:
                reply = await handle_onboarding_step(
                    ob, message, ctx, session,
                    media_id=body.media_id,
                    media_type=body.media_type,
                    media_mime=body.media_mime,
                )
            await _log(session, phone, message, ctx.role, "ONBOARDING", reply)
            await session.commit()
            return OutboundReply(reply=reply, intent="ONBOARDING", role=ctx.role)

    # ── 2b. Check pending disambiguation (owner) or complaint follow-up (tenant) ──
    if ctx.role in ("admin", "owner", "receptionist"):
        pending = await _get_active_pending(ctx.phone, session)
        _chat_logger.info("Pending check for %s: %s (intent=%s, resolved=%s)",
                          phone, "FOUND" if pending else "NONE",
                          pending.intent if pending else "-",
                          pending.resolved if pending else "-")
        # File-based debug log for VPS tracing
        import json as _dbg_json
        with open("/tmp/pg_pending_debug.log", "a") as _dbg:
            _dbg.write(f"[{datetime.utcnow().isoformat()}] phone={ctx.phone} msg={message[:60]} "
                       f"pending={'FOUND id=' + str(pending.id) + ' intent=' + pending.intent + ' step=' + _dbg_json.loads(pending.action_data or '{}').get('step','?') if pending else 'NONE'}\n")
        if pending:
            # ── Mid-flow breakout detection ────────────────────────────────────
            import json as _jbr
            _step = _jbr.loads(pending.action_data or "{}").get("step", "")
            _free_text_steps = {"ask_notes", "ask_description"}
            _breakout = _detect_mid_flow_breakout(message, pending.intent, skip_new_intent=(_step in _free_text_steps))
            if _breakout == "cancel":
                pending.resolved = True
                cancel_reply = "Cancelled. What would you like to do?"
                await _log(session, phone, message, ctx.role, "CANCEL", cancel_reply)
                await session.commit()
                return OutboundReply(reply=cancel_reply, intent="CANCEL", role=ctx.role)
            if _breakout in ("greeting", "new_intent"):
                # Clear pending and fall through to normal intent detection
                pending.resolved = True

            # ── Intent-ambiguity resolution (e.g. "Raj 31st March" → checkin or checkout?) ──
            if not pending.resolved and pending.intent == "INTENT_AMBIGUOUS":
                import json as _j
                choice = message.strip().rstrip(".")
                choices_data = _j.loads(pending.choices or "[]")
                action_data  = _j.loads(pending.action_data or "{}")
                if choice.isdigit():
                    idx = int(choice) - 1
                    if 0 <= idx < len(choices_data):
                        selected_intent   = choices_data[idx]["intent"]
                        original_msg      = action_data.get("original_message", message)
                        resolved_entities = _extract_entities(original_msg, selected_intent)
                        # ── Learn: store this pattern→intent mapping ──────────────────
                        _learn_from_selection(original_msg, selected_intent)
                        if _USE_PYDANTIC_AGENTS:
                            _pg_id = await _resolve_pg_id(session)
                            if _pg_id:
                                from src.llm_gateway.agents.learning_agent import learn_from_interaction
                                import asyncio as _asyncio
                                _asyncio.create_task(learn_from_interaction(
                                    pg_id=_pg_id, message=original_msg, phone=phone, role=ctx.role,
                                    regex_result=None, regex_confidence=None,
                                    llm_result=selected_intent, llm_confidence=0.8,
                                    final_intent=selected_intent, entities=action_data.get("entities", {}),
                                    source="user_selection", session=session,
                                ))
                        # ── Route with the chosen intent ──────────────────────────────
                        if "description" not in resolved_entities:
                            resolved_entities["description"] = original_msg
                        amb_reply = await route(selected_intent, resolved_entities, ctx, original_msg, session)
                        pending.resolved = True
                        await _log(session, phone, message, ctx.role, selected_intent, amb_reply)
                        await session.commit()
                        return OutboundReply(reply=amb_reply, intent=selected_intent, role=ctx.role)
                # Invalid choice — re-prompt
                options = "\n".join(f"*{c['seq']}*. {c['label']}" for c in choices_data)
                re_prompt = f"Please reply with a number:\n{options}"
                await _log(session, phone, message, ctx.role, "AMBIGUOUS", re_prompt)
                await session.commit()
                return OutboundReply(reply=re_prompt, intent="AMBIGUOUS", role=ctx.role)

            # ── RECEIPT_SELECT: user picking which payment a receipt belongs to ──
            if not pending.resolved and pending.intent == "RECEIPT_SELECT":
                import json as _jr
                choice = message.strip()
                if choice.isdigit():
                    choices_data = _jr.loads(pending.choices or "[]")
                    action_data = _jr.loads(pending.action_data or "{}")
                    idx = int(choice) - 1
                    from src.whatsapp.handlers.receipt_handler import resolve_receipt_selection
                    rcpt_reply = await resolve_receipt_selection(idx, choices_data, action_data, phone, session)
                    pending.resolved = True
                    await _log(session, phone, message, ctx.role, "ATTACH_RECEIPT", rcpt_reply)
                    await session.commit()
                    return OutboundReply(reply=rcpt_reply, intent="ATTACH_RECEIPT", role=ctx.role)

            # ── MEDIA_CLASSIFY: user selecting document type for an uploaded photo ──
            if not pending.resolved and pending.intent == "MEDIA_CLASSIFY":
                import json as _jm
                choice = message.strip()
                if choice.isdigit():
                    choices_data = _jm.loads(pending.choices or "[]")
                    action_data = _jm.loads(pending.action_data or "{}")
                    idx = int(choice) - 1
                    from src.whatsapp.handlers.receipt_handler import handle_media_classify_selection
                    cls_reply = await handle_media_classify_selection(idx, choices_data, action_data, phone, ctx, session)
                    pending.resolved = True
                    await _log(session, phone, message, ctx.role, "MEDIA_CLASSIFY", cls_reply)
                    await session.commit()
                    return OutboundReply(reply=cls_reply, intent="MEDIA_CLASSIFY", role=ctx.role)

            # ── RECEIPT_NO_PAYMENT: receipt uploaded but no payment found, user typing payment details ──
            if not pending.resolved and pending.intent == "RECEIPT_NO_PAYMENT":
                # User should type "Raj 15000 cash april" — treat as PAYMENT_LOG
                import json as _jn
                action_data = _jn.loads(pending.action_data or "{}")
                pending.resolved = True
                # Re-inject as a payment log with the saved receipt
                intent_result = detect_intent(message, ctx.role)
                if intent_result.intent == "PAYMENT_LOG":
                    intent_result.entities["_receipt_file_path"] = action_data.get("file_path", "")
                    reply = await route("PAYMENT_LOG", intent_result.entities, ctx, message, session)
                    await _log(session, phone, message, ctx.role, "PAYMENT_LOG", reply)
                    await session.commit()
                    return OutboundReply(reply=reply, intent="PAYMENT_LOG", role=ctx.role)

            # ── AWAITING_CLARIFICATION: bot asked follow-up, this is the answer ──
            if not pending.resolved and pending.intent == "AWAITING_CLARIFICATION":
                import json as _jc
                import re as _re
                ad = _jc.loads(pending.action_data or "{}")
                original_intent = ad.get("original_intent", "")
                waiting_for     = ad.get("waiting_for", "")
                orig_entities   = dict(ad.get("entities") or {})

                _MONTHS_MAP = {
                    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
                    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
                    "january": 1, "february": 2, "march": 3, "april": 4,
                    "june": 6, "july": 7, "august": 8, "september": 9,
                    "october": 10, "november": 11, "december": 12,
                }
                if waiting_for == "month":
                    found_month = None
                    for abbr, num in _MONTHS_MAP.items():
                        if _re.search(r"\b" + abbr + r"\b", message, _re.I):
                            found_month = num
                            break
                    if not found_month:
                        re_prompt = "Please name a month, e.g. *Jan*, *Feb*, *March*, *April*..."
                        await _log(session, phone, message, ctx.role, "CLARIFICATION", re_prompt)
                        await session.commit()
                        return OutboundReply(reply=re_prompt, intent="CLARIFICATION", role=ctx.role)
                    orig_entities["month"] = found_month
                elif waiting_for == "tenant_name":
                    orig_entities["name"] = message.strip()

                pending.resolved = True
                clarif_reply = await route(original_intent, orig_entities, ctx, message, session)
                await _log(session, phone, message, ctx.role, original_intent, clarif_reply)
                await session.commit()
                return OutboundReply(reply=clarif_reply, intent=original_intent, role=ctx.role)

            # ── AI correction detection: "no, name is X" → correction, not cancel ──
            if not pending.resolved and _is_correction_message(message):
                try:
                    _pending_data = _jbr.loads(pending.action_data or "{}")
                    _pending_desc = f"Pending: {pending.intent}, step: {_pending_data.get('step', 'confirm')}, data: {json.dumps({k: v for k, v in _pending_data.items() if k != 'step' and not k.startswith('_')}, default=str)[:300]}"
                    ai = get_claude_client()
                    conv = await ai.manage_conversation(
                        message=message,
                        role=ctx.role,
                        chat_history=chat_context,
                        pending_context=_pending_desc,
                    )
                    if conv.get("action") == "correct_field" and conv.get("correction"):
                        _field = conv["correction"].get("field", "")
                        _value = conv["correction"].get("value", "")
                        if _field and _value:
                            _pending_data[_field] = _value
                            # Update EXISTING pending in-place (don't create new one)
                            pending.action_data = json.dumps(_pending_data, default=str)
                            pending.expires_at = datetime.utcnow() + timedelta(minutes=30)
                            await session.flush()
                            # Build confirmation summary
                            _summary_parts = []
                            for _k, _v in _pending_data.items():
                                if _k not in ("step", "logged_by") and not _k.startswith("_") and _v:
                                    _summary_parts.append(f"  {_k.title()}: *{_v}*")
                            _summary = "\n".join(_summary_parts) if _summary_parts else ""
                            corr_reply = f"Updated *{_field}* to *{_value}*.\n\n{_summary}\n\nReply *Yes* to confirm or correct again."
                            await _log(session, phone, message, ctx.role, "CORRECTION", corr_reply)
                            await session.commit()
                            return OutboundReply(reply=corr_reply, intent="CORRECTION", role=ctx.role)
                    if conv.get("action") == "ask_what_to_change":
                        ask_reply = conv.get("reply") or "What would you like to change?"
                        # Extend pending expiry so it stays alive
                        pending.expires_at = datetime.utcnow() + timedelta(minutes=30)
                        await session.flush()
                        await _log(session, phone, message, ctx.role, "CORRECTION", ask_reply)
                        await session.commit()
                        return OutboundReply(reply=ask_reply, intent="CORRECTION", role=ctx.role)
                except Exception as _corr_err:
                    _chat_logger.warning("AI correction detection failed: %s", _corr_err)

            if not pending.resolved:
                _chat_logger.info("Calling resolve_pending_action: intent=%s, msg=%s, step=%s",
                                  pending.intent, message[:50],
                                  _jbr.loads(pending.action_data or "{}").get("step", "?"))
                try:
                    resolved_reply = await resolve_pending_action(
                        pending, message, session,
                        media_id=body.media_id, media_type=body.media_type, media_mime=body.media_mime,
                    )
                except Exception as _resolve_err:
                    resolved_reply = None
                    with open("/tmp/pg_pending_debug.log", "a") as _dbg:
                        _dbg.write(f"  RESOLVE ERROR: {_resolve_err}\n")
                    import traceback
                    traceback.print_exc()
                _chat_logger.info("resolve_pending_action returned: %s", repr(resolved_reply[:100]) if resolved_reply else "None")
                with open("/tmp/pg_pending_debug.log", "a") as _dbg:
                    _dbg.write(f"  resolve_reply={'None' if resolved_reply is None else repr(resolved_reply[:100])}\n")
            else:
                resolved_reply = None
                _chat_logger.info("Pending already resolved, skipping resolve_pending_action")
                with open("/tmp/pg_pending_debug.log", "a") as _dbg:
                    _dbg.write(f"  ALREADY RESOLVED — skipped\n")
            if resolved_reply:
                # Prefix "__KEEP_PENDING__" means correction re-prompt — keep pending alive
                if resolved_reply.startswith("__KEEP_PENDING__"):
                    clean_reply = resolved_reply[len("__KEEP_PENDING__"):]
                    await _log(session, phone, message, ctx.role, "CONFIRMATION", clean_reply)
                    await session.commit()
                    return OutboundReply(reply=clean_reply, intent="CONFIRMATION", role=ctx.role)
                pending.resolved = True
                await _log(session, phone, message, ctx.role, "CONFIRMATION", resolved_reply)
                await session.commit()
                with open("/tmp/pg_pending_debug.log", "a") as _dbg:
                    _dbg.write(f"  RETURNED: {resolved_reply[:80]}\n")
                return OutboundReply(reply=resolved_reply, intent="CONFIRMATION", role=ctx.role)
            pending.resolved = True
            with open("/tmp/pg_pending_debug.log", "a") as _dbg:
                _dbg.write(f"  FELL THROUGH — resolved_reply was None, pending killed\n")

    if ctx.role == "tenant":
        pending = await _get_active_pending(ctx.phone, session)
        if pending and pending.intent == "COMPLAINT_REGISTER":
            resolved_reply = await resolve_tenant_complaint(pending, message, session)
            pending.resolved = True
            await _log(session, phone, message, ctx.role, "COMPLAINT_REGISTER", resolved_reply)
            await session.commit()
            return OutboundReply(reply=resolved_reply, intent="COMPLAINT_REGISTER", role=ctx.role)

    # ── 3. Detect intent — Groq LLM primary, regex fast-path ────────────
    # Try regex first for speed (instant, free)
    intent_result = detect_intent(message, ctx.role)
    intent = intent_result.intent

    # ── Follow-up detection: "show me the list", "break it down" etc. ──
    if intent in ("UNKNOWN", "GENERAL"):
        from src.llm_gateway.agents.flexible_query import _FOLLOWUP_PATTERNS, get_query_context
        if _FOLLOWUP_PATTERNS.search(message) and get_query_context(ctx.phone):
            from src.llm_gateway.agents.flexible_query import run_flexible_query
            chat_context = await _load_chat_context(ctx.phone, session, limit=8)
            flex_reply = await run_flexible_query(message, session, ctx.role, chat_context, ctx.phone)
            await _log(session, phone, message, ctx.role, "QUERY_FLEXIBLE", flex_reply)
            await session.commit()
            return OutboundReply(reply=flex_reply, intent="QUERY_FLEXIBLE", role=ctx.role)

    # ── PydanticAI agent path (feature flag) ─────────────────────────
    if _USE_PYDANTIC_AGENTS and intent in ("UNKNOWN", "GENERAL"):
        pg_id = await _resolve_pg_id(session)
        if pg_id:
            from src.llm_gateway.agents.conversation_agent import run_conversation_agent
            from src.llm_gateway.agents.learning_agent import learn_from_interaction
            import asyncio as _asyncio

            chat_context = await _load_chat_context(ctx.phone, session, limit=8)
            agent_result = await run_conversation_agent(
                message=message, role=ctx.role, phone=ctx.phone,
                pg_id=pg_id, session=session,
                chat_history=chat_context, pending_context="",
            )

            if agent_result.action == "classify" and agent_result.intent:
                intent = agent_result.intent
                entities = agent_result.entities or {}
                entities.update(_extract_entities(message, intent))
                intent_result = IntentResult(intent=intent, confidence=agent_result.confidence, entities=entities)
                _asyncio.create_task(learn_from_interaction(
                    pg_id=pg_id, message=message, phone=ctx.phone, role=ctx.role,
                    regex_result=None, regex_confidence=None,
                    llm_result=intent, llm_confidence=agent_result.confidence,
                    final_intent=intent, entities=entities, source="auto_confirmed",
                    session=session,
                ))

                # ── Flexible query: answer directly, don't route to gatekeeper ──
                if intent == "QUERY_FLEXIBLE":
                    from src.llm_gateway.agents.flexible_query import run_flexible_query
                    flex_reply = await run_flexible_query(message, session, ctx.role, chat_context, ctx.phone)
                    await _log(session, phone, message, ctx.role, "QUERY_FLEXIBLE", flex_reply)
                    await session.commit()
                    return OutboundReply(reply=flex_reply, intent="QUERY_FLEXIBLE", role=ctx.role)

                # Fall through to gatekeeper routing

            elif agent_result.action == "ask_options" and agent_result.options:
                from src.whatsapp.handlers._shared import _save_pending
                choices_list = [
                    {"seq": i + 1, "intent": opt, "label": _INTENT_LABELS.get(opt, opt)}
                    for i, opt in enumerate(agent_result.options)
                ]
                action_data = json.dumps({"original_message": message, "entities": agent_result.entities or {}})
                await _save_pending(ctx.phone, "INTENT_AMBIGUOUS", action_data, choices_list, session)
                _asyncio.create_task(learn_from_interaction(
                    pg_id=pg_id, message=message, phone=ctx.phone, role=ctx.role,
                    regex_result=None, regex_confidence=None,
                    llm_result=str(agent_result.options), llm_confidence=agent_result.confidence,
                    final_intent="INTENT_AMBIGUOUS", entities={}, source="pending_selection",
                    session=session,
                ))
                reply = agent_result.reply or ("Did you mean:\n" + "\n".join(
                    f"{c['seq']}. {c['label']}" for c in choices_list
                ))
                await _log(session, phone, message, ctx.role, "INTENT_AMBIGUOUS", reply)
                await session.commit()
                return OutboundReply(reply=reply, intent="INTENT_AMBIGUOUS", role=ctx.role)

            elif agent_result.action == "converse" and agent_result.reply:
                _asyncio.create_task(learn_from_interaction(
                    pg_id=pg_id, message=message, phone=ctx.phone, role=ctx.role,
                    regex_result=None, regex_confidence=None,
                    llm_result="CONVERSE", llm_confidence=agent_result.confidence,
                    final_intent="CONVERSE", entities={}, source="conversation",
                    session=session,
                ))
                await _log(session, phone, message, ctx.role, "CONVERSE", agent_result.reply)
                await session.commit()
                return OutboundReply(reply=agent_result.reply, intent="CONVERSE", role=ctx.role)

            elif agent_result.action == "clarify" and agent_result.reply:
                await _log(session, phone, message, ctx.role, "CLARIFY", agent_result.reply)
                await session.commit()
                return OutboundReply(reply=agent_result.reply, intent="CLARIFY", role=ctx.role)

    # If regex is confident (>=0.90), use it. Otherwise, call Groq for better understanding.
    if intent == "UNKNOWN" or intent_result.confidence < 0.90:
        try:
            ai = get_claude_client()
            ai_result = await ai.detect_whatsapp_intent(message, ctx.role)
            ai_intent = str(ai_result.get("intent", "UNKNOWN")).upper()
            ai_conf   = float(ai_result.get("confidence", 0.5))
            ai_entities = dict(ai_result.get("entities") or {})

            # Use AI result if it's confident, or if regex was UNKNOWN
            if ai_intent != "UNKNOWN" and (ai_conf >= 0.6 or intent == "UNKNOWN"):
                # Merge entities: AI + regex (keep non-null from both, AI takes precedence for name)
                merged = {}
                for k, v in intent_result.entities.items():
                    if v is not None:
                        merged[k] = v
                for k, v in ai_entities.items():
                    if v is not None:
                        merged[k] = v
                intent_result = IntentResult(intent=ai_intent, confidence=ai_conf, entities=merged)
                intent = ai_intent
                _chat_logger.info("Groq classified: %s (%.2f) for %s", ai_intent, ai_conf, phone)
        except Exception as e:
            _chat_logger.warning("Groq intent detection failed: %s — using regex result", e)

    # ── 3a. Image + expense keyword = always LOG (not query) ──
    if body.media_id and body.media_type == "image" and intent in ("QUERY_EXPENSES", "UNKNOWN"):
        _EXPENSE_KW = re.compile(r"\b(eb|bill|electricity|water|internet|salary|maintenance|plumber|repair|groceries?|cleaning|diesel|generator|receipt)\b", re.I)
        if _EXPENSE_KW.search(message):
            intent = "ADD_EXPENSE"
            intent_result = IntentResult(intent="ADD_EXPENSE", confidence=0.90, entities=intent_result.entities)
            _chat_logger.info("Image + expense keyword: forced ADD_EXPENSE for %s", phone)

    # ── 3a2. Image with no specific intent → media classify + receipt handler ──
    if body.media_id and body.media_type == "image" and intent in ("UNKNOWN", "GENERAL"):
        from src.whatsapp.handlers.receipt_handler import handle_media_upload
        media_reply = await handle_media_upload(
            media_id=body.media_id, media_mime=body.media_mime or "image/jpeg",
            caption=message, phone=phone, ctx=ctx, session=session,
        )
        await _log(session, phone, message, ctx.role, "MEDIA_UPLOAD", media_reply)
        await session.commit()
        return OutboundReply(reply=media_reply, intent="MEDIA_UPLOAD", role=ctx.role)

    # ── 3b. Duplicate-log prevention: if user just logged something similar, treat as query ──
    _LOG_INTENTS = {"ADD_EXPENSE", "LOG_EXPENSE", "PAYMENT_LOG"}
    if intent in _LOG_INTENTS and not re.search(r"\b(log|add|record|save|enter)\b", message, re.I):
        from src.database.models import WhatsappLog, MessageDirection
        five_min_ago = datetime.utcnow() - timedelta(minutes=5)
        recent_reply = await session.scalar(
            select(WhatsappLog).where(
                WhatsappLog.to_number == phone,
                WhatsappLog.direction == MessageDirection.outbound,
                WhatsappLog.created_at >= five_min_ago,
                WhatsappLog.intent.in_(list(_LOG_INTENTS) + ["CONFIRMATION"]),
            ).order_by(WhatsappLog.created_at.desc()).limit(1)
        )
        if recent_reply and recent_reply.message_text:
            reply_lower = recent_reply.message_text.lower()
            if any(w in reply_lower for w in ("saved", "logged", "recorded", "added", "expense saved")):
                _chat_logger.info("Duplicate-log prevention: %s -> QUERY_EXPENSES for %s", intent, phone)
                intent = "QUERY_EXPENSES"
                intent_result = IntentResult(intent="QUERY_EXPENSES", confidence=0.8, entities=intent_result.entities)

    # ── 3c. Follow-up detection: pronoun-style messages referencing last turn ──
    if intent == "UNKNOWN" and chat_context:
        followup = _detect_followup_context(message, chat_context)
        if followup:
            followup_entities = _extract_entities(message, "QUERY_TENANT")
            if "room" in followup and "room" not in followup_entities:
                followup_entities["room"] = followup["room"]
            if "name" in followup and "name" not in followup_entities:
                followup_entities["name"] = followup["name"]
            followup_entities["_chat_context"] = chat_context
            followup_entities["description"] = message
            intent_result = IntentResult(
                intent="QUERY_TENANT",
                confidence=0.85,
                entities=followup_entities,
            )
            intent = "QUERY_TENANT"
            _chat_logger.info(
                "Follow-up detected for %s: re-routed to QUERY_TENANT with %s",
                phone, {k: v for k, v in followup.items()},
            )

    # (Groq AI fallback already handled in step 3 above)

    # ── Self-learning: log unrecognised messages for admin review ─────────
    if intent == "UNKNOWN":
        session.add(PendingLearning(
            phone=ctx.phone,
            role=ctx.role,
            message=message[:1000],
            detected_intent="UNKNOWN",
        ))

    # ── 3b. Low-confidence / UNKNOWN → AI conversation manager ─────────
    # Instead of dead-end "I didn't understand", use Groq to have a
    # natural conversation that guides toward the right intent.
    if (
        intent_result.confidence < 0.70
        and intent not in _LOW_CONF_PASSTHROUGH
        and ctx.role != "lead"   # leads always get conversational handling
    ):
        try:
            ai = get_claude_client()
            conv_result = await ai.manage_conversation(
                message=message,
                role=ctx.role,
                chat_history=chat_context,
            )
            conv_action = str(conv_result.get("action", "converse")).upper()
            conv_conf = float(conv_result.get("confidence", 0.5))
            conv_entities = dict(conv_result.get("entities") or {})

            # If AI found a real intent with decent confidence, route it
            if conv_action not in ("CONVERSE", "CANCEL", "CONFIRM", "CORRECT_FIELD", "ASK_WHAT_TO_CHANGE") and conv_conf >= 0.6:
                if "description" not in conv_entities:
                    conv_entities["description"] = message
                intent_result = IntentResult(intent=conv_action, confidence=conv_conf, entities=conv_entities)
                intent = conv_action
                _chat_logger.info("AI conversation manager routed: %s (%.2f) for %s", conv_action, conv_conf, phone)
                # Fall through to normal routing below
            else:
                # AI chose to converse — return its natural reply
                conv_reply = conv_result.get("reply") or "Could you tell me more? Type *help* to see what I can do."
                await _log(session, phone, message, ctx.role, "AI_CONVERSE", conv_reply)
                await session.commit()
                try:
                    await _save_chat_message(session, phone, "inbound", message, "UNKNOWN", ctx.role)
                    await _save_chat_message(session, phone, "outbound", conv_reply, "AI_CONVERSE", ctx.role)
                    await session.commit()
                except Exception:
                    await session.rollback()
                return OutboundReply(
                    reply=conv_reply,
                    intent="AI_CONVERSE",
                    role=ctx.role,
                    confidence=conv_conf,
                )
        except Exception as e:
            _chat_logger.warning("AI conversation manager failed: %s — using fallback", e)
            hard_reply = (
                "I'm not quite sure what you mean. Could you rephrase?\n\n"
                "Type *help* to see what I can do."
            )
            await _log(session, phone, message, ctx.role, "SYSTEM_HARD_UNKNOWN", hard_reply)
            await session.commit()
            return OutboundReply(
                reply=hard_reply,
                intent="SYSTEM_HARD_UNKNOWN",
                role=ctx.role,
                confidence=intent_result.confidence,
            )

    # ── 3c. Ambiguous intent — ask user to choose ────────────────────────
    if intent == "AMBIGUOUS" and ctx.role in ("admin", "owner"):
        alternatives = intent_result.entities.get("alternatives", [])
        alt_labels   = intent_result.entities.get("alt_labels", alternatives)
        choices_list = [
            {"seq": i + 1, "intent": alt, "label": _INTENT_LABELS.get(alt, lbl)}
            for i, (alt, lbl) in enumerate(zip(alternatives, alt_labels))
        ]
        action_data = {
            "original_message": message,
            "name":  intent_result.entities.get("name", ""),
            "date":  intent_result.entities.get("date", ""),
        }
        # Save as INTENT_AMBIGUOUS pending action (30-min expiry)
        from src.whatsapp.handlers._shared import _save_pending
        await _save_pending(phone, "INTENT_AMBIGUOUS", action_data, choices_list, session)
        options_txt = "\n".join(f"*{c['seq']}.* {c['label']}" for c in choices_list)
        name_str    = intent_result.entities.get("name", "")
        date_str    = intent_result.entities.get("date", "")
        try:
            from datetime import date as _d
            date_fmt = _d.fromisoformat(date_str).strftime("%d %b") if date_str else ""
        except Exception:
            date_fmt = date_str
        context = f" ({name_str}{' on ' + date_fmt if date_fmt else ''})" if name_str else ""
        amb_reply = (
            f"*What did you mean{context}?*\n\n"
            f"{options_txt}\n\n"
            "Reply *1* or *2*."
        )
        await _log(session, phone, message, ctx.role, "AMBIGUOUS", amb_reply)
        await session.commit()
        return OutboundReply(reply=amb_reply, intent="AMBIGUOUS", role=ctx.role)

    # ── 4. Route to handler ───────────────────────────────────────────────
    # Always include raw message so handlers (e.g. complaint) can use it
    if "description" not in intent_result.entities or not intent_result.entities["description"]:
        intent_result.entities["description"] = message

    # Inject chat context so handlers can use it (AI calls, unknown handlers)
    if chat_context:
        intent_result.entities["_chat_context"] = chat_context

    # Pass media info to intent handlers (for image-based form extraction etc.)
    if body.media_id:
        intent_result.entities["_media_id"] = body.media_id
        intent_result.entities["_media_type"] = body.media_type
        intent_result.entities["_media_mime"] = body.media_mime

    reply = await route(intent, intent_result.entities, ctx, message, session)

    # ── 4a. No reply = bot disabled for this role (tenant/lead) ───────────
    if reply is None:
        await _log(session, phone, message, ctx.role, intent, None)
        await session.commit()
        return OutboundReply(reply="", intent=intent, role=ctx.role, skip=True)

    # ── 4b. Attach interactive payload for menu intents ───────────────────
    interactive_payload = None
    if intent in ("HELP", "MORE_MENU") and ctx.role in ("admin", "owner"):
        interactive_payload = _build_owner_interactive(intent, reply, ctx)

    # ── 5. Log ────────────────────────────────────────────────────────────
    await _log(session, phone, message, ctx.role, intent, reply)
    await session.commit()

    # Save chat context AFTER main commit (so pending actions aren't lost if chat_messages table missing)
    try:
        await _save_chat_message(session, phone, "inbound", message, intent, ctx.role)
        await _save_chat_message(session, phone, "outbound", reply, intent, ctx.role)
        await session.commit()
    except Exception:
        await session.rollback()

    return OutboundReply(
        reply=reply, intent=intent, role=ctx.role,
        confidence=intent_result.confidence,
        interactive_payload=interactive_payload,
    )


def _build_owner_interactive(intent: str, reply_text: str, ctx) -> Optional[dict]:
    """
    Build a Meta WhatsApp interactive list message for owner HELP / MORE_MENU.
    Both intents show the same full services menu (like HP Gas WhatsApp).
    """
    if intent not in ("HELP", "MORE_MENU"):
        return None

    # WhatsApp interactive body max = 1024 chars
    body = reply_text.split("\n\n")[0].strip()[:1024] or "Select a service below."

    return {
        "type": "interactive",
        "interactive": {
            "type": "list",
            "header": {"type": "text", "text": "Cozeevo Help Desk"},
            "body":   {"text": body},
            "footer": {"text": "Cozeevo Co-living"},
            "action": {
                "button": "View Services",
                "sections": [
                    {
                        "title": "Rent & Payments",
                        "rows": [
                            {"id": "PAYMENT_LOG",  "title": "Log Payment",      "description": "Record rent received"},
                            {"id": "QUERY_DUES",   "title": "Who Owes",          "description": "Pending dues list"},
                            {"id": "REPORT",       "title": "Monthly Report",    "description": "Income & expense summary"},
                        ],
                    },
                    {
                        "title": "Tenants & Rooms",
                        "rows": [
                            {"id": "ADD_TENANT",     "title": "Check-in",        "description": "New tenant (text or photo)"},
                            {"id": "CHECKOUT",       "title": "Checkout",        "description": "Exit process (text or photo)"},
                            {"id": "QUERY_TENANT",   "title": "Tenant Info",     "description": "Balance & payment history"},
                            {"id": "QUERY_VACANT_ROOMS", "title": "Vacant Rooms", "description": "Empty beds by floor"},
                        ],
                    },
                    {
                        "title": "Operations",
                        "rows": [
                            {"id": "ADD_EXPENSE",        "title": "Log Expense",     "description": "EB, salary, maintenance"},
                            {"id": "COMPLAINT_REGISTER", "title": "Report Issue",    "description": "Plumbing, electric, wifi"},
                            {"id": "SEND_REMINDER_ALL",  "title": "Send Reminders",  "description": "Remind all unpaid tenants"},
                        ],
                    },
                ],
            },
        },
    }


def _learn_from_selection(original_msg: str, intent: str) -> None:
    """Store exact message → intent in learned_rules.json so it fires automatically next time."""
    import json, re as _re
    from pathlib import Path
    rules_path = Path("data/learned_rules.json")
    try:
        rules: list = json.loads(rules_path.read_text(encoding="utf-8")) if rules_path.exists() else []
    except Exception:
        rules = []
    escaped = _re.escape(original_msg)
    for rule in rules:
        if rule.get("pattern") == escaped:
            rule["intent"] = intent
            rules_path.write_text(json.dumps(rules, indent=2, ensure_ascii=False), encoding="utf-8")
            return
    rules.append({"pattern": escaped, "intent": intent, "confidence": 0.97, "applies_to": "owner", "active": True})
    rules_path.parent.mkdir(parents=True, exist_ok=True)
    rules_path.write_text(json.dumps(rules, indent=2, ensure_ascii=False), encoding="utf-8")


# ── Chat history helpers ──────────────────────────────────────────────────────

async def _save_chat_message(
    session: AsyncSession,
    phone: str,
    direction: str,
    message: str,
    intent: Optional[str] = None,
    role: Optional[str] = None,
) -> None:
    """Save a single chat message (inbound or outbound) to chat_messages table."""
    session.add(ChatMessage(
        phone=phone,
        direction=direction,
        message=message[:4000] if message else "",
        intent=intent,
        role=role,
        created_at=datetime.utcnow(),
    ))


async def _load_chat_context(phone: str, session: AsyncSession, limit: int = 5) -> str:
    """
    Load last N messages for this phone, format as context string.
    Returns empty string if no history.
    """
    from sqlalchemy import desc
    rows = (await session.execute(
        select(ChatMessage)
        .where(ChatMessage.phone == phone)
        .order_by(desc(ChatMessage.created_at))
        .limit(limit)
    )).scalars().all()

    if not rows:
        return ""

    # Rows are newest-first; reverse for chronological display
    rows = list(reversed(rows))
    lines = []
    for row in rows:
        prefix = "You" if row.direction == "inbound" else "Bot"
        # Truncate long messages for context
        text = (row.message or "")[:200]
        if len(row.message or "") > 200:
            text += "..."
        lines.append(f"{prefix}: {text}")

    return "[Recent context]\n" + "\n".join(lines)


# ── Mid-flow breakout detection ───────────────────────────────────────────────

# Intents that are clearly new actions (not answers to a pending question)
_NEW_INTENT_TRIGGERS = frozenset({
    "PAYMENT_LOG", "ADD_EXPENSE", "ADD_TENANT", "CHECKOUT", "NOTICE_GIVEN",
    "REPORT", "QUERY_DUES", "QUERY_VACANT_ROOMS", "VOID_PAYMENT",
    "ROOM_TRANSFER", "RENT_CHANGE", "QUERY_TENANT",
})

_CANCEL_WORDS = frozenset({
    "cancel", "stop", "abort", "nevermind", "never mind", "nvm",
    "forget it", "leave it", "exit", "quit", "chhodo", "rehne do",
})
# NOTE: "skip" removed — it's a valid answer in step-by-step forms (skip cash/UPI)

_GREETING_WORDS = frozenset({
    "hi", "hello", "hey", "menu", "help", "start",
})


def _is_correction_message(message: str) -> bool:
    """
    Detect if a message looks like a correction (not a simple yes/no).
    e.g. "no name is Raj", "wrong, room should be 305", "change amount to 15000"
    Simple "no" or "yes" returns False — let the normal handler deal with those.
    """
    msg = message.strip().lower()
    # Simple yes/no — not a correction, let normal flow handle
    if msg in ("no", "n", "yes", "y", "ok", "cancel", "stop", "abort", "confirm"):
        return False
    # "No" followed by more content → likely a correction
    if re.match(r"^no[\s,]+\w", msg, re.I):
        return True
    # Correction keywords
    if re.search(r"\b(wrong|incorrect|change|update|correct|actually|should be|not \w+\s+its?)\b", msg, re.I):
        return True
    return False


def _detect_mid_flow_breakout(message: str, pending_intent: str, skip_new_intent: bool = False) -> Optional[str]:
    """
    Check if a message during a pending flow is a breakout signal.

    Returns:
      "cancel"    — user wants to cancel the current flow
      "greeting"  — user said hi/hello/menu → clear flow, show menu
      "new_intent"— user started a clearly different action
      None        — not a breakout, continue with pending flow
    """
    msg = message.strip().lower().rstrip(".!?")

    # Cancel keywords
    if msg in _CANCEL_WORDS:
        return "cancel"

    # Greeting / menu reset
    if msg in _GREETING_WORDS:
        return "greeting"

    # Skip new_intent detection during free-text input steps (notes, description)
    # where user input may accidentally match intent patterns like "paid"
    if skip_new_intent:
        return None

    # Check if message matches a clear new intent (high confidence, different from pending)
    # Only check for multi-step flows (ADD_TENANT_STEP, RECORD_CHECKOUT) where user
    # might abandon mid-flow to do something else
    if pending_intent in ("ADD_TENANT_STEP", "RECORD_CHECKOUT", "CONFIRM_PAYMENT_LOG", "COLLECT_RENT_STEP", "LOG_EXPENSE_STEP", "CONFIRM_PAYMENT_ALLOC", "UPDATE_TENANT_NOTES_STEP", "ADD_CONTACT_STEP", "FORM_EXTRACT_CONFIRM", "COLLECT_DOCS", "CONFIRM_ADD_TENANT", "CHECKOUT_FORM_CONFIRM", "COLLECT_RECEIPT"):
        probe = detect_intent(message, "admin")
        if (
            probe.intent in _NEW_INTENT_TRIGGERS
            and probe.confidence >= 0.85
        ):
            return "new_intent"

    return None


# ── Follow-up detection ──────────────────────────────────────────────────────

# Patterns that suggest a pronoun-style follow-up referencing the last conversation
_FOLLOWUP_PATTERNS = _re.compile(
    r"^(?:how much|what about|tell me more|details|more details|his |her |their |"
    r"when did|how many|since when|what.?s his|what.?s her|"
    r"payment history|payments?|balance|dues|rent|"
    r"and (?:his|her|their)|also |"
    r"(?:uska|uski|unka|unki|kitna|kab se)\b)",
    _re.I,
)

# Extract room number or tenant name from a bot response
_ROOM_IN_RESPONSE = _re.compile(r"\b(?:Room|room)\s+([\w-]+)\b")
_NAME_IN_RESPONSE = _re.compile(r"(?:Occupant|Tenant|Name)s?:\s*\*?([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)")


def _detect_followup_context(message: str, chat_context: str) -> Optional[dict]:
    """
    If the message looks like a follow-up and the last bot message mentions
    a room/tenant, return dict with extracted room/name for re-routing.
    Returns None if not a follow-up.
    """
    if not chat_context:
        return None
    if not _FOLLOWUP_PATTERNS.search(message):
        return None

    # Find the last bot message in context
    last_bot_msg = ""
    for line in chat_context.split("\n"):
        if line.startswith("Bot: "):
            last_bot_msg = line[5:]

    if not last_bot_msg:
        return None

    result = {}

    # Try to extract room number from last bot response
    room_match = _ROOM_IN_RESPONSE.search(last_bot_msg)
    if room_match:
        result["room"] = room_match.group(1)

    # Try to extract tenant name from last bot response
    name_match = _NAME_IN_RESPONSE.search(last_bot_msg)
    if name_match:
        result["name"] = name_match.group(1)

    # Only return if we found something to reference
    if result:
        return result
    return None


async def _get_active_pending(phone: str, session: AsyncSession) -> Optional[PendingAction]:
    """Return the most recent unresolved pending action for this phone, if not expired.
    APPROVE_ONBOARDING is prioritized over other intents (created by tenant session)."""
    # Check for high-priority approval pendings first
    approval = await session.scalar(
        select(PendingAction).where(
            and_(
                PendingAction.phone == phone,
                PendingAction.resolved == False,
                PendingAction.expires_at > datetime.utcnow(),
                PendingAction.intent == "APPROVE_ONBOARDING",
            )
        ).order_by(PendingAction.created_at.desc())
    )
    if approval:
        return approval
    # Then normal most-recent lookup
    return await session.scalar(
        select(PendingAction).where(
            and_(
                PendingAction.phone == phone,
                PendingAction.resolved == False,
                PendingAction.expires_at > datetime.utcnow(),
            )
        ).order_by(PendingAction.created_at.desc())
    )


async def _log(
    session: AsyncSession,
    phone: str,
    message: str,
    role: str,
    intent: str,
    reply: Optional[str],
):
    role_map = {
        "admin":        CallerRole.owner,
        "owner":        CallerRole.owner,
        "receptionist": CallerRole.owner,
        "tenant":       CallerRole.tenant,
        "lead":         CallerRole.lead,
        "blocked":      CallerRole.blocked,
    }
    session.add(WhatsappLog(
        direction=MessageDirection.inbound,
        caller_role=role_map.get(role, CallerRole.unknown),
        from_number=phone,
        to_number=os.getenv("WHATSAPP_PHONE_NUMBER_ID", ""),
        message_text=message,
        intent=intent,
        created_at=datetime.utcnow(),
    ))
    if reply:
        session.add(WhatsappLog(
            direction=MessageDirection.outbound,
            caller_role=role_map.get(role, CallerRole.unknown),
            from_number=os.getenv("WHATSAPP_PHONE_NUMBER_ID", ""),
            to_number=phone,
            message_text=reply,
            intent=intent,
            created_at=datetime.utcnow(),
        ))

    # ── Also save to chat_messages for context loading ────────────────────
    try:
        await _save_chat_message(session, phone, "inbound", message, intent=intent, role=role)
        if reply:
            await _save_chat_message(session, phone, "outbound", reply, intent=intent, role=role)
    except Exception:
        _chat_logger.debug("Failed to save chat_message for %s (table may not exist yet)", phone)
