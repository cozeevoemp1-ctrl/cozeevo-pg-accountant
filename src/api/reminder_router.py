"""
Reminder API — trigger reminders manually + send custom notices.

All endpoints are localhost-only (protected by LocalOnlyMiddleware in main.py).

Endpoints:
  POST /api/reminders/trigger-rent       — send rent reminders now (same as scheduler)
  POST /api/reminders/send-custom        — send a custom template to specific tenants
  POST /api/reminders/send-bulk          — send a notice to ALL active tenants
  GET  /api/reminders/preview-rent       — preview who would get rent reminders (dry run)
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from src.whatsapp.reminder_sender import send_template, send_reminder_text

import os
from dotenv import load_dotenv

load_dotenv()

router = APIRouter(prefix="/api/reminders", tags=["reminders"])

_ASYNC_DB_URL = os.getenv("DATABASE_URL", "").replace(
    "postgresql://", "postgresql+asyncpg://"
) if "+asyncpg" not in os.getenv("DATABASE_URL", "") else os.getenv("DATABASE_URL", "")


# ── Models ────────────────────────────────────────────────────────────────────

class TriggerRentRequest(BaseModel):
    label: str = "first"  # "first" or "second"

class CustomMessageRequest(BaseModel):
    phones: list[str]                    # list of phone numbers
    template_name: Optional[str] = None  # if using template
    body_params: Optional[list[str]] = None
    text_message: Optional[str] = None   # if sending free-form (24hr window only)

class BulkNoticeRequest(BaseModel):
    template_name: str = "general_notice"
    message: str       # the notice text (goes into {{2}} of general_notice template)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/preview-rent")
async def preview_rent_reminders():
    """Dry run — show who would receive rent reminders this month."""
    engine = create_async_engine(_ASYNC_DB_URL, echo=False)
    today = date.today()
    period = date(today.year, today.month, 1)

    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("""
                SELECT
                    t.name,
                    t.phone,
                    (rs.rent_due + COALESCE(rs.adjustment, 0)) AS due_total,
                    COALESCE(
                        (SELECT SUM(p.amount) FROM payments p
                         WHERE p.tenancy_id = rs.tenancy_id
                           AND p.period_month = rs.period_month
                           AND p.is_void = FALSE), 0
                    ) AS paid,
                    r.room_number
                FROM rent_schedule rs
                JOIN tenancies  tn ON tn.id  = rs.tenancy_id
                JOIN tenants    t  ON t.id   = tn.tenant_id
                JOIN rooms      r  ON r.id   = tn.room_id
                WHERE rs.period_month = :period
                  AND tn.status       = 'active'
                ORDER BY t.name
            """), {"period": period})
            rows = result.fetchall()
    finally:
        await engine.dispose()

    tenants = [
        {
            "name": r.name,
            "phone": r.phone,
            "room": r.room_number,
            "due": float(r.due_total),
            "paid": float(r.paid),
            "balance": float(r.due_total - r.paid),
        }
        for r in rows
        if float(r.due_total - r.paid) > 0
    ]

    return {
        "period": period,
        "count": len(tenants),
        "total_outstanding": sum(t["balance"] for t in tenants),
        "tenants": tenants,
    }


@router.get("/preview-all-tenants")
async def preview_all_tenants():
    """Show ALL active tenants who would receive a rent reminder."""
    engine = create_async_engine(_ASYNC_DB_URL, echo=False)

    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("""
                SELECT t.name, t.phone, r.room_number
                FROM tenancies tn
                JOIN tenants t ON t.id = tn.tenant_id
                JOIN rooms   r ON r.id = tn.room_id
                WHERE tn.status = 'active'
                  AND t.phone IS NOT NULL
                  AND t.phone != ''
                ORDER BY t.name
            """))
            rows = result.fetchall()
    finally:
        await engine.dispose()

    tenants = [{"name": r.name, "phone": r.phone, "room": r.room_number} for r in rows]
    return {"count": len(tenants), "tenants": tenants}


@router.post("/blast-rent-reminder")
async def blast_rent_reminder():
    """Send rent_reminder template to ALL active tenants. No amount, just generic reminder."""
    engine = create_async_engine(_ASYNC_DB_URL, echo=False)

    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("""
                SELECT t.name, t.phone
                FROM tenancies tn
                JOIN tenants t ON t.id = tn.tenant_id
                WHERE tn.status = 'active'
                  AND t.phone IS NOT NULL
                  AND t.phone != ''
                ORDER BY t.name
            """))
            rows = result.fetchall()
    finally:
        await engine.dispose()

    if not rows:
        return {"sent": 0, "failed": 0, "message": "No active tenants with phone numbers"}

    sent, failed = 0, 0
    for name, phone in rows:
        ok = await send_template(phone, "rent_reminder", body_params=[name])
        if ok:
            sent += 1
        else:
            failed += 1

    return {"sent": sent, "failed": failed, "total": len(rows)}


@router.post("/trigger-rent")
async def trigger_rent_reminders(req: TriggerRentRequest):
    """Manually trigger rent reminders (same logic as the scheduled job)."""
    from src.scheduler import _rent_reminder
    try:
        await _rent_reminder(label=req.label)
        return {"status": "ok", "label": req.label}
    except Exception as e:
        logger.error(f"[Reminder API] trigger-rent failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/send-custom")
async def send_custom_message(req: CustomMessageRequest):
    """Send a template or text message to specific phone numbers."""
    if not req.template_name and not req.text_message:
        raise HTTPException(400, "Provide either template_name or text_message")

    sent, failed = 0, 0
    for phone in req.phones:
        if req.template_name:
            ok = await send_template(phone, req.template_name, body_params=req.body_params)
        else:
            ok = await send_reminder_text(phone, req.text_message)
        if ok:
            sent += 1
        else:
            failed += 1

    return {"sent": sent, "failed": failed, "total": len(req.phones)}


@router.post("/send-bulk")
async def send_bulk_notice(req: BulkNoticeRequest):
    """Send a notice to ALL active tenants via template."""
    engine = create_async_engine(_ASYNC_DB_URL, echo=False)

    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("""
                SELECT t.name, t.phone
                FROM tenancies tn
                JOIN tenants t ON t.id = tn.tenant_id
                WHERE tn.status = 'active'
                  AND t.phone IS NOT NULL
                  AND t.phone != ''
                ORDER BY t.name
            """))
            rows = result.fetchall()
    finally:
        await engine.dispose()

    if not rows:
        return {"sent": 0, "message": "No active tenants with phone numbers"}

    sent, failed = 0, 0
    for name, phone in rows:
        ok = await send_template(
            phone, req.template_name,
            body_params=[name, req.message],
        )
        if ok:
            sent += 1
        else:
            failed += 1

    return {"sent": sent, "failed": failed, "total": len(rows)}
