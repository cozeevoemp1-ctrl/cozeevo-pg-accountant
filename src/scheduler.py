"""
Business Scheduler — Cozeevo PG Accountant
==========================================
Persistent APScheduler backed by SQLAlchemy (Supabase PostgreSQL).
Job state ("next_run_time") is stored in the DB — so scheduled jobs survive
server restarts, reboots, and VPS blips without missing a beat.

Jobs
----
  rent_reminder_early  — 1st of every month,  09:00 IST
                         WhatsApp each active tenant who still owes rent
  rent_reminder_late   — 15th of every month, 09:00 IST
                         Second nudge for tenants still unpaid after the 1st
  daily_reconciliation — every day at 02:00 IST
                         Compare rent_schedule dues vs payments; DM admin a gap report
  weekly_backup        — every Sunday at 03:00 IST
                         JSON snapshot of key tables → data/backups/YYYY-MM-DD/

Usage (called from main.py lifespan)
-----
  from src.scheduler import start_scheduler, stop_scheduler
  pg_scheduler = start_scheduler()
  ...
  stop_scheduler(pg_scheduler)
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path

from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

load_dotenv()

# ── URLs ───────────────────────────────────────────────────────────────────────
# DATABASE_URL in .env is always postgresql://... (plain psycopg2 style)
# APScheduler's SQLAlchemyJobStore needs the sync URL — use it directly.
# FastAPI / SQLAlchemy async layers replace "postgresql://" with "postgresql+asyncpg://"
# so both can coexist.
_raw_url      = os.getenv("DATABASE_URL", "")
# Normalize: strip +asyncpg if present to get plain sync URL for SQLAlchemyJobStore
_SYNC_DB_URL  = _raw_url.replace("postgresql+asyncpg://", "postgresql://")
_ASYNC_DB_URL = _raw_url if "+asyncpg" in _raw_url else _raw_url.replace("postgresql://", "postgresql+asyncpg://")
_ADMIN_PHONE  = os.getenv("ADMIN_PHONE", "")
_BACKUP_DIR   = Path(os.getenv("BACKUP_DIR", "data/backups"))


# ── Builder ────────────────────────────────────────────────────────────────────

def start_scheduler() -> AsyncIOScheduler:
    """
    Build, populate, and start the business scheduler.
    Returns the running AsyncIOScheduler instance.
    """
    if not _SYNC_DB_URL:
        logger.warning("[Scheduler] DATABASE_URL not set — scheduler disabled.")
        return AsyncIOScheduler()   # no-op scheduler

    jobstores = {
        "default": SQLAlchemyJobStore(
            url=_SYNC_DB_URL,
            tablename="apscheduler_jobs",   # auto-created on first run
        )
    }
    executors  = {"default": AsyncIOExecutor()}
    job_defaults = {
        "coalesce":          True,   # if server was down and missed multiple fires → run ONCE
        "misfire_grace_time": 3600,  # run the job if we're within 1hr of the scheduled time
        "max_instances":     1,      # never run the same job twice simultaneously
    }

    scheduler = AsyncIOScheduler(
        executors=executors,
        job_defaults=job_defaults,
        timezone="Asia/Kolkata",    # IST — all cron times below are IST
    )
    # Overwrite jobstores after init (APScheduler quirk with AsyncIOScheduler)
    scheduler._jobstores = {}
    scheduler.add_jobstore(jobstores["default"], "default")

    # ── Register jobs ──────────────────────────────────────────────────────────

    scheduler.add_job(
        _rent_reminder,
        trigger=CronTrigger(day=1, hour=9, minute=0),   # 1st of month, 9am
        id="rent_reminder_early",
        name="Rent Reminder — 1st of month",
        replace_existing=True,
        kwargs={"label": "first"},
    )

    scheduler.add_job(
        _rent_reminder,
        trigger=CronTrigger(day=15, hour=9, minute=0),  # 15th of month, 9am
        id="rent_reminder_late",
        name="Rent Reminder — 15th of month",
        replace_existing=True,
        kwargs={"label": "second"},
    )

    scheduler.add_job(
        _daily_reconciliation,
        trigger=CronTrigger(hour=2, minute=0),          # 2am daily
        id="daily_reconciliation",
        name="Daily Reconciliation",
        replace_existing=True,
    )

    scheduler.add_job(
        _weekly_backup,
        trigger=CronTrigger(day_of_week="sun", hour=3, minute=0),  # Sunday 3am
        id="weekly_backup",
        name="Weekly DB Backup",
        replace_existing=True,
    )

    scheduler.add_job(
        _checkout_deposit_alerts,
        trigger=CronTrigger(hour=9, minute=0),   # every day at 9am IST
        id="checkout_deposit_alerts",
        name="Checkout Deposit Alerts — 9am daily",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("[Scheduler] Started — 5 jobs registered (jobs persist in Supabase)")
    _log_next_runs(scheduler)
    return scheduler


def stop_scheduler(scheduler: AsyncIOScheduler) -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("[Scheduler] Stopped.")


def _log_next_runs(scheduler: AsyncIOScheduler) -> None:
    for job in scheduler.get_jobs():
        logger.info(f"  [{job.id}] next run: {job.next_run_time}")


# ── Job: Rent Reminders ────────────────────────────────────────────────────────

async def _rent_reminder(label: str = "first") -> None:
    """
    Query active tenancies with unpaid or partially-paid rent for the current month.
    Send a personalised WhatsApp reminder to each tenant's phone.
    label: "first" (1st of month) or "second" (15th of month)
    """
    from src.whatsapp.webhook_handler import _send_whatsapp

    engine = create_async_engine(_ASYNC_DB_URL, echo=False)
    today  = date.today()
    period = today.strftime("%Y-%m-01")  # first day of current month

    logger.info(f"[Scheduler] rent_reminder ({label}) — period {period}")

    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("""
                SELECT
                    t.name,
                    t.phone,
                    rs.due_amount,
                    rs.paid_amount,
                    (rs.due_amount - COALESCE(rs.paid_amount, 0)) AS balance
                FROM rent_schedule rs
                JOIN tenancies  tn ON tn.id  = rs.tenancy_id
                JOIN tenants    t  ON t.id   = tn.tenant_id
                WHERE rs.period_month = :period
                  AND tn.status       = 'active'
                  AND rs.is_void      = FALSE
                  AND (rs.due_amount - COALESCE(rs.paid_amount, 0)) > 0
                ORDER BY balance DESC
            """), {"period": period})
            rows = result.fetchall()
    finally:
        await engine.dispose()

    if not rows:
        logger.info("[Scheduler] rent_reminder — no unpaid tenants found.")
        return

    month_label = today.strftime("%B %Y")
    sent = 0
    for name, phone, due, paid, balance in rows:
        if not phone:
            continue
        if label == "first":
            msg = (
                f"Hi {name} 👋\n\n"
                f"This is a friendly reminder that your rent for *{month_label}* is due.\n"
                f"Amount due: *₹{balance:,.0f}*\n\n"
                f"Please arrange payment at your earliest convenience.\n"
                f"Thank you! — Cozeevo PG"
            )
        else:
            msg = (
                f"Hi {name},\n\n"
                f"This is a *second reminder* — your rent for *{month_label}* is still outstanding.\n"
                f"Balance: *₹{balance:,.0f}*\n\n"
                f"Kindly clear this immediately to avoid a late fee.\n"
                f"— Cozeevo PG"
            )
        await _send_whatsapp(phone, msg)
        sent += 1

    logger.info(f"[Scheduler] rent_reminder ({label}) — sent {sent}/{len(rows)} reminders")

    # Notify admin with summary
    if _ADMIN_PHONE and rows:
        summary = (
            f"📋 *Rent Reminder Sent ({label})* — {month_label}\n"
            f"Tenants messaged: {sent}\n"
            f"Total outstanding: ₹{sum(r[4] for r in rows):,.0f}"
        )
        await _send_whatsapp(_ADMIN_PHONE, summary)


# ── Job: Daily Reconciliation ──────────────────────────────────────────────────

async def _daily_reconciliation() -> None:
    """
    Compare rent_schedule dues vs payments for current month.
    Build a gap report and DM it to admin on WhatsApp.
    Runs at 2am IST so data from the previous day is complete.
    """
    from src.whatsapp.webhook_handler import _send_whatsapp

    engine = create_async_engine(_ASYNC_DB_URL, echo=False)
    today  = date.today()
    period = today.strftime("%Y-%m-01")

    logger.info(f"[Scheduler] daily_reconciliation — {today}")

    try:
        async with engine.connect() as conn:
            # Total dues vs collected for current month
            summary = await conn.execute(text("""
                SELECT
                    COUNT(*)                                          AS total_tenants,
                    SUM(rs.due_amount)                               AS total_due,
                    SUM(COALESCE(rs.paid_amount, 0))                 AS total_collected,
                    SUM(rs.due_amount - COALESCE(rs.paid_amount, 0)) AS total_gap,
                    COUNT(*) FILTER (
                        WHERE rs.due_amount - COALESCE(rs.paid_amount, 0) <= 0
                    )                                                AS fully_paid_count
                FROM rent_schedule rs
                JOIN tenancies tn ON tn.id = rs.tenancy_id
                WHERE rs.period_month = :period
                  AND tn.status       = 'active'
                  AND rs.is_void      = FALSE
            """), {"period": period})
            row = summary.fetchone()

            # Payments logged in the LAST 24 hours
            recent = await conn.execute(text("""
                SELECT COUNT(*), COALESCE(SUM(amount), 0)
                FROM payments
                WHERE received_at >= NOW() - INTERVAL '24 hours'
                  AND is_void = FALSE
            """))
            pay_count, pay_total = recent.fetchone()
    finally:
        await engine.dispose()

    if not row:
        logger.info("[Scheduler] daily_reconciliation — no data.")
        return

    total, due, collected, gap, paid_count = row
    month_label = today.strftime("%B %Y")

    report = (
        f"📊 *Daily Reconciliation — {today}*\n\n"
        f"*{month_label} rent status:*\n"
        f"  Active tenants:  {total}\n"
        f"  Total due:       ₹{due or 0:,.0f}\n"
        f"  Collected:       ₹{collected or 0:,.0f}\n"
        f"  Outstanding:     ₹{gap or 0:,.0f}\n"
        f"  Fully paid:      {paid_count}/{total}\n\n"
        f"*Last 24 hrs payments:*\n"
        f"  {pay_count} transactions — ₹{pay_total:,.0f}"
    )

    if _ADMIN_PHONE:
        await _send_whatsapp(_ADMIN_PHONE, report)
    logger.info(f"[Scheduler] daily_reconciliation done — gap ₹{gap or 0:,.0f}")


# ── Job: Weekly Backup ─────────────────────────────────────────────────────────

async def _weekly_backup() -> None:
    """
    Export key tables as JSON snapshots to data/backups/YYYY-MM-DD/.
    Tables: tenants, tenancies, payments, rent_schedule, investment_expenses.
    This is a SAFETY NET — Supabase has its own PITR backup on paid plans.
    Keeps 8 weeks of rolling backups locally (older folders are pruned).
    """
    engine = create_async_engine(_ASYNC_DB_URL, echo=False)
    today  = date.today().isoformat()
    backup_path = _BACKUP_DIR / today
    backup_path.mkdir(parents=True, exist_ok=True)

    TABLES = [
        "tenants",
        "tenancies",
        "payments",
        "rent_schedule",
        "investment_expenses",
        "pg_contacts",
        "authorized_users",
    ]

    logger.info(f"[Scheduler] weekly_backup → {backup_path}")
    total_rows = 0

    try:
        async with engine.connect() as conn:
            for table in TABLES:
                result = await conn.execute(text(f"SELECT * FROM {table}"))
                cols = list(result.keys())
                rows = [
                    {col: (_serialize(val)) for col, val in zip(cols, row)}
                    for row in result.fetchall()
                ]
                out_file = backup_path / f"{table}.json"
                out_file.write_text(json.dumps(rows, ensure_ascii=False, indent=2))
                total_rows += len(rows)
                logger.info(f"  {table}: {len(rows)} rows → {out_file.name}")
    finally:
        await engine.dispose()

    # Prune backups older than 8 weeks (keep last 8 Sunday snapshots)
    _prune_old_backups(max_keep=8)

    logger.info(f"[Scheduler] weekly_backup complete — {total_rows} rows across {len(TABLES)} tables")

    # Notify admin
    if _ADMIN_PHONE:
        from src.whatsapp.webhook_handler import _send_whatsapp
        await _send_whatsapp(
            _ADMIN_PHONE,
            f"✅ *Weekly Backup Complete — {today}*\n"
            f"Tables: {', '.join(TABLES)}\n"
            f"Total rows exported: {total_rows}\n"
            f"Location: data/backups/{today}/"
        )


def _serialize(val) -> object:
    """Make values JSON-serialisable."""
    if isinstance(val, (date, datetime)):
        return val.isoformat()
    return val


def _prune_old_backups(max_keep: int = 8) -> None:
    """Delete oldest backup folders, keeping only the last max_keep."""
    if not _BACKUP_DIR.exists():
        return
    folders = sorted(
        [f for f in _BACKUP_DIR.iterdir() if f.is_dir()],
        key=lambda f: f.name,
    )
    to_delete = folders[:-max_keep] if len(folders) > max_keep else []
    for old in to_delete:
        import shutil
        shutil.rmtree(old, ignore_errors=True)
        logger.info(f"[Scheduler] pruned old backup: {old.name}")


# ── Job: Checkout Deposit Alerts ───────────────────────────────────────────────

async def _checkout_deposit_alerts() -> None:
    """
    Runs every day at 09:00 IST.
    Finds tenancies with expected_checkout = today, sends deposit settlement
    summary to assigned staff + all admin/power_user phones.
    Creates a PendingAction(CONFIRM_DEPOSIT_REFUND) per recipient so they can
    reply 'process' or 'deduct XXXX' to finalise the refund.
    """
    import json
    from datetime import datetime, timedelta
    from src.whatsapp.webhook_handler import _send_whatsapp

    today = date.today()
    engine = create_async_engine(_ASYNC_DB_URL, echo=False)
    logger.info(f"[Scheduler] checkout_deposit_alerts — {today}")

    try:
        async with engine.connect() as conn:
            # Tenancies checking out today (scheduled via expected_checkout)
            rows = await conn.execute(text("""
                SELECT
                    tn.id             AS tenancy_id,
                    t.name            AS tenant_name,
                    r.room_number,
                    p.name            AS property_name,
                    p.id              AS property_id,
                    tn.security_deposit,
                    COALESCE(s.phone, '') AS staff_phone,
                    COALESCE(
                        (SELECT SUM(pay.amount) FROM payments pay
                         WHERE pay.tenancy_id = tn.id
                           AND pay.for_type = 'deposit'
                           AND pay.is_void = FALSE), 0
                    ) AS deposit_paid,
                    COALESCE(
                        (SELECT SUM(rs.due_amount - COALESCE(rs.paid_amount,0))
                         FROM rent_schedule rs
                         WHERE rs.tenancy_id = tn.id
                           AND rs.is_void = FALSE
                           AND rs.due_amount > COALESCE(rs.paid_amount, 0)), 0
                    ) AS outstanding_dues
                FROM tenancies tn
                JOIN tenants  t  ON t.id  = tn.tenant_id
                JOIN rooms    r  ON r.id  = tn.room_id
                JOIN properties p ON p.id = r.property_id
                LEFT JOIN staff s ON s.id = tn.assigned_staff_id
                WHERE tn.expected_checkout = :today
                  AND tn.status = 'active'
            """), {"today": today.isoformat()})
            checkouts = rows.fetchall()

            if not checkouts:
                logger.info("[Scheduler] checkout_deposit_alerts — no checkouts today.")
                return

            # All admin + power_user phones (to always notify owners)
            auth_rows = await conn.execute(text("""
                SELECT phone FROM authorized_users
                WHERE role IN ('admin', 'power_user') AND active = TRUE
            """))
            owner_phones = [r[0] for r in auth_rows.fetchall() if r[0]]

    finally:
        await engine.dispose()

    # Re-open engine for inserts (PendingActions)
    engine2 = create_async_engine(_ASYNC_DB_URL, echo=False)
    try:
        async with engine2.connect() as conn:
            for row in checkouts:
                tenancy_id    = row.tenancy_id
                tenant_name   = row.tenant_name
                room_number   = row.room_number
                prop_name     = row.property_name
                deposit_held  = int(row.deposit_paid or row.security_deposit or 0)
                outstanding   = int(row.outstanding_dues or 0)
                net_refund    = max(0, deposit_held - outstanding)
                staff_phone   = row.staff_phone

                msg = (
                    f"⚠️ *Checkout Today — {tenant_name}*\n"
                    f"Room       : {room_number} ({prop_name})\n"
                    f"Deposit    : Rs.{deposit_held:,}\n"
                    f"Outstanding: -Rs.{outstanding:,}\n"
                    f"*Net refund : Rs.{net_refund:,}*\n\n"
                    "Reply:\n"
                    "• *process* — confirm refund as above\n"
                    "• *deduct XXXX* — deduct maintenance first\n"
                    "• *deduct XXXX process* — deduct and confirm in one step"
                )

                action_data = json.dumps({
                    "tenancy_id":   tenancy_id,
                    "tenant_name":  tenant_name,
                    "room":         room_number,
                    "deposit_held": deposit_held,
                    "maintenance":  outstanding,
                    "net_refund":   net_refund,
                })
                expires_at = (datetime.utcnow() + timedelta(hours=48)).isoformat()

                # Collect unique phones to notify
                phones_to_notify = set(owner_phones)
                if staff_phone:
                    phones_to_notify.add(staff_phone)

                for phone in phones_to_notify:
                    await _send_whatsapp(phone, msg)
                    # Create PendingAction so 'process' reply is caught
                    await conn.execute(text("""
                        INSERT INTO pending_actions (phone, intent, action_data, choices, expires_at, resolved)
                        VALUES (:phone, 'CONFIRM_DEPOSIT_REFUND', :action_data, '[]', :expires_at, FALSE)
                    """), {"phone": phone, "action_data": action_data, "expires_at": expires_at})

                await conn.commit()
                logger.info(
                    f"[Scheduler] checkout alert sent — {tenant_name} ({room_number})"
                    f" deposit=Rs.{deposit_held:,} net=Rs.{net_refund:,}"
                    f" → {len(phones_to_notify)} recipients"
                )
    finally:
        await engine2.dispose()
