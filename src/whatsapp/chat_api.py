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

import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.db_manager import get_db_session as get_session
from src.database.models import PendingAction, PendingLearning, WhatsappLog, MessageDirection, CallerRole
from src.whatsapp.role_service import get_caller_context
from src.whatsapp.intent_detector import detect_intent, IntentResult, _extract_entities, _INTENT_LABELS
from src.whatsapp.gatekeeper import route
from src.whatsapp.handlers.owner_handler import resolve_pending_action, handle_learn_command
from src.whatsapp.handlers.tenant_handler import get_active_onboarding, handle_onboarding_step, resolve_tenant_complaint
from src.llm_gateway.claude_client import get_claude_client

router = APIRouter(prefix="/api/whatsapp", tags=["whatsapp"])


class InboundMessage(BaseModel):
    phone:      str
    message:    str
    message_id: Optional[str] = None


class OutboundReply(BaseModel):
    reply:      str
    intent:     str
    role:       str
    confidence: float = 0.0
    skip:       bool = False    # True = don't send reply (spam / non-text)

# Intents that are safe to pass through even at low confidence
_LOW_CONF_PASSTHROUGH = frozenset({"HELP", "GENERAL", "UNKNOWN", "SYSTEM_HARD_UNKNOWN", "BLOCKED", "ONBOARDING", "CONFIRMATION", "COMPLAINT_REGISTER", "AMBIGUOUS"})


@router.post("/process", response_model=OutboundReply)
async def process_message(
    body: InboundMessage,
    session: AsyncSession = Depends(get_session),
):
    phone   = body.phone.strip()
    message = body.message.strip()

    # ── 0. Admin !learn command — intercept before any other processing ──
    if message.startswith("!learn"):
        ctx_quick = await get_caller_context(phone, session)
        if ctx_quick.role in ("admin", "power_user"):
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

    # ── 2a. Check active onboarding session (tenant role) ────────────────
    if ctx.role == "tenant" and ctx.tenant_id:
        ob = await get_active_onboarding(ctx.tenant_id, session)
        if ob:
            import json as _json
            data = _json.loads(ob.collected_data or "{}")
            name = data.get("name", ctx.name)
            # First contact: send welcome + Q1 without consuming their message as an answer
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

    # ── 2b. Check pending disambiguation (owner) or complaint follow-up (tenant) ──
    if ctx.role in ("admin", "power_user", "key_user"):
        pending = await _get_active_pending(phone, session)
        if pending:
            # ── Intent-ambiguity resolution (e.g. "Raj 31st March" → checkin or checkout?) ──
            if pending.intent == "INTENT_AMBIGUOUS":
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

            resolved_reply = await resolve_pending_action(pending, message, session)
            if resolved_reply:
                pending.resolved = True
                await _log(session, phone, message, ctx.role, "CONFIRMATION", resolved_reply)
                await session.commit()
                return OutboundReply(reply=resolved_reply, intent="CONFIRMATION", role=ctx.role)
            pending.resolved = True

    if ctx.role == "tenant":
        pending = await _get_active_pending(phone, session)
        if pending and pending.intent == "COMPLAINT_REGISTER":
            resolved_reply = await resolve_tenant_complaint(pending, message, session)
            pending.resolved = True
            await _log(session, phone, message, ctx.role, "COMPLAINT_REGISTER", resolved_reply)
            await session.commit()
            return OutboundReply(reply=resolved_reply, intent="COMPLAINT_REGISTER", role=ctx.role)

    # ── 3. Detect intent (rules-first, AI fallback for UNKNOWN) ──────────
    intent_result = detect_intent(message, ctx.role)
    intent = intent_result.intent

    if intent == "UNKNOWN":
        try:
            ai = get_claude_client()
            ai_result = await ai.detect_whatsapp_intent(message, ctx.role)
            ai_intent = str(ai_result.get("intent", "UNKNOWN")).upper()
            ai_conf   = float(ai_result.get("confidence", 0.5))
            ai_entities = dict(ai_result.get("entities") or {})
            # Merge: AI entities + original rule entities (rules take precedence for non-None values)
            merged_entities = {k: v for k, v in ai_entities.items() if v is not None}
            merged_entities.update({k: v for k, v in intent_result.entities.items() if v is not None})
            intent_result = IntentResult(
                intent=ai_intent,
                confidence=ai_conf,
                entities=merged_entities,
            )
            intent = intent_result.intent
        except Exception:
            pass  # stay with UNKNOWN if AI also fails

    # ── Self-learning: log unrecognised messages for admin review ─────────
    if intent == "UNKNOWN":
        session.add(PendingLearning(
            phone=ctx.phone,
            role=ctx.role,
            message=message[:1000],
            detected_intent="UNKNOWN",
        ))
        admin_phone = os.getenv("ADMIN_PHONE", "")
        if admin_phone and ctx.phone != admin_phone:
            # Queue an outbound notification to admin (n8n will deliver it)
            session.add(WhatsappLog(
                direction=MessageDirection.outbound,
                caller_role=CallerRole.owner,
                from_number="system",
                to_number=admin_phone,
                message_text=(
                    f"⚠️ *Unknown message* from {ctx.role} ({ctx.phone}):\n"
                    f"\"{message[:200]}\"\n\n"
                    f"Teach me: `!learn INTENT keyword1, keyword2`"
                ),
                intent="SYSTEM_ADMIN_NOTIFY",
                created_at=datetime.utcnow(),
            ))

    # ── 3b. Low-confidence gate → SYSTEM_HARD_UNKNOWN ───────────────────
    # If intent router is not confident enough, ask the user to rephrase
    # rather than taking a potentially wrong action.
    if (
        intent_result.confidence < 0.70
        and intent not in _LOW_CONF_PASSTHROUGH
        and ctx.role != "lead"   # leads always get conversational handling
    ):
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
    if intent == "AMBIGUOUS" and ctx.role in ("admin", "power_user", "key_user"):
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

    reply = await route(intent, intent_result.entities, ctx, message, session)

    # ── 5. Log ────────────────────────────────────────────────────────────
    await _log(session, phone, message, ctx.role, intent, reply)
    await session.commit()

    return OutboundReply(reply=reply, intent=intent, role=ctx.role, confidence=intent_result.confidence)


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


async def _get_active_pending(phone: str, session: AsyncSession) -> Optional[PendingAction]:
    """Return the most recent unresolved pending action for this phone, if not expired."""
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
        "admin":      CallerRole.owner,
        "power_user": CallerRole.owner,
        "key_user":   CallerRole.tenant,
        "tenant":     CallerRole.tenant,
        "lead":       CallerRole.lead,
        "blocked":    CallerRole.blocked,
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
