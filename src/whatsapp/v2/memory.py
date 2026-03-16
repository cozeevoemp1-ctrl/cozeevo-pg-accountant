"""
src/whatsapp/v2/memory.py
─────────────────────────
Conversation history helpers for the v2 Supervisor Agent.

Provides a lightweight per-user message window (last 10 turns) that the
LangGraph supervisor includes in every Groq call for context-aware intent
classification.

Tables used:
    conversation_history  — simple rows, auto-pruned to MAX_ROWS_PER_PHONE
"""
from __future__ import annotations

from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import ConversationHistory

MAX_ROWS_PER_PHONE = 50   # hard cap per user; oldest pruned on each save_turn call
DEFAULT_HISTORY_LIMIT = 10


async def get_history(
    phone: str,
    session: AsyncSession,
    limit: int = DEFAULT_HISTORY_LIMIT,
) -> list[dict]:
    """Return last `limit` turns for phone, oldest-first.

    Each item: {sent_by, message, intent, role}
    Returns empty list if no history exists yet.
    """
    result = await session.execute(
        select(ConversationHistory)
        .where(ConversationHistory.phone == phone)
        .order_by(ConversationHistory.created_at.desc())
        .limit(limit)
    )
    rows = result.scalars().all()
    # Reverse so oldest is first (chronological order for the LLM prompt)
    return [
        {
            "sent_by":  r.sent_by,
            "message":  r.message,
            "intent":   r.intent or "",
            "role":     r.role or "",
        }
        for r in reversed(rows)
    ]


async def save_turn(
    phone: str,
    role: str,
    user_message: str,
    bot_response: str,
    intent: str,
    session: AsyncSession,
) -> None:
    """Insert user message + bot response rows, then prune to MAX_ROWS_PER_PHONE.

    Two rows are written per turn:
        sent_by="user"  — the inbound message
        sent_by="bot"   — the outbound reply
    """
    session.add(ConversationHistory(
        phone=phone, sent_by="user", message=user_message, intent=intent, role=role
    ))
    session.add(ConversationHistory(
        phone=phone, sent_by="bot", message=bot_response, intent=intent, role=role
    ))

    # Prune: keep only the MAX_ROWS_PER_PHONE newest rows per phone
    count_result = await session.execute(
        select(func.count()).where(ConversationHistory.phone == phone)
    )
    total = count_result.scalar() or 0

    if total > MAX_ROWS_PER_PHONE:
        # Find the cutoff created_at (the oldest row we want to keep)
        cutoff_result = await session.execute(
            select(ConversationHistory.created_at)
            .where(ConversationHistory.phone == phone)
            .order_by(ConversationHistory.created_at.desc())
            .limit(1)
            .offset(MAX_ROWS_PER_PHONE - 1)
        )
        cutoff = cutoff_result.scalar()
        if cutoff:
            await session.execute(
                delete(ConversationHistory).where(
                    ConversationHistory.phone == phone,
                    ConversationHistory.created_at < cutoff,
                )
            )
