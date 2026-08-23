"""
Dedicated Groq caller for the Havenly Stays demo — separate from
src/llm_gateway/claude_client.py (production's shared LLM gateway) so this
demo can tune its own parameters without touching code production depends on.

Why this exists: the shared gateway's Groq backend is a reasoning model
(openai/gpt-oss-120b) with a hardcoded max_tokens=512 and no reasoning_effort
control. Our JSON-extraction prompts occasionally got the ENTIRE token
budget consumed by the model's hidden chain-of-thought, returning empty
content that broke json.loads downstream. Setting reasoning_effort="low"
and a higher max_tokens leaves reliable room for the actual answer.
"""
from __future__ import annotations

import os

import httpx
from loguru import logger

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


async def call_groq_json(prompt: str, max_tokens: int = 600) -> str:
    """Calls Groq with low reasoning effort so the token budget goes to the
    actual answer, not hidden chain-of-thought. Returns raw text — caller
    still does its own json.loads/cleanup."""
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY not set")
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": GROQ_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "max_tokens": max_tokens,
        "reasoning_effort": "low",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(GROQ_URL, headers=headers, json=payload)
    if resp.status_code != 200:
        raise RuntimeError(f"Groq call failed {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
    if not content:
        logger.warning(f"[Demo] Groq returned empty content. finish_reason={data.get('choices', [{}])[0].get('finish_reason')}")
    return content
