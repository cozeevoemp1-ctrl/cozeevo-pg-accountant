"""
ConversationAgent — the brain of Kozzy AI Platform.

Single PydanticAI agent that handles ALL non-regex messages:
- Classifies intents with few-shot examples
- Converses naturally (greetings, thanks, small talk)
- Shows options when medium confidence (0.6-0.9)
- Asks clarification when low confidence (<0.6)
- Handles corrections mid-flow
- Extracts entities from natural language

System prompt is built dynamically from pg_config.
"""
from __future__ import annotations

import json
import os
import uuid
from typing import Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.llm_gateway.agents.models import ConversationResult
from src.llm_gateway.agents.prompt_builder import build_system_prompt
from src.llm_gateway.agents.tools import search_similar_examples
from src.database.models import PgConfig

# Cache pg_config per pg_id to avoid repeated DB lookups
_pg_config_cache: dict[str, dict] = {}


async def _get_pg_config(pg_id: str, session: AsyncSession) -> dict:
    """Load pg_config from DB, cached in memory."""
    if pg_id in _pg_config_cache:
        return _pg_config_cache[pg_id]

    result = await session.execute(
        select(PgConfig).where(PgConfig.id == pg_id)
    )
    pg = result.scalars().first()
    if not pg:
        logger.error(f"[ConversationAgent] pg_config not found for pg_id={pg_id}")
        return {}

    config = {
        "pg_name": pg.pg_name,
        "brand_name": pg.brand_name,
        "brand_voice": pg.brand_voice or "",
        "buildings": pg.buildings or [],
        "rooms": pg.rooms or [],
        "staff_rooms": pg.staff_rooms or [],
        "admin_phones": pg.admin_phones or [],
        "pricing": pg.pricing or {},
        "bank_config": pg.bank_config or {},
        "expense_categories": pg.expense_categories or [],
        "custom_intents": pg.custom_intents or [],
        "business_rules": pg.business_rules or {},
    }
    _pg_config_cache[pg_id] = config
    return config


def invalidate_pg_config_cache(pg_id: str | None = None):
    """Clear pg_config cache (call after pg_config update)."""
    if pg_id:
        _pg_config_cache.pop(pg_id, None)
    else:
        _pg_config_cache.clear()


async def run_conversation_agent(
    message: str,
    role: str,
    phone: str,
    pg_id: str,
    session: AsyncSession,
    chat_history: str = "",
    pending_context: str = "",
) -> ConversationResult:
    """
    Run ConversationAgent on a message. Returns structured ConversationResult.
    Called by chat_api.py when regex misses and USE_PYDANTIC_AGENTS is enabled.
    """
    try:
        pg_config = await _get_pg_config(pg_id, session)
        if not pg_config:
            return ConversationResult(
                action="converse",
                reply="I'm having trouble loading my configuration. Please try again.",
                reasoning="pg_config not found",
            )

        examples = await search_similar_examples(message, pg_id, role, session, limit=10)

        system_prompt = build_system_prompt(
            pg_config=pg_config,
            role=role,
            examples=examples,
            chat_history=chat_history,
            pending_context=pending_context,
        )

        result = await _call_llm(system_prompt, message)

        logger.info(
            f"[ConversationAgent] {phone} | action={result.action} "
            f"intent={result.intent} conf={result.confidence:.2f} "
            f"reasoning={result.reasoning[:80]}"
        )
        return result

    except Exception as e:
        logger.error(f"[ConversationAgent] Error: {e}")
        return ConversationResult(
            action="converse",
            reply="I didn't quite catch that. Could you rephrase? Type *help* for options.",
            reasoning=f"Agent error: {str(e)}",
        )


async def _call_llm(system_prompt: str, user_message: str) -> ConversationResult:
    """
    Call Groq via PydanticAI for structured output.
    Falls back to manual JSON parsing if PydanticAI structured output fails.
    """
    try:
        from pydantic_ai import Agent

        agent = Agent(
            model="groq:llama-3.3-70b-versatile",
            system_prompt=system_prompt,
            result_type=ConversationResult,
            retries=3,
        )

        result = await agent.run(user_message)
        return result.data

    except ImportError:
        logger.warning("[ConversationAgent] pydantic-ai not available, falling back to manual")
        return await _call_llm_manual(system_prompt, user_message)
    except Exception as e:
        logger.warning(f"[ConversationAgent] PydanticAI call failed: {e}, trying manual")
        return await _call_llm_manual(system_prompt, user_message)


async def _call_llm_manual(system_prompt: str, user_message: str) -> ConversationResult:
    """Fallback: call Groq directly via httpx and parse JSON manually."""
    import httpx

    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key:
        return ConversationResult(
            action="converse",
            reply="I'm not fully configured yet. Please contact the admin.",
            reasoning="GROQ_API_KEY not set",
        )

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "temperature": 0.0,
        "max_tokens": 512,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=headers,
            json=payload,
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"].strip()

    clean = raw.lstrip("```json").lstrip("```").rstrip("```").strip()
    data = json.loads(clean)
    return ConversationResult(**data)
