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

# Hold the lock file descriptor for the process lifetime — lock releases on exit.
_scheduler_lock_fd: int | None = None


def _acquire_scheduler_lock() -> bool:
    """Return True if this worker should own the scheduler, False otherwise.

    Why: uvicorn runs with --workers 2 on the VPS, and each worker was
    constructing its own APScheduler + SQLAlchemyJobStore, so every cron job
    fired twice (duplicate reminders, duplicate reconciliations, etc.).
    APScheduler's jobstore does not coordinate runs across processes — we
    coordinate via a POSIX advisory lock instead. Exactly one worker wins the
    lock; others return a no-op scheduler. On Windows (local dev, single
    worker), fcntl is unavailable — skip the lock and always run.
    """
    global _scheduler_lock_fd
    try:
        import fcntl
    except ImportError:
        return True   # Windows local dev — assume single worker

    lock_path = os.getenv("SCHEDULER_LOCK_PATH", "/tmp/pg-accountant-scheduler.lock")
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_WRONLY, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode())
        _scheduler_lock_fd = fd   # keep fd open so kernel holds the lock
        logger.info("[Scheduler] acquired lock %s (pid=%d)", lock_path, os.getpid())
        return True
    except (BlockingIOError, OSError) as e:
        logger.info("[Scheduler] lock held by another worker — skipping (pid=%d, %s)",
                    os.getpid(), e)
        return False


# ── Builder ────────────────────────────────────────────────────────────────────

def start_scheduler() -> AsyncIOScheduler:
    """
    Build, populate, and start the business scheduler.
    Returns the running AsyncIOScheduler instance.
    """
    if not _SYNC_DB_URL:
        logger.warning("[Scheduler] DATABASE_URL not set — scheduler disabled.")
        return AsyncIOScheduler()   # no-op scheduler

    if not _acquire_scheduler_lock():
        return AsyncIOScheduler()   # another worker owns the scheduler

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

    # !! RENT REMINDERS DISABLED — Kiran 2026-05-13. Do NOT re-enable without explicit instruction.
    # !! Use PWA to send manually when needed.
    # scheduler.add_job(
    #     _rent_reminder,
    #     trigger=CronTrigger(hour=9, minute=0, timezone="Asia/Kolkata"),
    #     id="rent_reminder_advance",
    #     name="Rent Reminder — Day -1 (last day of month)",
    #     replace_existing=True,
    #     kwargs={"mode": "advance"},
    # )
    # for _day, _id in [(1, "rent_reminder_day1"), (3, "rent_reminder_day3"), (5, "rent_reminder_day5")]:
    #     scheduler.add_job(
    #         _rent_reminder,
    #         trigger=CronTrigger(day=_day, hour=9, minute=0, timezone="Asia/Kolkata"),
    #         id=_id,
    #         name=f"Rent Reminder — Day {_day} (overdue tenants)",
    #         replace_existing=True,
    #         kwargs={"mode": "overdue_daily"},
    #     )

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

    # Rollover on second-last calendar day of every month at 23:00 IST.
    # Job self-checks (handles 28/29/30/31-day months + leap years automatically).
    scheduler.add_job(
        _monthly_tab_rollover,
        trigger=CronTrigger(hour=23, minute=0),  # daily 11pm; self-checks day
        id="monthly_tab_rollover",
        name="Monthly Rollover — 2nd-to-last calendar day, 11pm IST",
        replace_existing=True,
    )


    # Prep reminders — TWO separate messages at 08:00 IST daily.
    # Each message is only sent if its target day actually has movements;
    # nothing scheduled → nothing sent (no empty "no movements" noise).
    # Recipients: every admin / owner / receptionist in authorized_users
    # (includes Lokesh 7680814628).
    # 9am → TODAY (morning briefing of what's happening today).
    # 2pm → TOMORROW (afternoon heads-up so reception can prep for next day).
    scheduler.add_job(
        _prep_reminder,
        trigger=CronTrigger(hour=9, minute=0, timezone="Asia/Kolkata"),
        id="prep_reminder_today",
        name="Prep Reminder — today's checkins/outs (9am IST)",
        replace_existing=True,
        kwargs={"when": "today"},
    )
    scheduler.add_job(
        _prep_reminder,
        trigger=CronTrigger(hour=14, minute=0, timezone="Asia/Kolkata"),
        id="prep_reminder_tomorrow",
        name="Prep Reminder — tomorrow's checkins/outs (2pm IST)",
        replace_existing=True,
        kwargs={"when": "tomorrow"},
    )

    # Nightly sheet↔DB drift audit — 23:30 IST. Alerts admin on WhatsApp when
    # TENANTS / current-monthly-tab values diverge from DB (manual sheet edits).
    scheduler.add_job(
        _nightly_sheet_audit,
        trigger=CronTrigger(hour=23, minute=30, timezone="Asia/Kolkata"),
        id="nightly_sheet_audit",
        name="Nightly Sheet Audit — DB↔Sheet drift check (11:30pm IST)",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("[Scheduler] Started — 5 jobs registered (rent reminders disabled 2026-05-13)")
    _log_next_runs(scheduler)
    return scheduler


def stop_scheduler(scheduler: AsyncIOScheduler) -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("[Scheduler] Stopped.")


def _log_next_runs(scheduler: AsyncIOScheduler) -> None:
    for job in scheduler.get_jobs():
        logger.info(f"  [{job.id}] next run: {job.next_run_time}")


# ── Job: Check-in/out Prep Reminders ──────────────────────────────────────────

async def _prep_reminder(when: str = "today") -> None:
    """
    Morning prep reminder — fires twice at 08:00 IST daily, once per target day.
      when='today'    → check-ins/outs happening today (day-of reminder).
      when='tomorrow' → check-ins/outs happening tomorrow (24-hour advance).

    If the target day has NOTHING (no check-ins AND no check-outs), no
    message is sent. If it has only check-ins, only the check-ins section
    is shown (and vice versa for check-outs).

    Check-ins: tenancies.checkin_date = target AND status IN (active, no_show).
               (no_show stays in the list so reception keeps preparing the bed
               until the tenant actually arrives.)
    Check-outs: tenancies.expected_checkout = target AND status = active.

    Recipients: every authorized_users row with role IN (admin, owner,
    receptionist) AND active = TRUE. Today that is Kiran, the partner,
    Prabhakaran, Lakshmi, and Lokesh (7680814628, receptionist).
    """
    from datetime import timedelta
    from src.whatsapp.webhook_handler import _send_whatsapp

    today = date.today()
    if when == "tomorrow":
        target = today + timedelta(days=1)
        header_label = "TOMORROW"
    else:
        target = today
        header_label = "TODAY"

    logger.info(f"[Scheduler] prep_reminder ({when}) — target={target}")

    engine = create_async_engine(_ASYNC_DB_URL, echo=False)
    try:
        async with engine.connect() as conn:
            checkins = (await conn.execute(text("""
                SELECT t.name, r.room_number, COALESCE(t.phone, '') AS phone,
                       COALESCE(tn.sharing_type::text, '') AS sharing,
                       COALESCE(tn.notes, '') AS notes
                FROM tenancies tn
                JOIN tenants t ON t.id = tn.tenant_id
                JOIN rooms r   ON r.id = tn.room_id
                WHERE tn.checkin_date = :target
                  AND tn.status IN ('active', 'no_show')
                ORDER BY r.room_number
            """), {"target": target})).fetchall()

            checkouts = (await conn.execute(text("""
                SELECT t.name, r.room_number, COALESCE(t.phone, '') AS phone,
                       COALESCE(tn.notes, '') AS notes
                FROM tenancies tn
                JOIN tenants t ON t.id = tn.tenant_id
                JOIN rooms r   ON r.id = tn.room_id
                WHERE tn.expected_checkout = :target
                  AND tn.status = 'active'
                ORDER BY r.room_number
            """), {"target": target})).fetchall()

            # Day-wise short-stay prebookings — separate table, same target day.
            daywise_in = (await conn.execute(text("""
                SELECT guest_name, room_number, COALESCE(phone, '') AS phone,
                       COALESCE(stay_period, '') AS period,
                       COALESCE(num_days, 0) AS days,
                       COALESCE(comments, '') AS notes
                FROM daywise_stays
                WHERE checkin_date = :target
                ORDER BY room_number
            """), {"target": target})).fetchall()

            daywise_out = (await conn.execute(text("""
                SELECT guest_name, room_number, COALESCE(phone, '') AS phone
                FROM daywise_stays
                WHERE checkout_date = :target
                ORDER BY room_number
            """), {"target": target})).fetchall()

            admin_rows = (await conn.execute(text("""
                SELECT phone, COALESCE(NULLIF(name, ''), 'team') AS name
                FROM authorized_users
                WHERE role IN ('admin', 'owner', 'receptionist') AND active = TRUE
            """))).fetchall()
    finally:
        await engine.dispose()

    # Suppress entirely if nothing is scheduled for this target day
    # (across tenancies + daywise_stays).
    if not checkins and not checkouts and not daywise_in and not daywise_out:
        logger.info(f"[Scheduler] prep_reminder ({when}) — nothing scheduled, not sending.")
        return

    admin_recipients = [(r[0], r[1]) for r in admin_rows if r[0]]
    if not admin_recipients:
        logger.warning("[Scheduler] prep_reminder — no admin/owner/receptionist phones configured.")
        return

    lines = [f"*Room Prep — {header_label} ({target.strftime('%a %d %b %Y')})*"]
    if checkins:
        lines.append(f"\n*Check-ins ({len(checkins)}):*")
        for nm, rn, ph, sh, nt in checkins:
            sh_part = f" — {sh}" if sh else ""
            ph_part = f" ({ph})" if ph else ""
            nt_part = f"\n   _{nt[:80]}_" if nt else ""
            lines.append(f"• Room {rn}{sh_part} — {nm}{ph_part}{nt_part}")
    if checkouts:
        lines.append(f"\n*Check-outs ({len(checkouts)}):*")
        for nm, rn, ph, nt in checkouts:
            ph_part = f" ({ph})" if ph else ""
            nt_part = f"\n   _{nt[:80]}_" if nt else ""
            lines.append(f"• Room {rn} — {nm}{ph_part}{nt_part}")
    if daywise_in:
        lines.append(f"\n*Day-wise check-ins ({len(daywise_in)}):*")
        for nm, rn, ph, pd, dy, nt in daywise_in:
            ph_part = f" ({ph})" if ph else ""
            days_part = f" — {dy}d" if dy else ""
            period_part = f" [{pd}]" if pd else ""
            nt_part = f"\n   _{nt[:80]}_" if nt else ""
            lines.append(f"• Room {rn}{days_part}{period_part} — {nm}{ph_part}{nt_part}")
    if daywise_out:
        lines.append(f"\n*Day-wise check-outs ({len(daywise_out)}):*")
        for nm, rn, ph in daywise_out:
            ph_part = f" ({ph})" if ph else ""
            lines.append(f"• Room {rn} — {nm}{ph_part}")

    msg = "\n".join(lines)
    sent = 0
    for phone, name in admin_recipients:
        try:
            ok = await _send_whatsapp(phone, msg)
            if ok:
                sent += 1
                logger.info(f"[Scheduler] prep_reminder ({when}) — sent to {phone} ({name})")
            else:
                logger.warning(f"[Scheduler] prep_reminder ({when}) — send FAILED to {phone}")
        except Exception as e:
            logger.warning(f"[Scheduler] prep_reminder ({when}) — send to {phone} exception: {e}")
    logger.info(f"[Scheduler] prep_reminder ({when}) — {sent}/{len(admin_recipients)} delivered")


# ── Job: Rent Reminders ────────────────────────────────────────────────────────

# Billing rule (see docs/BUSINESS_LOGIC.md § Late Fee).
LATE_FEE_PER_DAY  = 200   # Rupees per day after the grace window
LATE_FEE_FROM_DAY = 6     # Fee starts accruing on this day of the month


async def _rent_reminder(mode: str = "day1") -> None:
    if os.getenv("REMINDERS_PAUSED", "0") == "1":
        logger.info("[Scheduler] _rent_reminder skipped — REMINDERS_PAUSED=1")
        return
    """Three-tier rent reminder — all delivered via approved Meta templates so
    no 24-hour customer-service window is required.

      mode='advance'      → fires daily 09:00 IST; only runs on
                            (last day of month − 1), i.e. 2 days before the
                            next month begins. Sends the ``rent_reminder``
                            template to *every* active tenant for NEXT month.

      mode='day1'         → fires daily 09:00 IST; only runs on the 1st.
                            Sends ``rent_reminder`` to *every* active tenant
                            for the current month.

      mode='overdue_daily' → fires daily 09:00 IST; only runs from day 2
                            onwards. Sends ``general_notice`` (custom wording)
                            to tenants still unpaid for the current month, and
                            includes the Rs.200/day late-fee warning that
                            accrues from day 6.

    Tenants stop receiving the overdue reminder the day after their payment
    clears the balance (rent_schedule.paid_amount >= due_amount).
    """
    import calendar
    from src.whatsapp.reminder_sender import send_template

    today = date.today()

    if mode == "advance":
        last_day = calendar.monthrange(today.year, today.month)[1]
        if today.day != last_day:
            return
        target_year  = today.year + (1 if today.month == 12 else 0)
        target_month = 1 if today.month == 12 else today.month + 1
        period        = date(target_year, target_month, 1)
        all_active    = True
        template_name = "rent_reminder"
        log_tag       = "advance (2 days before next month)"
    elif mode == "day1":
        if today.day != 1:
            return
        period        = date(today.year, today.month, 1)
        all_active    = True
        template_name = "rent_reminder"
        log_tag       = "day1 (all active)"
    elif mode == "overdue_daily":
        period        = date(today.year, today.month, 1)
        all_active    = False
        template_name = "rent_reminder"
        log_tag       = f"overdue_daily (day {today.day}, unpaid)"
    else:
        logger.warning("[Scheduler] _rent_reminder unknown mode: %s", mode)
        return

    month_label = period.strftime("%B %Y")
    logger.info("[Scheduler] rent_reminder (%s) — period=%s", log_tag, period)

    engine = create_async_engine(_ASYNC_DB_URL, echo=False)
    try:
        async with engine.connect() as conn:
            if all_active:
                # rent_schedule row for the target period may not exist yet on
                # the 'advance' fire (rollover runs same evening, after our
                # 09:00 IST slot). Fall back to tenancy.agreed_rent.
                rows = (await conn.execute(text("""
                    SELECT t.name, t.phone,
                           COALESCE(rs.rent_due + COALESCE(rs.adjustment, 0),
                                    tn.agreed_rent, 0) AS balance
                    FROM tenancies tn
                    JOIN tenants t ON t.id = tn.tenant_id
                    LEFT JOIN rent_schedule rs
                           ON rs.tenancy_id = tn.id
                          AND rs.period_month = :period
                    WHERE tn.status = 'active'
                      AND t.phone IS NOT NULL AND t.phone <> ''
                    ORDER BY t.name
                """), {"period": period})).fetchall()
            else:
                rows = (await conn.execute(text("""
                    SELECT t.name, t.phone,
                           (rs.rent_due + COALESCE(rs.adjustment, 0)
                            - COALESCE(p_sum.paid, 0)) AS balance
                    FROM rent_schedule rs
                    JOIN tenancies tn ON tn.id = rs.tenancy_id
                    JOIN tenants   t  ON t.id  = tn.tenant_id
                    LEFT JOIN (
                        SELECT tenancy_id, SUM(amount) AS paid
                        FROM payments
                        WHERE for_type = 'rent'
                          AND period_month = :period
                          AND is_void = FALSE
                        GROUP BY tenancy_id
                    ) p_sum ON p_sum.tenancy_id = tn.id
                    WHERE rs.period_month = :period
                      AND tn.status       = 'active'
                      AND rs.status       IN ('pending', 'partial')
                      AND t.phone IS NOT NULL AND t.phone <> ''
                      AND (rs.rent_due + COALESCE(rs.adjustment, 0)
                           - COALESCE(p_sum.paid, 0)) > 0
                    ORDER BY balance DESC
                """), {"period": period})).fetchall()
    finally:
        await engine.dispose()

    if not rows:
        logger.info("[Scheduler] rent_reminder (%s) — no recipients.", log_tag)
        return

    sent = 0
    for name, phone, balance in rows:
        if not phone or not balance or float(balance) <= 0:
            continue
        try:
            ok = await send_template(
                phone, "general_notice",
                body_params=[month_label],
            )
            if ok:
                sent += 1
        except Exception as e:
            logger.warning("[Scheduler] rent_reminder (%s) — send to %s exception: %s",
                           log_tag, phone, e)

    logger.info("[Scheduler] rent_reminder (%s) — %d/%d sent via %s",
                log_tag, sent, len(rows), template_name)

    # Notify all admin/owner phones so the team knows reminders went out.
    from src.whatsapp.webhook_handler import _send_whatsapp
    engine2 = create_async_engine(_ASYNC_DB_URL, echo=False)
    try:
        async with engine2.connect() as conn2:
            admin_rows = (await conn2.execute(text("""
                SELECT phone FROM authorized_users
                WHERE role IN ('admin', 'owner') AND active = TRUE AND phone IS NOT NULL
            """))).fetchall()
    finally:
        await engine2.dispose()
    summary_msg = (
        f"*Rent Reminder — {log_tag}*\n"
        f"Month: {month_label}\n"
        f"Sent: {sent}/{len(rows)} via `{template_name}` template."
    )
    for (ap,) in admin_rows:
        if ap:
            await _send_whatsapp(ap, summary_msg)


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
    period = date(today.year, today.month, 1)

    logger.info(f"[Scheduler] daily_reconciliation — {today}")

    try:
        async with engine.connect() as conn:
            # Total dues vs collected for current month
            summary = await conn.execute(text("""
                SELECT
                    COUNT(*)                                              AS total_tenants,
                    SUM(rs.rent_due + COALESCE(rs.adjustment, 0))        AS total_due,
                    SUM(COALESCE(p_sum.paid, 0))                         AS total_collected,
                    SUM(rs.rent_due + COALESCE(rs.adjustment, 0)
                        - COALESCE(p_sum.paid, 0))                       AS total_gap,
                    COUNT(*) FILTER (
                        WHERE rs.rent_due + COALESCE(rs.adjustment, 0)
                              - COALESCE(p_sum.paid, 0) <= 0
                    )                                                     AS fully_paid_count
                FROM rent_schedule rs
                JOIN tenancies tn ON tn.id = rs.tenancy_id
                LEFT JOIN (
                    SELECT tenancy_id, SUM(amount) AS paid
                    FROM payments
                    WHERE for_type = 'rent' AND period_month = :period AND is_void = FALSE
                    GROUP BY tenancy_id
                ) p_sum ON p_sum.tenancy_id = rs.tenancy_id
                WHERE rs.period_month = :period
                  AND tn.status       = 'active'
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


# ── Job: Monthly Sheet Tab Rollover ───────────────────────────────────────────

async def _monthly_tab_rollover() -> None:
    """Atomic monthly rollover — fires daily at 23:00 IST, self-checks whether
    today is the second-last calendar day of the month. If yes:
      1. Pull source sheet → DB
      2. Generate RentSchedule rows for NEXT month (active + no-show only,
         exited/cancelled skipped; first-month prorate applied)
      3. Create NEXT month's tab in Operations sheet
      4. Reconcile sheet ↔ DB
    Handles 28/29/30/31-day months + Feb leap years automatically via
    calendar.monthrange (Python stdlib).
    """
    import asyncio
    import calendar
    import subprocess
    import sys
    import os
    from datetime import date

    today = date.today()
    last_day = calendar.monthrange(today.year, today.month)[1]
    if today.day != last_day - 1:
        # Not the second-last day — skip silently. Daily fire is intentional.
        return

    MONTHS = ["JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY",
              "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER"]
    if today.month == 12:
        next_year, next_month_num = today.year + 1, 1
    else:
        next_year, next_month_num = today.year, today.month + 1
    next_month_name = MONTHS[next_month_num - 1]

    logger.info("[Scheduler] Monthly rollover fire — target %s %d",
                next_month_name, next_year)

    # Use the running interpreter — works identically on Windows dev + Linux VPS.
    import sys as _sys
    py = _sys.executable

    try:
        result = await asyncio.to_thread(
            subprocess.run,
            [py, "scripts/run_monthly_rollover.py", next_month_name, str(next_year), "--skip-source"],
            capture_output=True, text=True, timeout=900,
        )
        if result.returncode != 0:
            logger.error("[Scheduler] Monthly rollover failed (rc=%s): %s",
                         result.returncode, (result.stderr or result.stdout)[-600:])
            if _ADMIN_PHONE:
                from src.whatsapp.webhook_handler import _send_whatsapp
                await _send_whatsapp(
                    _ADMIN_PHONE,
                    f"⚠️ Monthly rollover FAILED for {next_month_name} {next_year}.\n"
                    f"Check server logs. Run manually:\n"
                    f"python scripts/run_monthly_rollover.py {next_month_name} {next_year}"
                )
            return

        logger.info("[Scheduler] Monthly rollover done: %s %d",
                    next_month_name, next_year)
        if _ADMIN_PHONE:
            from src.whatsapp.webhook_handler import _send_whatsapp
            await _send_whatsapp(
                _ADMIN_PHONE,
                f"✅ Monthly rollover complete — {next_month_name} {next_year}\n"
                f"Sheet tab created, RentSchedule rows generated, dashboard refreshed."
            )
    except Exception as e:
        logger.error("[Scheduler] Monthly rollover exception: %s", e)




# ── Job: Checkout Deposit Alerts ───────────────────────────────────────────────

async def _checkout_deposit_alerts() -> None:
    """
    Runs every day at 09:00 IST.
    Finds checkouts today from BOTH tenancies (monthly) and daywise_stays,
    sends deposit/balance summary to all admin/owner phones.
    For monthly tenancies: creates PendingAction(CONFIRM_DEPOSIT_REFUND) for
    'process' / 'deduct XXXX' refund flow.
    """
    import json
    from datetime import datetime, timedelta
    from src.whatsapp.webhook_handler import _send_whatsapp

    today = date.today()
    engine = create_async_engine(_ASYNC_DB_URL, echo=False)
    logger.info(f"[Scheduler] checkout_deposit_alerts — {today}")

    try:
        async with engine.connect() as conn:
            # Monthly tenancies checking out today
            rows = await conn.execute(text("""
                SELECT
                    tn.id             AS tenancy_id,
                    t.name            AS tenant_name,
                    r.room_number,
                    p.name            AS property_name,
                    tn.security_deposit,
                    COALESCE(s.phone, '') AS staff_phone,
                    COALESCE(
                        (SELECT SUM(pay.amount) FROM payments pay
                         WHERE pay.tenancy_id = tn.id
                           AND pay.for_type = 'deposit'
                           AND pay.is_void = FALSE), 0
                    ) AS deposit_paid,
                    COALESCE(
                        (SELECT SUM(rs2.rent_due + COALESCE(rs2.adjustment, 0)
                                    - COALESCE(
                                        (SELECT SUM(p2.amount) FROM payments p2
                                         WHERE p2.tenancy_id = tn.id
                                           AND p2.for_type = 'rent'
                                           AND p2.period_month = rs2.period_month
                                           AND p2.is_void = FALSE), 0))
                         FROM rent_schedule rs2
                         WHERE rs2.tenancy_id = tn.id
                           AND rs2.status IN ('pending', 'partial')), 0
                    ) AS outstanding_dues
                FROM tenancies tn
                JOIN tenants  t  ON t.id  = tn.tenant_id
                JOIN rooms    r  ON r.id  = tn.room_id
                JOIN properties p ON p.id = r.property_id
                LEFT JOIN staff s ON s.id = tn.assigned_staff_id
                WHERE tn.expected_checkout = :today
                  AND tn.status = 'active'
            """), {"today": today})
            monthly_checkouts = rows.fetchall()

            # Day-wise stays checking out today
            dw_rows = await conn.execute(text("""
                SELECT guest_name, room_number,
                       COALESCE(balance_due, 0) AS balance_due,
                       COALESCE(total_amount, 0) AS total_amount,
                       COALESCE(amount_paid, 0)  AS amount_paid
                FROM daywise_stays
                WHERE checkout_date = :today
                  AND status = 'ACTIVE'
            """), {"today": today})
            daywise_checkouts = dw_rows.fetchall()

            if not monthly_checkouts and not daywise_checkouts:
                logger.info("[Scheduler] checkout_deposit_alerts — no checkouts today.")
                return

            # All admin + owner phones
            auth_rows = await conn.execute(text("""
                SELECT phone FROM authorized_users
                WHERE role IN ('admin', 'owner') AND active = TRUE
            """))
            owner_phones = [r[0] for r in auth_rows.fetchall() if r[0]]

    finally:
        await engine.dispose()

    engine2 = create_async_engine(_ASYNC_DB_URL, echo=False)
    try:
        async with engine2.connect() as conn:
            # Monthly tenancy alerts (with deposit refund flow)
            for row in monthly_checkouts:
                tenancy_id   = row.tenancy_id
                tenant_name  = row.tenant_name
                room_number  = row.room_number
                prop_name    = row.property_name
                deposit_held = int(row.deposit_paid or row.security_deposit or 0)
                outstanding  = int(row.outstanding_dues or 0)
                net_refund   = max(0, deposit_held - outstanding)
                staff_phone  = row.staff_phone

                msg = (
                    f"*Checkout Today — {tenant_name}*\n"
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

                phones_to_notify = set(owner_phones)
                if staff_phone:
                    phones_to_notify.add(staff_phone)

                for phone in phones_to_notify:
                    await _send_whatsapp(phone, msg)
                    await conn.execute(text("""
                        INSERT INTO pending_actions (phone, intent, action_data, choices, expires_at, resolved)
                        VALUES (:phone, 'CONFIRM_DEPOSIT_REFUND', :action_data, '[]', :expires_at, FALSE)
                    """), {"phone": phone, "action_data": action_data, "expires_at": expires_at})

                await conn.commit()
                logger.info(
                    f"[Scheduler] checkout alert (monthly) — {tenant_name} ({room_number})"
                    f" deposit=Rs.{deposit_held:,} net=Rs.{net_refund:,}"
                    f" → {len(phones_to_notify)} recipients"
                )

            # Day-wise stay alerts (no deposit flow, just balance summary)
            for row in daywise_checkouts:
                guest_name  = row.guest_name
                room_number = row.room_number
                balance_due = int(row.balance_due or 0)
                total       = int(row.total_amount or 0)
                paid        = int(row.amount_paid or 0)

                msg = (
                    f"*Day-wise Checkout Today — {guest_name}*\n"
                    f"Room     : {room_number}\n"
                    f"Total    : Rs.{total:,}\n"
                    f"Paid     : Rs.{paid:,}\n"
                    f"*Balance : Rs.{balance_due:,}*"
                )
                for phone in owner_phones:
                    await _send_whatsapp(phone, msg)

                await conn.commit()
                logger.info(
                    f"[Scheduler] checkout alert (daywise) — {guest_name} ({room_number})"
                    f" balance=Rs.{balance_due:,} → {len(owner_phones)} recipients"
                )
    finally:
        await engine2.dispose()




# ── Job: Nightly Sheet Audit ──────────────────────────────────────────────────

async def _nightly_sheet_audit() -> None:
    """
    Compare TENANTS + current-monthly-tab cells against DB on high-signal
    fields (Room, Rent, Deposit, Cash, UPI, Total Paid, Notice Date,
    Checkout Date). WhatsApp the admin if any drift is detected so a manual
    edit on the sheet — which the bot would never notice on its own — gets
    surfaced within 24h.

    Not auto-heal. `sync_sheet_from_db.py` preserves sheet Cash/UPI values, so
    blindly re-running it could keep an accidental zero. Kiran triages first.
    """
    from src.services.sheet_audit import run_audit, whatsapp_message
    from src.whatsapp.webhook_handler import _send_whatsapp

    logger.info("[Scheduler] nightly_sheet_audit — running")
    try:
        result = await run_audit()
    except Exception as e:
        logger.exception(f"[Scheduler] nightly_sheet_audit failed: {e}")
        if _ADMIN_PHONE:
            await _send_whatsapp(
                _ADMIN_PHONE,
                f"Sheet audit FAILED at {datetime.now():%Y-%m-%d %H:%M}: {e}"
            )
        return

    logger.info(
        f"[Scheduler] nightly_sheet_audit — tenants_diffs={len(result.tenants_diffs)} "
        f"monthly_diffs={len(result.monthly_diffs)} "
        f"missing_in_db={len(result.missing_in_db)} "
        f"missing_in_sheet={len(result.missing_in_sheet)}"
    )

    if result.total_diffs == 0:
        return   # silent on clean runs — no WhatsApp spam

    if _ADMIN_PHONE:
        await _send_whatsapp(_ADMIN_PHONE, whatsapp_message(result))
