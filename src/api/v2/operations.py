"""
Operational event log API.

GET  /api/v2/app/operations          — list logs (optional ?category=, ?limit=)
POST /api/v2/app/operations          — create a new log entry
DELETE /api/v2/app/operations/{id}   — delete a log entry (admin only)

Categories and required detail fields:
  power_outage       : outage_start (ISO datetime), outage_end (ISO datetime, optional)
  hp_gas             : booking_date (YYYY-MM-DD), received_date (YYYY-MM-DD), cylinder_count (int)
  water_tanker       : received_at (ISO datetime)
  garbage_collection : informed_date (YYYY-MM-DD), collected_date (YYYY-MM-DD, optional),
                       completed_date (YYYY-MM-DD, optional)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v2.auth import AppUser, get_current_user
from src.database.db_manager import get_session
from src.database.models import OperationalLog, OperationalLogCategory

router = APIRouter(prefix="/operations", tags=["operations"])

VALID_CATEGORIES = {c.value for c in OperationalLogCategory}
_STAFF_ROLES = {"admin", "power_user", "key_user"}


@router.get("")
async def list_operations(
    category: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    user: AppUser = Depends(get_current_user),
):
    if user.role not in _STAFF_ROLES:
        raise HTTPException(403, "Staff only")
    async with get_session() as session:
        q = select(OperationalLog).order_by(OperationalLog.created_at.desc()).limit(limit)
        if category:
            if category not in VALID_CATEGORIES:
                raise HTTPException(400, f"Unknown category: {category}")
            q = q.where(OperationalLog.category == category)
        rows = (await session.execute(q)).scalars().all()
    return {
        "logs": [_serialize(r) for r in rows],
        "count": len(rows),
    }


@router.post("")
async def create_operation(
    body: dict,
    user: AppUser = Depends(get_current_user),
):
    if user.role not in _STAFF_ROLES:
        raise HTTPException(403, "Staff only")

    category = (body.get("category") or "").strip()
    if category not in VALID_CATEGORIES:
        raise HTTPException(400, f"category must be one of: {', '.join(sorted(VALID_CATEGORIES))}")

    details = body.get("details") or {}
    if not isinstance(details, dict):
        raise HTTPException(400, "details must be an object")

    _validate_details(category, details)

    notes = (body.get("notes") or "").strip() or None
    logged_by = user.actor or user.user_id

    async with get_session() as session:
        log = OperationalLog(
            category=category,
            details=details,
            notes=notes,
            logged_by=logged_by,
        )
        session.add(log)
        await session.commit()
        await session.refresh(log)

    return _serialize(log)


@router.patch("/{log_id}")
async def patch_operation(
    log_id: int,
    body: dict,
    user: AppUser = Depends(get_current_user),
):
    if user.role not in _STAFF_ROLES:
        raise HTTPException(403, "Staff only")
    async with get_session() as session:
        result = await session.execute(
            select(OperationalLog).where(OperationalLog.id == log_id)
        )
        log = result.scalars().first()
        if not log:
            raise HTTPException(404, "Log entry not found")
        if "details" in body and isinstance(body["details"], dict):
            # Merge — allows partial updates (e.g. just filling in outage_end)
            merged = dict(log.details or {})
            merged.update({k: v for k, v in body["details"].items() if v not in (None, "")})
            log.details = merged
        if "notes" in body:
            log.notes = (body["notes"] or "").strip() or None
        await session.commit()
        await session.refresh(log)
    return _serialize(log)


@router.delete("/{log_id}")
async def delete_operation(
    log_id: int,
    user: AppUser = Depends(get_current_user),
):
    if user.role not in {"admin", "power_user"}:
        raise HTTPException(403, "Admins only")
    async with get_session() as session:
        result = await session.execute(
            select(OperationalLog).where(OperationalLog.id == log_id)
        )
        log = result.scalars().first()
        if not log:
            raise HTTPException(404, "Log entry not found")
        await session.execute(delete(OperationalLog).where(OperationalLog.id == log_id))
        await session.commit()
    return {"id": log_id, "status": "deleted"}


def _validate_details(category: str, details: dict) -> None:
    """Raise 422 if required fields are missing for the category."""
    required: dict[str, list[str]] = {
        "power_outage":        ["outage_start"],
        "hp_gas":              ["booking_date", "received_date", "cylinder_count"],
        "water_tanker":        ["received_at"],
        "garbage_collection":  ["informed_date"],
    }
    missing = [f for f in required.get(category, []) if not details.get(f)]
    if missing:
        raise HTTPException(422, f"Missing required fields for {category}: {', '.join(missing)}")


def _serialize(log: OperationalLog) -> dict:
    return {
        "id":         log.id,
        "category":   log.category,
        "details":    log.details,
        "notes":      log.notes,
        "logged_by":  log.logged_by,
        "created_at": log.created_at.isoformat() if log.created_at else None,
    }
