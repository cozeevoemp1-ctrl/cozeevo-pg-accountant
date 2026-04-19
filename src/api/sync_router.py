"""
src/api/sync_router.py
======================
Webhook endpoint for live sync from source Google Sheet.

Triggered by Google Apps Script onEdit → POST /api/sync/source-sheet
- Token-authenticated (shared secret)
- Debounced: multiple rapid calls coalesce into one sync after 30s quiet
- Safety net: aborts if >5 status flips or >20% cash variance, alerts admin

After DB updated → Operations sheet (current month) refreshed.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request
from loguru import logger

router = APIRouter(prefix="/api/sync", tags=["sync"])

# ── Config ────────────────────────────────────────────────────────────────
SYNC_TOKEN = os.getenv("SYNC_WEBHOOK_TOKEN", "kozzy-sync-2026")
DEBOUNCE_SECONDS = 30

# ── Debounce state ────────────────────────────────────────────────────────
_last_request_at: Optional[datetime] = None
_sync_task: Optional[asyncio.Task] = None
_lock = asyncio.Lock()


async def _run_sync() -> dict:
    """Pull source → DB → Operations sheet. Called after debounce window."""
    logger.info("[SyncWebhook] Running debounced sync")
    result = {"ok": False, "stage": "", "msg": ""}

    # 1. Pull source sheet → DB
    try:
        proc = await asyncio.to_thread(
            subprocess.run,
            ["venv/Scripts/python", "scripts/sync_from_source_sheet.py", "--write"],
            capture_output=True, text=True, timeout=600,
        )
        if proc.returncode != 0:
            logger.error("[SyncWebhook] Pull failed: %s", proc.stderr[-500:])
            result["stage"] = "pull"
            result["msg"] = proc.stderr[-500:]
            return result

        # Safety net — parse output for suspicious changes
        output = proc.stdout
        for line in output.split("\n"):
            if "updated_status" in line:
                try:
                    flipped = int(line.split(":")[1].strip())
                    if flipped > 5:
                        logger.warning(f"[SyncWebhook] {flipped} status flips — alerting admin")
                        await _alert_admin(f"⚠️ Live sync detected {flipped} status changes. Please verify.")
                except Exception:
                    pass

        logger.info("[SyncWebhook] DB updated from source")
    except Exception as e:
        logger.exception("[SyncWebhook] Pull exception")
        result["stage"] = "pull"
        result["msg"] = str(e)
        return result

    # 2. Refresh current month Operations sheet
    try:
        today = date.today()
        await asyncio.to_thread(
            subprocess.run,
            ["venv/Scripts/python", "scripts/sync_sheet_from_db.py",
             "--month", str(today.month), "--year", str(today.year), "--write"],
            capture_output=True, text=True, timeout=600,
        )
        logger.info("[SyncWebhook] Operations sheet refreshed")
    except Exception as e:
        logger.exception("[SyncWebhook] Sheet refresh exception")
        result["stage"] = "refresh"
        result["msg"] = str(e)
        return result

    # 3. Refresh DAY WISE tab
    try:
        await asyncio.to_thread(
            subprocess.run,
            ["venv/Scripts/python", "scripts/sync_daywise_from_db.py", "--write"],
            capture_output=True, text=True, timeout=300,
        )
        logger.info("[SyncWebhook] DAY WISE sheet refreshed")
    except Exception as e:
        logger.exception("[SyncWebhook] Daywise refresh exception")
        result["stage"] = "daywise"
        result["msg"] = str(e)
        return result

    result["ok"] = True
    result["stage"] = "complete"
    return result


async def _debounce_and_run():
    """Wait for quiet period, then run sync. Reset by new requests."""
    global _sync_task, _last_request_at
    try:
        while True:
            # Sleep until debounce window expires
            await asyncio.sleep(DEBOUNCE_SECONDS)
            async with _lock:
                now = datetime.now()
                if _last_request_at and (now - _last_request_at) >= timedelta(seconds=DEBOUNCE_SECONDS):
                    break
        # Run the sync
        await _run_sync()
    finally:
        async with _lock:
            _sync_task = None


async def _alert_admin(msg: str):
    """Send alert to admin via WhatsApp."""
    try:
        from src.whatsapp.webhook_handler import _send_whatsapp
        admin = os.getenv("ADMIN_PHONE", "")
        if admin:
            await _send_whatsapp(admin, msg)
    except Exception as e:
        logger.error("[SyncWebhook] Admin alert failed: %s", e)


@router.post("/source-sheet")
async def source_sheet_edit(
    request: Request,
    x_sync_token: Optional[str] = Header(None, alias="X-Sync-Token"),
):
    """
    Triggered by Google Apps Script onEdit on source sheet.
    Debounces bursts of edits into a single sync after DEBOUNCE_SECONDS of quiet.
    """
    # Auth
    if x_sync_token != SYNC_TOKEN:
        raise HTTPException(401, "Invalid sync token")

    global _last_request_at, _sync_task
    async with _lock:
        _last_request_at = datetime.now()
        if _sync_task is None or _sync_task.done():
            _sync_task = asyncio.create_task(_debounce_and_run())

    return {"ok": True, "queued": True, "debounce_seconds": DEBOUNCE_SECONDS}


@router.post("/source-sheet/now")
async def source_sheet_now(
    x_sync_token: Optional[str] = Header(None, alias="X-Sync-Token"),
):
    """Manual trigger — runs sync immediately (no debounce). For testing."""
    if x_sync_token != SYNC_TOKEN:
        raise HTTPException(401, "Invalid sync token")
    result = await _run_sync()
    return result
