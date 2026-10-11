"""
Blacklist service — shared helper for checking, adding, and removing
persons banned from being onboarded at Cozeevo.

Checked at:
  - POST /api/onboarding/create  (phone + name if provided)
  - POST /api/onboarding/{token}/approve  (tenant KYC phone + name)
  - WhatsApp bot: blacklist_add / show_blacklist commands
"""
import re
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def check_blacklisted(
    session: AsyncSession,
    *,
    name: str | None = None,
    phone: str | None = None,
) -> dict | None:
    """Return the blacklist row if name or phone matches an active entry, else None."""
    clauses: list[str] = []
    params: dict = {}

    if phone:
        digits = re.sub(r"\D", "", str(phone))[-10:]
        if digits:
            clauses.append("regexp_replace(phone, '[^0-9]', '', 'g') LIKE :phone_pat")
            params["phone_pat"] = f"%{digits}"

    if name and len(name.strip()) >= 3:
        clauses.append("LOWER(name) LIKE :name_pat")
        params["name_pat"] = f"%{name.strip().lower()}%"

    if not clauses:
        return None

    sql = text(
        f"SELECT id, name, phone, reason FROM blacklist "
        f"WHERE is_active = TRUE AND ({' OR '.join(clauses)})"
    )
    row = (await session.execute(sql, params)).first()
    return dict(row._mapping) if row else None


async def add_to_blacklist(
    session: AsyncSession,
    *,
    name: str | None = None,
    phone: str | None = None,
    reason: str,
    added_by: str | None = None,
) -> int:
    """Insert a blacklist entry. Caller is responsible for session commit."""
    sql = text(
        "INSERT INTO blacklist (name, phone, reason, added_by) "
        "VALUES (:name, :phone, :reason, :added_by) RETURNING id"
    )
    result = await session.execute(
        sql, {"name": name or None, "phone": phone or None, "reason": reason, "added_by": added_by}
    )
    new_id = result.scalar_one()
    _audit(session, new_id, name or phone, "added", added_by, reason)
    return new_id


def _audit(session: AsyncSession, bl_id: int, who: str | None, action: str,
           actor: str | None, note: str | None = None) -> None:
    """Every blacklist write lands in audit_log (rules_audit_logs)."""
    from src.database.models import AuditLog
    session.add(AuditLog(
        changed_by=actor or "system", entity_type="blacklist", entity_id=bl_id,
        entity_name=who, field="blacklist", old_value=None, new_value=action,
        source="whatsapp" if (actor or "").lstrip("+").isdigit() else "pwa", note=note,
    ))


async def list_blacklist(session: AsyncSession) -> list[dict]:
    """Return all active blacklist entries, newest first."""
    sql = text(
        "SELECT id, name, phone, reason, added_by, "
        "to_char(created_at, 'DD Mon YYYY') AS added_on "
        "FROM blacklist WHERE is_active = TRUE ORDER BY created_at DESC"
    )
    rows = (await session.execute(sql)).all()
    return [dict(r._mapping) for r in rows]


async def remove_from_blacklist(session: AsyncSession, blacklist_id: int,
                                removed_by: str | None = None) -> bool:
    """Soft-delete a blacklist entry. Returns True if found and removed."""
    sql = text(
        "UPDATE blacklist SET is_active = FALSE "
        "WHERE id = :id AND is_active = TRUE RETURNING id, name, phone"
    )
    row = (await session.execute(sql, {"id": blacklist_id})).first()
    if row is None:
        return False
    _audit(session, blacklist_id, row.name or row.phone, "removed", removed_by)
    return True
