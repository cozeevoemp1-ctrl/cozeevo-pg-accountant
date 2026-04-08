"""Tools available to ConversationAgent via PydanticAI tool use."""
from __future__ import annotations

from difflib import SequenceMatcher
from typing import Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import IntentExample, Tenant, Tenancy, Room


async def search_similar_examples(
    message: str,
    pg_id: str,
    role: str,
    session: AsyncSession,
    limit: int = 10,
) -> list[dict]:
    """
    Find the most similar past examples for this PG.
    Uses substring matching + difflib similarity (no embeddings yet).
    Returns top-K examples sorted by relevance.
    """
    result = await session.execute(
        select(IntentExample).where(
            and_(
                IntentExample.pg_id == pg_id,
                IntentExample.is_active == True,
            )
        ).limit(200)
    )
    examples = result.scalars().all()

    if not examples:
        return []

    msg_lower = message.lower().strip()
    scored = []
    for ex in examples:
        ex_lower = ex.message_text.lower().strip()
        ratio = SequenceMatcher(None, msg_lower, ex_lower).ratio()
        msg_words = set(msg_lower.split())
        ex_words = set(ex_lower.split())
        overlap = len(msg_words & ex_words) / max(len(msg_words), 1)
        score = ratio * 0.6 + overlap * 0.4
        scored.append((score, ex))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        {
            "message": ex.message_text,
            "intent": ex.intent,
            "confidence": float(ex.confidence) if ex.confidence else 0.0,
            "source": ex.source,
        }
        for score, ex in scored[:limit]
        if score > 0.15
    ]


async def get_tenant_context(
    name_or_room: str,
    session: AsyncSession,
) -> Optional[dict]:
    """
    Look up tenant/room info for entity resolution.
    Returns basic tenant+room info if found, None otherwise.
    """
    name_or_room = name_or_room.strip()

    # Try room number first
    if name_or_room.isdigit() or name_or_room.upper().startswith("G"):
        result = await session.execute(
            select(Tenancy, Tenant, Room).join(
                Tenant, Tenancy.tenant_id == Tenant.id
            ).join(
                Room, Tenancy.room_id == Room.id
            ).where(
                and_(
                    Room.room_number == name_or_room,
                    Tenancy.status == "active",
                )
            )
        )
        row = result.first()
        if row:
            tenancy, tenant, room = row
            return {
                "tenant_name": tenant.name,
                "room": room.room_number,
                "rent": float(tenancy.agreed_rent) if tenancy.agreed_rent else None,
                "status": tenancy.status,
            }

    # Try name search (prefix match)
    result = await session.execute(
        select(Tenancy, Tenant, Room).join(
            Tenant, Tenancy.tenant_id == Tenant.id
        ).join(
            Room, Tenancy.room_id == Room.id
        ).where(
            and_(
                Tenant.name.ilike(f"{name_or_room}%"),
                Tenancy.status == "active",
            )
        ).limit(5)
    )
    rows = result.all()
    if rows:
        first = rows[0]
        tenancy, tenant, room = first
        return {
            "tenant_name": tenant.name,
            "room": room.room_number,
            "rent": float(tenancy.agreed_rent) if tenancy.agreed_rent else None,
            "status": tenancy.status,
            "multiple_matches": len(rows) > 1,
        }

    return None
