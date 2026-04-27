"""
scripts/fix_april_dues.py
=========================
One-time script: set April 2026 balances to EXACTLY what's in Kiran's
"april dues .xlsx" file.

For each person:
  - In Excel with balance > 0 → set DB balance to match via adjustment field
  - In DB with balance > 0 but NOT in Excel → zero out via adjustment field
  - No rent_schedule in DB but Excel says they owe → create schedule

All touched rows get adjustment_note = "MANUAL_LOCK" so no formula ever
overwrites them.

Usage:
    python scripts/fix_april_dues.py          # dry run
    python scripts/fix_april_dues.py --write  # commit to DB
"""
import asyncio
import os
import re
import sys
from datetime import date
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

sys.stdout.reconfigure(encoding="utf-8")

import openpyxl
from sqlalchemy import select, func
from src.database.db_manager import init_engine, get_session
from src.database.models import (
    Tenant, Tenancy, Room, Payment, RentSchedule,
    TenancyStatus, StayType, PaymentFor, RentStatus,
)

APRIL = date(2026, 4, 1)
EXCEL_PATH = "april dues .xlsx"

COL_ROOM    = 0
COL_NAME    = 1
COL_PHONE   = 3
COL_BALANCE = 23   # April Balance


def norm_name(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def norm_room(s) -> str:
    raw = re.sub(r"\.0+$", "", str(s or "").strip())
    return raw.upper().lstrip("0") or raw


def norm_phone(raw) -> str:
    d = re.sub(r"\D", "", str(raw or ""))
    if d.startswith("91") and len(d) == 12:
        d = d[2:]
    return f"+91{d}" if len(d) == 10 else ""


def pn(val) -> float:
    s = str(val or "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


def load_excel_dues() -> dict:
    """Returns {(room_norm, name_norm): target_balance} for rows with balance > 0."""
    wb = openpyxl.load_workbook(EXCEL_PATH)
    ws = wb.active
    dues = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        balance = pn(row[COL_BALANCE])
        if balance <= 0:
            continue
        room = norm_room(row[COL_ROOM])
        name = norm_name(row[COL_NAME])
        phone = norm_phone(row[COL_PHONE])
        if not name:
            continue
        dues[(room, name)] = {"balance": Decimal(str(int(balance))), "phone": phone}
    return dues


async def main(write: bool):
    print(f"Mode: {'WRITE' if write else 'DRY RUN'}")
    excel_dues = load_excel_dues()
    print(f"Excel: {len(excel_dues)} people with dues\n")

    init_engine(os.getenv("DATABASE_URL"))

    stats = {"zeroed": 0, "adjusted": 0, "created": 0, "already_correct": 0}
    actions = []

    async with get_session() as session:
        # Load all April rent_schedule rows with tenancy/tenant/room joins
        rs_rows = (await session.execute(
            select(RentSchedule, Tenancy, Tenant, Room)
            .join(Tenancy, Tenancy.id == RentSchedule.tenancy_id)
            .join(Tenant, Tenant.id == Tenancy.tenant_id)
            .join(Room, Room.id == Tenancy.room_id)
            .where(RentSchedule.period_month == APRIL)
        )).all()

        # Build lookup: (room_norm, name_norm) → (rs, tenancy, tenant, room)
        db_map = {}
        for rs, tenancy, tenant, room in rs_rows:
            key = (norm_room(room.room_number), norm_name(tenant.name))
            db_map[key] = (rs, tenancy, tenant, room)

        # Also build phone→tenancy map for fallback matching
        phone_tenancy_map = {}
        all_tenancies = (await session.execute(
            select(Tenancy, Tenant, Room)
            .join(Tenant, Tenant.id == Tenancy.tenant_id)
            .join(Room, Room.id == Tenancy.room_id)
            .where(Tenancy.status.in_([TenancyStatus.active, TenancyStatus.no_show]))
        )).all()
        for tenancy, tenant, room in all_tenancies:
            if tenant.phone:
                phone_tenancy_map[tenant.phone] = (tenancy, tenant, room)

        # ── STEP 1: Fix everyone in Excel ──────────────────────────────────
        for (room_key, name_key), info in excel_dues.items():
            target = info["balance"]
            phone = info["phone"]

            rs_data = db_map.get((room_key, name_key))

            if rs_data:
                rs, tenancy, tenant, room = rs_data
                # Compute current paid amount for April rent
                paid = await session.scalar(
                    select(func.coalesce(func.sum(Payment.amount), 0))
                    .where(
                        Payment.tenancy_id == tenancy.id,
                        Payment.period_month == APRIL,
                        Payment.for_type == PaymentFor.rent,
                        Payment.is_void == False,
                    )
                ) or Decimal("0")

                # effective_balance = rent_due + adjustment - paid
                # We want: rent_due + new_adjustment - paid = target
                # => new_adjustment = target + paid - rent_due
                rent_due = rs.rent_due or Decimal("0")
                new_adj = target + paid - rent_due
                current_adj = rs.adjustment or Decimal("0")
                current_balance = rent_due + current_adj - paid

                if current_balance == target and rs.adjustment_note == "MANUAL_LOCK":
                    stats["already_correct"] += 1
                    continue

                actions.append(
                    f"  {'SET' if current_balance != target else 'LOCK'} "
                    f"Room {room.room_number} {tenant.name}: "
                    f"balance {int(current_balance)} → {int(target)}"
                )
                if write:
                    rs_obj = await session.get(RentSchedule, rs.id)
                    rs_obj.adjustment = new_adj
                    rs_obj.adjustment_note = "MANUAL_LOCK"
                    if rs_obj.status == RentStatus.na:
                        rs_obj.status = RentStatus.partial if paid > 0 else RentStatus.pending
                stats["adjusted"] += 1

            else:
                # No rent_schedule in DB — try phone fallback
                tenancy_data = phone_tenancy_map.get(phone)
                if not tenancy_data:
                    actions.append(f"  SKIP (not found) Room {room_key} {name_key} — target Rs.{int(target)}")
                    continue

                tenancy, tenant, room = tenancy_data
                # Check again with actual name
                paid = await session.scalar(
                    select(func.coalesce(func.sum(Payment.amount), 0))
                    .where(
                        Payment.tenancy_id == tenancy.id,
                        Payment.period_month == APRIL,
                        Payment.for_type == PaymentFor.rent,
                        Payment.is_void == False,
                    )
                ) or Decimal("0")

                actions.append(
                    f"  CREATE rent_schedule Room {room.room_number} {tenant.name} "
                    f"(matched by phone) — dues Rs.{int(target)}"
                )
                if write:
                    session.add(RentSchedule(
                        tenancy_id=tenancy.id,
                        period_month=APRIL,
                        rent_due=target,
                        maintenance_due=Decimal("0"),
                        status=RentStatus.partial if paid > 0 else RentStatus.pending,
                        due_date=APRIL,
                        adjustment=Decimal("0"),
                        adjustment_note="MANUAL_LOCK",
                    ))
                stats["created"] += 1

        # ── STEP 2: Zero out everyone in DB with balance > 0 but NOT in Excel ──
        for (room_key, name_key), (rs, tenancy, tenant, room) in db_map.items():
            if (room_key, name_key) in excel_dues:
                continue  # already handled above

            paid = await session.scalar(
                select(func.coalesce(func.sum(Payment.amount), 0))
                .where(
                    Payment.tenancy_id == tenancy.id,
                    Payment.period_month == APRIL,
                    Payment.for_type == PaymentFor.rent,
                    Payment.is_void == False,
                )
            ) or Decimal("0")

            rent_due = rs.rent_due or Decimal("0")
            current_adj = rs.adjustment or Decimal("0")
            current_balance = rent_due + current_adj - paid

            if current_balance <= 0:
                # Already zero or credit — just lock it
                if rs.adjustment_note != "MANUAL_LOCK":
                    if write:
                        rs_obj = await session.get(RentSchedule, rs.id)
                        rs_obj.adjustment_note = "MANUAL_LOCK"
                continue

            # Zero out
            new_adj = paid - rent_due  # so effective_due = paid, balance = 0
            actions.append(
                f"  ZERO Room {room.room_number} {tenant.name}: "
                f"balance {int(current_balance)} → 0"
            )
            if write:
                rs_obj = await session.get(RentSchedule, rs.id)
                rs_obj.adjustment = new_adj
                rs_obj.adjustment_note = "MANUAL_LOCK"
                rs_obj.status = RentStatus.paid
            stats["zeroed"] += 1

        if write:
            await session.commit()
            print("Committed to DB.")

    print(f"\nActions ({len(actions)}):")
    for a in actions:
        print(a)

    print(f"\n=== SUMMARY ===")
    print(f"  Adjusted to Excel balance: {stats['adjusted']}")
    print(f"  Zeroed out:                {stats['zeroed']}")
    print(f"  Created (from phone match):{stats['created']}")
    print(f"  Already correct:           {stats['already_correct']}")


if __name__ == "__main__":
    write = "--write" in sys.argv
    asyncio.run(main(write))
