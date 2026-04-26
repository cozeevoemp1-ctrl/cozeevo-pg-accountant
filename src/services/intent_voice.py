"""Voice intent extraction using PydanticAI + Groq Llama 3.3 70B."""
from __future__ import annotations

import os
from pydantic import BaseModel


class PaymentIntent(BaseModel):
    intent: str  # "log_payment" | "check_balance" | "unknown"
    amount: int | None = None
    tenant_name: str | None = None
    tenant_room: str | None = None
    method: str | None = None  # UPI / CASH / BANK / CARD / OTHER
    for_type: str = "rent"


_SYSTEM = """You extract structured payment data from a PG owner's voice note.

Rules:
- intent: "log_payment" if a payment is being recorded, "check_balance" if balance is queried, else "unknown"
- amount: integer in rupees. "8k" = 8000, "8.5k" = 8500, "8500" = 8500
- tenant_name: first name or full name as spoken
- tenant_room: room code like "H201", "T104", "304" etc.
- method: one of UPI / CASH / BANK / CARD / OTHER (UPI = gpay/phonepe/paytm/online/neft/imps)
- for_type: "rent" (default), "deposit", "maintenance", "booking", "adjustment"
Return ONLY valid JSON matching the schema. No explanation."""


def extract_intent(*, transcript: str) -> PaymentIntent:
    """Extract payment intent from voice transcript using Groq Llama 3.3 70B."""
    # Use PydanticAI if available, fallback to raw Groq JSON mode
    try:
        from pydantic_ai import Agent  # type: ignore
        agent: Agent[None, PaymentIntent] = Agent(
            "groq:llama-3.3-70b-versatile",
            result_type=PaymentIntent,
            system_prompt=_SYSTEM,
        )
        result = agent.run_sync(transcript)
        return result.data
    except ImportError:
        return _extract_via_groq(transcript)


def _extract_via_groq(transcript: str) -> PaymentIntent:
    """Fallback: raw Groq call with JSON mode."""
    from groq import Groq
    import json

    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    resp = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": transcript},
        ],
        temperature=0,
    )
    raw = resp.choices[0].message.content or "{}"
    data = json.loads(raw)
    return PaymentIntent(**{k: v for k, v in data.items() if k in PaymentIntent.model_fields})
