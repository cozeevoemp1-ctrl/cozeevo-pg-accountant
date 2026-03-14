"""
Deduplication audit script for PG Accountant.

Scans for:
  1. Duplicate active tenancies  — same tenant phone + room, both active
  2. Duplicate payments          — same tenancy_id + amount + payment_date (likely double-import)
  3. Orphaned rent_schedule rows — period has no matching active tenancy

Run:
  python -m src.database.dedup_check
  python -m src.database.dedup_check --fix-dry-run   (shows what would be deleted)
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import date
from decimal import Decimal

from dotenv import load_dotenv
from sqlalchemy import select, func, and_, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

load_dotenv()

from src.database.models import (
    Payment, PaymentFor, RentSchedule, Room, Tenant,
    Tenancy, TenancyStatus,
)

DATABASE_URL = os.environ["DATABASE_URL"]

# ── Helpers ───────────────────────────────────────────────────────────────────

SEP = "─" * 60


def _h(title: str):
    print(f"\n{SEP}\n  {title}\n{SEP}")


# ── 1. Duplicate active tenancies ─────────────────────────────────────────────

async def check_duplicate_tenancies(session: AsyncSession) -> list[dict]:
    """
    Find cases where the same tenant has more than one tenancy for the same room.
    Returns list of groups — each group is a list of tenancy rows.
    """
    _h("1. DUPLICATE TENANCIES (same tenant + room)")

    result = await session.execute(
        select(
            Tenant.phone,
            Tenant.name,
            Tenancy.room_id,
            Room.room_number,
            func.count(Tenancy.id).label("cnt"),
        )
        .join(Tenant, Tenant.id == Tenancy.tenant_id)
        .join(Room, Room.id == Tenancy.room_id)
        .group_by(Tenant.phone, Tenant.name, Tenancy.room_id, Room.room_number)
        .having(func.count(Tenancy.id) > 1)
        .order_by(func.count(Tenancy.id).desc())
    )
    groups = result.fetchall()

    if not groups:
        print("  ✓ No duplicate tenancies found.")
        return []

    duplicates = []
    for phone, name, room_id, room_no, cnt in groups:
        # Fetch all tenancies for this tenant+room
        rows = await session.execute(
            select(Tenancy)
            .join(Tenant, Tenant.id == Tenancy.tenant_id)
            .where(Tenant.phone == phone, Tenancy.room_id == room_id)
            .order_by(Tenancy.checkin_date, Tenancy.id)
        )
        tenancies = rows.scalars().all()
        active_ones = [t for t in tenancies if t.status == TenancyStatus.active]

        print(f"\n  Tenant: {name} ({phone})  Room: {room_no}")
        for t in tenancies:
            marker = " ← ACTIVE" if t.status == TenancyStatus.active else ""
            print(f"    ID={t.id:5}  status={t.status.value:10}  checkin={t.checkin_date}  "
                  f"checkout={t.checkout_date or 'still in'}{marker}")

        if len(active_ones) > 1:
            # Keep the oldest (lowest id), mark rest as duplicates
            keep = active_ones[0]
            remove = active_ones[1:]
            print(f"    → KEEP id={keep.id}  |  REMOVE ids={[r.id for r in remove]}")
            duplicates.append({
                "phone": phone, "name": name, "room_id": room_id,
                "keep_id": keep.id,
                "remove_ids": [r.id for r in remove],
            })

    print(f"\n  Total groups with duplicates: {len(groups)}")
    active_dups = sum(1 for d in duplicates if d["remove_ids"])
    print(f"  Groups with MULTIPLE ACTIVE tenancies: {active_dups}")
    return duplicates


# ── 2. Duplicate payments ─────────────────────────────────────────────────────

async def check_duplicate_payments(session: AsyncSession) -> list[dict]:
    """
    Find payments with same (tenancy_id, amount, payment_date, payment_mode).
    These are almost certainly double-imported rows.
    """
    _h("2. DUPLICATE PAYMENTS (same tenancy + amount + date + mode)")

    result = await session.execute(text("""
        SELECT
            tenancy_id,
            amount,
            payment_date,
            payment_mode,
            period_month,
            COUNT(*) as cnt,
            array_agg(id ORDER BY id) as ids
        FROM payments
        WHERE is_void = false
        GROUP BY tenancy_id, amount, payment_date, payment_mode, period_month
        HAVING COUNT(*) > 1
        ORDER BY cnt DESC, tenancy_id
    """))
    rows = result.fetchall()

    if not rows:
        print("  ✓ No duplicate payments found.")
        return []

    duplicates = []
    total_extra_rows = 0
    total_extra_amount = Decimal("0")

    for tenancy_id, amount, pay_date, mode, period, cnt, ids in rows:
        extra = cnt - 1
        total_extra_rows += extra
        total_extra_amount += Decimal(str(amount)) * extra
        keep_id = ids[0]
        void_ids = ids[1:]
        print(f"  tenancy_id={tenancy_id:4}  Rs.{int(amount):>8,}  {pay_date}  "
              f"{mode:6}  period={period}  count={cnt}  void_ids={void_ids}")
        duplicates.append({
            "tenancy_id": tenancy_id, "amount": amount,
            "payment_date": pay_date, "mode": mode,
            "keep_id": keep_id, "void_ids": void_ids,
        })

    print(f"\n  Duplicate payment groups : {len(rows)}")
    print(f"  Extra rows to void       : {total_extra_rows}")
    print(f"  Extra amount double-counted: Rs.{int(total_extra_amount):,}")
    return duplicates


# ── 3. Orphaned rent_schedule rows ────────────────────────────────────────────

async def check_orphaned_schedules(session: AsyncSession):
    """
    Find rent_schedule rows whose tenancy has exited before that period.
    These inflate pending dues incorrectly.
    """
    _h("3. ORPHANED RENT SCHEDULE ROWS (exited tenant, future schedule)")

    result = await session.execute(text("""
        SELECT rs.id, rs.tenancy_id, rs.period_month, rs.status,
               t.status as tenancy_status, t.checkout_date
        FROM rent_schedule rs
        JOIN tenancies t ON t.id = rs.tenancy_id
        WHERE t.status IN ('exited', 'cancelled', 'no_show')
          AND rs.status IN ('pending', 'partial')
        ORDER BY rs.tenancy_id, rs.period_month
        LIMIT 30
    """))
    rows = result.fetchall()

    if not rows:
        print("  ✓ No orphaned schedule rows found.")
        return

    print(f"  {'rs_id':>6}  {'tenancy_id':>10}  {'period':12}  {'rs_status':10}  "
          f"{'tenancy_status':15}  checkout")
    for rs_id, ten_id, period, rs_status, ten_status, checkout in rows:
        print(f"  {rs_id:>6}  {ten_id:>10}  {str(period):12}  {rs_status:10}  "
              f"{ten_status:15}  {checkout}")
    print(f"\n  Total orphaned rows: {len(rows)}{'+ (showing first 30)' if len(rows)==30 else ''}")


# ── 4. Summary ────────────────────────────────────────────────────────────────

async def summary(session: AsyncSession):
    _h("4. OVERALL COUNTS")

    counts = await session.execute(text("""
        SELECT
            (SELECT COUNT(*) FROM tenancies) as total_tenancies,
            (SELECT COUNT(*) FROM tenancies WHERE status='active') as active,
            (SELECT COUNT(*) FROM payments WHERE is_void=false) as payments,
            (SELECT COUNT(*) FROM rent_schedule) as schedules,
            (SELECT SUM(amount) FROM payments
             WHERE is_void=false AND for_type='rent'
               AND period_month='2026-03-01') as march_total,
            (SELECT SUM(amount) FROM payments
             WHERE is_void=false AND for_type='rent'
               AND period_month='2026-03-01' AND payment_mode='cash') as march_cash,
            (SELECT SUM(amount) FROM payments
             WHERE is_void=false AND for_type='rent'
               AND period_month='2026-03-01' AND payment_mode='upi') as march_upi
    """))
    row = counts.fetchone()
    print(f"  Total tenancies      : {row[0]}")
    print(f"  Active tenancies     : {row[1]}")
    print(f"  Payment rows (live)  : {row[2]}")
    print(f"  Rent schedule rows   : {row[3]}")
    print(f"  March 2026 collected : Rs.{int(row[4] or 0):,}")
    print(f"    Cash               : Rs.{int(row[5] or 0):,}")
    print(f"    UPI                : Rs.{int(row[6] or 0):,}")


# ── Main ──────────────────────────────────────────────────────────────────────

async def run_audit():
    engine = create_async_engine(DATABASE_URL, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as session:
        await summary(session)
        dup_tenancies = await check_duplicate_tenancies(session)
        dup_payments  = await check_duplicate_payments(session)
        await check_orphaned_schedules(session)

        print(f"\n{'='*60}")
        print("AUDIT COMPLETE")
        print(f"  Duplicate tenancy groups  : {len(dup_tenancies)}")
        print(f"  Duplicate payment groups  : {len(dup_payments)}")
        print(f"\nRun with --fix to void duplicate payments and")
        print(f"mark duplicate tenancies as 'cancelled'.")
        print(f"{'='*60}\n")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_audit())
