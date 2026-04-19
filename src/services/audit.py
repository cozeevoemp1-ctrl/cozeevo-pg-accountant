"""
src/services/audit.py
=====================
Thin wrapper around the audit_log table.

All financial and operational state changes should call write_audit_entry()
so the trail is consistent regardless of whether the caller is the WhatsApp
bot, the owner PWA, or a background job.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import AuditLog


async def write_audit_entry(
    *,
    session: AsyncSession,
    changed_by: str,
    entity_type: str,
    entity_id: int,
    field: str,
    old_value: Optional[str] = None,
    new_value: Optional[str] = None,
    entity_name: Optional[str] = None,
    room_number: Optional[str] = None,
    source: str = "service",
    note: Optional[str] = None,
) -> None:
    """Insert one row into audit_log.

    Args:
        session:     SQLAlchemy async session (caller owns the transaction).
        changed_by:  Phone number or identifier of the person/system making the change.
        entity_type: Type of record changed ("payment", "tenancy", "tenant", …).
        entity_id:   Primary key of the changed record.
        field:       Logical field name. Use dotted names for compound actions
                     (e.g. "payment.log", "rent.change").
        old_value:   String representation of the previous value (or None).
        new_value:   String representation of the new value.
        entity_name: Human-readable name (tenant name, room number string, etc.).
        room_number: Room number for easy querying by room.
        source:      Origin of change: "whatsapp" | "dashboard" | "pwa" | "system" | "import".
        note:        Optional free-text context.
    """
    entry = AuditLog(
        changed_by=changed_by or "system",
        entity_type=entity_type,
        entity_id=entity_id,
        entity_name=entity_name,
        field=field,
        old_value=old_value,
        new_value=new_value,
        room_number=room_number,
        source=source,
        note=note,
    )
    session.add(entry)
