"""
src/whatsapp/conversation/memory.py
====================================
ConversationMemory — the single struct every handler gets.

Replaces the ad-hoc pattern where each handler looks up its own
context (pending, recent turns, caller role, tenant profile) by
repeating DB queries. One load, one pass, one consistent view.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import PendingAction, WhatsappLog, MessageDirection


@dataclass
class ChatTurn:
    """One turn in the conversation — either an inbound user msg or
    outbound bot reply."""
    direction: str        # "inbound" | "outbound"
    message: str
    intent: Optional[str]
    timestamp: datetime


@dataclass
class ConversationMemory:
    """Everything a handler needs about the current conversation.

    Load once at the top of request processing. Mutate only through
    explicit service calls (save_pending, clear_pending, etc.) — never
    rewrite this struct in place.
    """
    phone: str                            # normalized 10-digit form
    role: str                             # "admin" | "owner" | "tenant" | ...
    name: str                             # caller's display name
    tenant_id: Optional[int] = None       # if role == tenant
    auth_user_id: Optional[int] = None    # if authorized user
    pending: Optional[PendingAction] = None
    recent_turns: list[ChatTurn] = field(default_factory=list)
    user_context: dict[str, Any] = field(default_factory=dict)

    def has_pending(self) -> bool:
        return self.pending is not None and not self.pending.resolved

    def pending_intent(self) -> Optional[str]:
        return self.pending.intent if self.has_pending() else None

    def pending_state(self) -> Optional[str]:
        """The ConversationState value stored on pending.state, if any.

        Returns None for legacy pendings that predate the state field.
        Callers can use this to decide whether to route through the new
        framework (state set) or the legacy cascade (state None).
        """
        if not self.has_pending():
            return None
        return getattr(self.pending, "state", None)


async def load(
    phone: str,
    role: str,
    name: str,
    session: AsyncSession,
    *,
    tenant_id: Optional[int] = None,
    auth_user_id: Optional[int] = None,
    recent_turns_limit: int = 10,
) -> ConversationMemory:
    """Build a ConversationMemory for this caller.

    Must be called AFTER phone normalization. `phone` here is the
    canonical 10-digit form returned by role_service._normalize.
    """
    mem = ConversationMemory(
        phone=phone, role=role, name=name or "",
        tenant_id=tenant_id, auth_user_id=auth_user_id,
    )

    # Pending (if any, unresolved, unexpired)
    mem.pending = await session.scalar(
        select(PendingAction)
        .where(
            PendingAction.phone == phone,
            PendingAction.resolved == False,
            PendingAction.expires_at > datetime.utcnow(),
        )
        .order_by(PendingAction.created_at.desc())
    )

    # Recent turns (most recent first). WhatsappLog stores from/to
    # numbers, not a unified "phone" — inbound rows use from_number,
    # outbound use to_number.
    from sqlalchemy import or_
    log_rows = (await session.execute(
        select(WhatsappLog)
        .where(or_(WhatsappLog.from_number == phone,
                   WhatsappLog.to_number == phone))
        .order_by(WhatsappLog.created_at.desc())
        .limit(recent_turns_limit)
    )).scalars().all()

    turns = []
    for row in log_rows:
        direction = "outbound" if row.direction == MessageDirection.outbound else "inbound"
        turns.append(ChatTurn(
            direction=direction,
            message=(row.message_text or "")[:500],
            intent=row.intent,
            timestamp=row.created_at,
        ))
    # Reverse so oldest-first (handlers read chronologically)
    mem.recent_turns = list(reversed(turns))
    return mem
