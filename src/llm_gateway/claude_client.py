"""
Multi-provider LLM client for PG Accountant.

Supports three backends — switch by setting LLM_PROVIDER in .env:
  LLM_PROVIDER=ollama     → free, runs on your PC (default)
  LLM_PROVIDER=groq       → free cloud API (groq.com)
  LLM_PROVIDER=anthropic  → paid Claude API (anthropic.com)

Used ONLY for ~3% of transactions:
  1. Merchant classification when rules confidence < threshold
  2. WhatsApp intent detection fallback
  3. Clarification questions
  4. New entity suggestions

All other operations are deterministic Python — no LLM calls.
"""
from __future__ import annotations

import json
import os
from typing import Optional

import httpx
from loguru import logger

from src.llm_gateway.prompts import (
    MERCHANT_CLASSIFY_PROMPT,
    INTENT_DETECT_PROMPT,
    WHATSAPP_INTENT_PROMPT,
    CLARIFICATION_PROMPT,
    NEW_ENTITY_PROMPT,
)


# ── Provider implementations ───────────────────────────────────────────────

class _OllamaBackend:
    """
    Calls a locally running Ollama instance (http://localhost:11434).
    Free forever. Install from https://ollama.com then run:
        ollama pull llama3.2
    """
    def __init__(self):
        self.url   = os.getenv("OLLAMA_URL", "http://localhost:11434") + "/api/generate"
        self.model = os.getenv("OLLAMA_MODEL", "llama3.2")

    async def call(self, prompt: str) -> str:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.0, "num_predict": 512},
        }
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(self.url, json=payload)
            resp.raise_for_status()
            return resp.json()["response"].strip()


class _GroqBackend:
    """
    Calls the Groq cloud API (free tier — fast Llama inference).
    Get a free key at https://console.groq.com
    """
    def __init__(self):
        self.api_key = os.getenv("GROQ_API_KEY", "")
        if not self.api_key:
            raise RuntimeError("GROQ_API_KEY not set. Get a free key at https://console.groq.com")
        self.url   = "https://api.groq.com/openai/v1/chat/completions"
        self.model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

    async def call(self, prompt: str) -> str:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0,
            "max_tokens": 512,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(self.url, headers=headers, json=payload)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()


class _AnthropicBackend:
    """
    Calls the Anthropic Claude API (paid).
    Get a key at https://console.anthropic.com
    """
    def __init__(self):
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key or api_key.startswith("PASTE_"):
            raise RuntimeError("ANTHROPIC_API_KEY not set in .env")
        import anthropic as _anthropic
        self.client     = _anthropic.AsyncAnthropic(api_key=api_key)
        self.model      = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
        self.max_tokens = int(os.getenv("ANTHROPIC_MAX_TOKENS", "512"))

    async def call(self, prompt: str) -> str:
        msg = await self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=0.0,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text


def _make_backend():
    provider = os.getenv("LLM_PROVIDER", "ollama").lower().strip()
    if provider == "groq":
        logger.info("[LLM] Using Groq (free cloud Llama)")
        return _GroqBackend()
    elif provider == "anthropic":
        logger.info("[LLM] Using Anthropic Claude")
        return _AnthropicBackend()
    else:
        logger.info("[LLM] Using Ollama (local Llama)")
        return _OllamaBackend()


# ── Public client (same interface regardless of provider) ──────────────────

class ClaudeClient:
    """
    Drop-in LLM client. Same methods regardless of which backend is active.
    Switch provider by changing LLM_PROVIDER in .env — no code changes needed.
    """

    def __init__(self):
        self._backend = _make_backend()
        self._usage_log: list[dict] = []

    # ── Merchant classification ───────────────────────────────────────────

    async def classify_merchant(
        self,
        description: str,
        merchant: str,
        date: str,
        amount: float,
        txn_type: str,
        categories: list[str],
    ) -> dict:
        """Returns {"category": str, "confidence": float, "reason": str}."""
        prompt = MERCHANT_CLASSIFY_PROMPT.format(
            categories="\n".join(f"  - {c}" for c in categories),
            date=date, amount=amount, txn_type=txn_type,
            description=description, merchant=merchant,
        )
        try:
            response = await self._call(prompt)
            result = json.loads(response)
            result["method"] = "ai"
            self._log("classify_merchant", prompt)
            return result
        except Exception as e:
            logger.warning(f"[LLM] classify_merchant failed: {e}")
            return {"category": "Miscellaneous", "confidence": 0.50, "reason": "AI fallback failed", "method": "ai_fallback"}

    # ── Intent detection ──────────────────────────────────────────────────

    async def detect_intent(self, message: str) -> dict:
        """Parses a WhatsApp message into structured intent."""
        prompt = INTENT_DETECT_PROMPT.format(message=message)
        try:
            response = await self._call(prompt)
            result = json.loads(response)
            self._log("detect_intent", prompt)
            return result
        except Exception as e:
            logger.warning(f"[LLM] detect_intent failed: {e}")
            return {"intent": "unknown", "period": None, "format": "text", "category": None, "entities": [], "confidence": 0.0}

    # ── WhatsApp intent (NLP fallback) ────────────────────────────────────

    _OWNER_INTENTS = (
        "PAYMENT_LOG         : tenant paid rent (e.g. 'Raj paid 15000', 'received 8k from 203', 'collect rent')\n"
        "QUERY_DUES          : who hasn't paid, pending list, outstanding balances, defaulters\n"
        "QUERY_TENANT        : balance/dues/details of a specific tenant (e.g. 'Raj balance', 'what is rent for chinmay')\n"
        "ADD_TENANT          : add new tenant, check-in, new admission (NOT add contact)\n"
        "START_ONBOARDING    : start KYC/onboarding/registration for a tenant\n"
        "CHECKOUT            : tenant leaving/vacating (immediate)\n"
        "RECORD_CHECKOUT     : checkout form, offboarding record, handover, keys returned\n"
        "SCHEDULE_CHECKOUT   : tenant leaving on a future date\n"
        "NOTICE_GIVEN        : tenant gave notice, plans to leave\n"
        "UPDATE_CHECKIN      : correct/backdate a check-in date\n"
        "UPDATE_CHECKOUT_DATE: change/correct a checkout date\n"
        "ROOM_TRANSFER       : move/transfer tenant to a different room\n"
        "RENT_CHANGE         : permanent rent increase or decrease\n"
        "RENT_DISCOUNT       : one-time concession, discount, surcharge, waiver\n"
        "DEPOSIT_CHANGE      : change/update security deposit amount\n"
        "ADD_EXPENSE         : log a property expense (electricity, salary, plumber, maintenance bill)\n"
        "QUERY_EXPENSES      : check/query expenses (e.g. 'expenses this month', 'what did we spend')\n"
        "VOID_PAYMENT        : cancel, reverse, void a payment\n"
        "VOID_EXPENSE        : cancel, reverse, void an expense\n"
        "ADD_REFUND          : record a deposit refund with amount\n"
        "QUERY_REFUNDS       : pending refunds, refund status\n"
        "REPORT              : monthly summary, P&L, collection report, financial, how much collected\n"
        "BANK_REPORT         : bank statement report/analysis\n"
        "BANK_DEPOSIT_MATCH  : match bank deposits to tenants\n"
        "QUERY_VACANT_ROOMS  : vacant/empty rooms, available beds, female/male rooms\n"
        "QUERY_OCCUPANCY     : occupancy, how full, how many tenants\n"
        "ROOM_LAYOUT         : floor plan, room diagram, building layout\n"
        "ROOM_STATUS         : who is in room X, room details\n"
        "COMPLAINT_REGISTER  : report a problem (no water, broken fan, plumbing, wifi down)\n"
        "COMPLAINT_UPDATE    : resolve/close a complaint\n"
        "QUERY_COMPLAINTS    : check complaint status, pending complaints\n"
        "SEND_REMINDER_ALL   : send reminders to all unpaid tenants\n"
        "REMINDER_SET        : set a reminder for a specific tenant or event\n"
        "LOG_VACATION        : tenant going on leave/vacation/home\n"
        "ACTIVITY_LOG        : log an activity (received items, deliveries, maintenance done)\n"
        "QUERY_ACTIVITY      : show activity log (today, this week)\n"
        "ADD_CONTACT         : add/save a vendor/service contact with phone number (plumber, electrician, lineman, etc.)\n"
        "QUERY_CONTACTS      : look up vendor/service contact (plumber number, electrician contact)\n"
        "UPDATE_TENANT_NOTES : update/edit tenant notes or agreement\n"
        "GET_TENANT_NOTES    : view tenant notes, agreed terms\n"
        "GET_WIFI_PASSWORD   : wifi password\n"
        "SET_WIFI            : set/change wifi password\n"
        "ADD_PARTNER         : add admin, owner, staff, give access\n"
        "QUERY_EXPIRING      : who is leaving this month, upcoming checkouts\n"
        "QUERY_CHECKINS      : who checked in, new arrivals\n"
        "QUERY_CHECKOUTS     : who checked out, recent exits\n"
        "RULES               : PG rules and regulations\n"
        "HELP                : help, menu, commands, hi, hello\n"
        "UNKNOWN             : cannot determine intent"
    )

    _TENANT_INTENTS = (
        "MY_BALANCE  : how much do I owe, my dues, my pending\n"
        "MY_PAYMENTS : my payment history, receipts, what I paid\n"
        "MY_DETAILS  : my room details, rent, check-in date\n"
        "HELP        : help, hi, hello\n"
        "UNKNOWN     : cannot determine"
    )

    _LEAD_INTENTS = (
        "ROOM_PRICE    : price, rent, cost, how much, rates\n"
        "AVAILABILITY  : available rooms, vacancy\n"
        "ROOM_TYPE     : single, double, sharing, private, AC\n"
        "VISIT_REQUEST : visit, tour, come see, show room\n"
        "GENERAL       : everything else (general enquiry or conversation)"
    )

    async def _call_haiku(self, prompt: str) -> str:
        """Direct call to Claude Haiku for intent detection (bypasses main LLM provider)."""
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key or api_key.startswith("PASTE_"):
            # Fallback to main backend if Haiku not configured
            return await self._call(prompt)
        try:
            import anthropic
            client = anthropic.AsyncAnthropic(api_key=api_key)
            msg = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=512,
                temperature=0.0,
                messages=[{"role": "user", "content": prompt}],
            )
            logger.debug("[LLM] Intent detection via Claude Haiku")
            return msg.content[0].text
        except Exception as e:
            logger.warning(f"[LLM] Haiku call failed, falling back to {type(self._backend).__name__}: {e}")
            return await self._call(prompt)

    async def detect_whatsapp_intent(self, message: str, role: str) -> dict:
        """
        NLP fallback for WhatsApp messages that don't match any regex rule.
        Uses Claude Haiku (cheap, fast, accurate) instead of main LLM provider.
        Returns {"intent": str, "confidence": float, "entities": dict}.
        """
        if role in ("admin", "owner"):
            intents_text = self._OWNER_INTENTS
        elif role == "tenant":
            intents_text = self._TENANT_INTENTS
        else:
            intents_text = self._LEAD_INTENTS

        prompt = WHATSAPP_INTENT_PROMPT.format(
            role=role,
            intents=intents_text,
            message=message,
        )
        try:
            response = await self._call_haiku(prompt)
            # Strip markdown fences if model wraps in ```json ... ```
            clean = response.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
            result = json.loads(clean)
            result.setdefault("entities", {})
            result.setdefault("confidence", 0.7)
            self._log("detect_whatsapp_intent", prompt)
            return result
        except Exception as e:
            logger.warning(f"[LLM] detect_whatsapp_intent failed: {e}")
            return {"intent": "UNKNOWN", "confidence": 0.0, "entities": {}}

    # ── Clarification ─────────────────────────────────────────────────────

    async def ask_clarification(self, context: str, message: str, unclear: str) -> str:
        prompt = CLARIFICATION_PROMPT.format(context=context, message=message, unclear=unclear)
        try:
            response = await self._call(prompt)
            self._log("clarification", prompt)
            return response.strip()
        except Exception as e:
            logger.warning(f"[LLM] ask_clarification failed: {e}")
            return "Could you please clarify your request?"

    # ── Entity suggestion ─────────────────────────────────────────────────

    async def suggest_entity(
        self, entity_type: str, date: str, amount: float,
        description: str, party: str, upi_id: str = ""
    ) -> dict:
        prompt = NEW_ENTITY_PROMPT.format(
            entity_type=entity_type, date=date, amount=amount,
            description=description, party=party, upi_id=upi_id,
        )
        try:
            response = await self._call(prompt)
            result = json.loads(response)
            self._log("suggest_entity", prompt)
            return result
        except Exception as e:
            logger.warning(f"[LLM] suggest_entity failed: {e}")
            return {"name": party or description[:50], "phone": None, "upi_id": upi_id or None, "notes": ""}

    # ── Smart log/expense query ─────────────────────────────────────────

    async def answer_from_logs(self, question: str, logs: list[str], log_type: str = "activity") -> str:
        """
        Given a user question and a list of log entries, use LLM to answer.
        log_type: "activity" or "expense"
        """
        if not logs:
            return ""

        logs_text = "\n".join(logs[:100])  # cap at 100 entries
        prompt = (
            f"You are a helpful PG (paying guest hostel) operations assistant.\n"
            f"Below are {log_type} log entries from the hostel. "
            f"Answer the user's question based ONLY on these logs.\n"
            f"Be concise. Use bullet points. Include dates and room numbers when relevant.\n"
            f"If the logs don't contain enough info to answer, say so.\n\n"
            f"--- {log_type.upper()} LOGS ---\n{logs_text}\n--- END LOGS ---\n\n"
            f"Question: {question}\n\n"
            f"Answer:"
        )
        try:
            response = await self._call(prompt)
            self._log(f"answer_{log_type}", prompt)
            return response
        except Exception as e:
            logger.warning(f"[LLM] answer_from_logs failed: {e}")
            return ""

    # ── Internal ──────────────────────────────────────────────────────────

    async def _call(self, prompt: str) -> str:
        return await self._backend.call(prompt)

    def _log(self, operation: str, prompt: str):
        self._usage_log.append({"operation": operation, "approx_chars": len(prompt)})
        logger.debug(f"[LLM] {operation} via {type(self._backend).__name__} | ~{len(prompt)} chars")

    def get_usage_summary(self) -> dict:
        by_op = {}
        for e in self._usage_log:
            by_op[e["operation"]] = by_op.get(e["operation"], 0) + 1
        return {"total_ai_calls": len(self._usage_log), "by_operation": by_op, "provider": type(self._backend).__name__}


# ── Singleton ──────────────────────────────────────────────────────────────

_client: Optional[ClaudeClient] = None


def get_claude_client() -> ClaudeClient:
    global _client
    if _client is None:
        _client = ClaudeClient()
    return _client
