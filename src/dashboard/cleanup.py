"""
Dashboard auto-cleanup scheduler.
Deletes HTML dashboard files older than TTL_HOURS.
Runs as a background APScheduler job.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger


def cleanup_old_dashboards(
    dashboard_dir: str | None = None,
    ttl_hours: int | None = None,
):
    """Delete dashboard files older than ttl_hours."""
    base_dir = Path(dashboard_dir or os.getenv("DASHBOARD_DIR", "./dashboards"))
    ttl      = ttl_hours or int(os.getenv("DASHBOARD_TTL_HOURS", "24"))
    cutoff   = datetime.now() - timedelta(hours=ttl)

    if not base_dir.exists():
        return

    deleted = 0
    for f in base_dir.glob("dashboard_*.html"):
        mtime = datetime.fromtimestamp(f.stat().st_mtime)
        if mtime < cutoff:
            f.unlink()
            deleted += 1
            logger.info(f"[Cleanup] Deleted old dashboard: {f.name}")

    if deleted:
        logger.info(f"[Cleanup] Removed {deleted} expired dashboard(s).")


def start_cleanup_scheduler() -> AsyncIOScheduler:
    """Start background scheduler that runs cleanup every hour."""
    scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")
    scheduler.add_job(
        cleanup_old_dashboards,
        trigger="interval",
        hours=1,
        id="dashboard_cleanup",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("[Cleanup] Dashboard cleanup scheduler started (runs every 1h).")
    return scheduler
