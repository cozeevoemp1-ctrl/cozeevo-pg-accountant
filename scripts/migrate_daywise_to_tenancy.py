"""
scripts/migrate_daywise_to_tenancy.py
======================================
One-time migration: DaywiseStay → Tenant + Tenancy(stay_type=daily) + Payment.

Usage:
  python scripts/migrate_daywise_to_tenancy.py           # dry run — shows what would change
  python scripts/migrate_daywise_to_tenancy.py --write   # apply to DB

Idempotent: rows with source_file='MIGRATED' are skipped. Safe to re-run.
Rows with no phone are skipped and logged to migration_skipped.txt.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8")
from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from src.database.models import (
    DaywiseStay, Tenant, Tenancy, TenancyStatus, StayType,
    Payment, PaymentMode, PaymentFor, Room,
)

DATABASE_URL = os.environ["DATABASE_URL"]
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)


def _build_tenancy_data(dw: DaywiseStay, tenant_id: int, room_id: int | None) -> dict:
    """Pure function — builds Tenancy kwargs from a DaywiseStay row. Testable."""
    status = TenancyStatus.active if str(dw.status or "").upper() in ("ACTIVE", "CHECKIN") else TenancyStatus.exited
    return {
        "tenant_id": tenant_id,
        "room_id": room_id,
        "stay_type": StayType.daily,
        "status": status,
        "checkin_date": dw.checkin_date,
        "checkout_date": dw.checkout_date,
        "expected_checkout": dw.checkout_date,
        "agreed_rent": dw.daily_rate or Decimal("0"),      # per-day rate
        "booking_amount": dw.booking_amount or Decimal("0"),
        "maintenance_fee": dw.maintenance or Decimal("0"),
        "notes": dw.comments or "",
        "entered_by": "excel_import",
    }


def _build_payment_data(dw: DaywiseStay, tenancy_id: int) -> dict | None:
    """Returns Payment kwargs or None if nothing to record."""
    total = float(dw.total_amount or 0)
    if total <= 0:
        return None
    return {
        "tenancy_id": tenancy_id,
        "amount": dw.total_amount,
        "payment_mode": PaymentMode.cash,   # Excel imports don't track mode — default cash
        "payment_date": dw.payment_date or dw.checkin_date,
        "for_type": PaymentFor.rent,
        "notes": "migrated from daywise_stays",
    }


async def migrate_row(dw: DaywiseStay, session: AsyncSession, dry_run: bool = False) -> str:
    """Migrate one DaywiseStay row. Returns outcome string."""
    if not dw.phone:
        return "skip_no_phone"
    if dw.source_file == "MIGRATED":
        return "skip_already"

    # Find or reuse existing Tenant by phone
    tenant = await session.scalar(select(Tenant).where(Tenant.phone == dw.phone))
    if not tenant:
        if dry_run:
            return "would_create_tenant"
        tenant = Tenant(name=dw.guest_name, phone=dw.phone)
        session.add(tenant)
        await session.flush()

    tenant_id = tenant.id if tenant else 0

    # Find room by room_number
    room = await session.scalar(select(Room).where(Room.room_number == dw.room_number))
    room_id = room.id if room else None

    # Skip if Tenancy for this stay already exists (idempotent)
    existing = await session.scalar(
        select(Tenancy).where(
            Tenancy.tenant_id == tenant_id,
            Tenancy.checkin_date == dw.checkin_date,
            Tenancy.stay_type == StayType.daily,
        )
    )
    if existing:
        if not dry_run:
            dw.source_file = "MIGRATED"
        return "skip_duplicate"

    if dry_run:
        return "would_migrate"

    # Create Tenancy
    tenancy_data = _build_tenancy_data(dw, tenant_id, room_id)
    tenancy = Tenancy(**tenancy_data)
    session.add(tenancy)
    await session.flush()

    # Create Payment if amount > 0
    pay_data = _build_payment_data(dw, tenancy.id)
    if pay_data:
        session.add(Payment(**pay_data))

    # Mark as migrated
    dw.source_file = "MIGRATED"
    return "migrated"


async def main(write: bool) -> None:
    engine = create_async_engine(DATABASE_URL, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    skipped_no_phone = []

    async with Session() as session:
        rows = (await session.execute(
            select(DaywiseStay).order_by(DaywiseStay.checkin_date)
        )).scalars().all()

        print(f"Total DaywiseStay rows: {len(rows)}")
        counts = {"migrated": 0, "skip_no_phone": 0, "skip_already": 0,
                  "skip_duplicate": 0, "would_migrate": 0, "would_create_tenant": 0}

        for dw in rows:
            result = await migrate_row(dw, session, dry_run=not write)
            counts[result] = counts.get(result, 0) + 1
            if result == "skip_no_phone":
                skipped_no_phone.append(f"{dw.guest_name} | room {dw.room_number} | {dw.checkin_date}")
            if write and result == "migrated":
                await session.commit()
                await session.begin()

        if not write:
            print("\n[DRY RUN] No changes written.")

    print("\nResults:")
    for k, v in counts.items():
        if v:
            print(f"  {k}: {v}")

    if skipped_no_phone:
        Path("migration_skipped.txt").write_text("\n".join(skipped_no_phone), encoding="utf-8")
        print(f"\nSkipped (no phone) logged to migration_skipped.txt: {len(skipped_no_phone)} rows")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(write=args.write))
