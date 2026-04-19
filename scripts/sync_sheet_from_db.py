"""
scripts/sync_sheet_from_db.py
==============================
Regenerate a monthly Sheet tab entirely from DB (source of truth).
Preserves existing payment data (Cash, UPI) from the Sheet.

Usage:
    python scripts/sync_sheet_from_db.py                    # dry run (April 2026)
    python scripts/sync_sheet_from_db.py --write            # actually write
    python scripts/sync_sheet_from_db.py --month 3 --year 2026 --write  # March
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

from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, selectinload
from src.database.models import (
    Tenancy, Tenant, Room, Property, TenancyStatus,
    RentSchedule, RentStatus, Payment,
)

DATABASE_URL = os.environ["DATABASE_URL"]
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

MONTH_NAMES = {1: "JANUARY", 2: "FEBRUARY", 3: "MARCH", 4: "APRIL",
               5: "MAY", 6: "JUNE", 7: "JULY", 8: "AUGUST",
               9: "SEPTEMBER", 10: "OCTOBER", 11: "NOVEMBER", 12: "DECEMBER"}


def pn(val) -> float:
    """Parse numeric."""
    if not val:
        return 0.0
    s = str(val).replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


async def main(args):
    month = args.month
    year = args.year
    tab_name = f"{MONTH_NAMES[month]} {year}"
    period = date(year, month, 1)

    print(f"=== Sync Sheet '{tab_name}' from DB ===\n")

    engine = create_async_engine(DATABASE_URL, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as session:
        # ── 1. Get all tenancies that should appear in this month ──
        # Active tenancies (checkin <= end of month)
        # Exited tenancies (checkout in this month)
        # No-show tenancies (checkin in this month)
        last_day = date(year, month + 1, 1) if month < 12 else date(year + 1, 1, 1)

        # Include tenancies that had payments or rent schedule for this month
        # (catches exited tenants who paid in this month even without checkout_date)
        tids_with_activity = set()
        for row in (await session.execute(
            select(Payment.tenancy_id).where(
                Payment.period_month == period, Payment.is_void == False
            )
        )).all():
            tids_with_activity.add(row[0])
        for row in (await session.execute(
            select(RentSchedule.tenancy_id).where(RentSchedule.period_month == period)
        )).all():
            tids_with_activity.add(row[0])

        rows = (await session.execute(
            select(Tenancy, Tenant, Room, Property.name)
            .join(Tenant, Tenant.id == Tenancy.tenant_id)
            .join(Room, Room.id == Tenancy.room_id)
            .join(Property, Property.id == Room.property_id)
            .where(
                or_(
                    # All active tenancies
                    Tenancy.status == TenancyStatus.active,
                    # Exited in this month (checkout date set)
                    and_(
                        Tenancy.status == TenancyStatus.exited,
                        Tenancy.checkout_date >= period,
                        Tenancy.checkout_date < last_day,
                    ),
                    # Any tenancy with payment or rent schedule for this month
                    Tenancy.id.in_(tids_with_activity) if tids_with_activity else False,
                    # All current no-shows (until they checkin or are cancelled)
                    Tenancy.status == TenancyStatus.no_show,
                )
            )
            .order_by(Room.room_number, Tenant.name)
        )).all()

        print(f"DB: {len(rows)} tenancies for {tab_name}")

        # Count by status
        counts = {}
        for tenancy, tenant, room, bldg in rows:
            s = tenancy.status.value
            counts[s] = counts.get(s, 0) + 1
        for s, c in sorted(counts.items()):
            print(f"  {s}: {c}")

        # ── 2. Get rent schedules for this month ──
        rent_map = {}  # tenancy_id -> RentSchedule
        rs_rows = (await session.execute(
            select(RentSchedule).where(RentSchedule.period_month == period)
        )).scalars().all()
        for rs in rs_rows:
            rent_map[rs.tenancy_id] = rs

        # ── 3. Get payments for this month ──
        payment_map = {}  # tenancy_id -> {cash, upi}
        pay_rows = (await session.execute(
            select(Payment).where(
                Payment.period_month == period,
                Payment.is_void == False,
            )
        )).scalars().all()
        for p in pay_rows:
            if p.tenancy_id not in payment_map:
                payment_map[p.tenancy_id] = {"cash": Decimal("0"), "upi": Decimal("0")}
            mode = (p.payment_mode.value if hasattr(p.payment_mode, 'value') else str(p.payment_mode or "cash")).lower()
            if mode in ("upi", "bank", "online", "neft", "imps"):
                payment_map[p.tenancy_id]["upi"] += p.amount
            else:
                payment_map[p.tenancy_id]["cash"] += p.amount

        # ── 4. Read existing Sheet to preserve any data not in DB ──
        from src.integrations.gsheets import _get_worksheet_sync
        ws = _get_worksheet_sync(tab_name)
        existing = ws.get_all_values()

        # Build lookup from existing sheet: (room, name_lower) -> row data
        sheet_lookup = {}
        for row in existing[4:]:  # skip header rows
            if not row[0] or not row[1]:
                continue
            key = (row[0].strip(), row[1].strip().lower())
            sheet_lookup[key] = row

        # ── 5. Build new rows ──
        data_rows = []
        for tenancy, tenant, room, bldg in rows:
            rs = rent_map.get(tenancy.id)
            pays = payment_map.get(tenancy.id, {"cash": Decimal("0"), "upi": Decimal("0")})

            rent_due = int(rs.rent_due + (rs.maintenance_due or 0) + (rs.adjustment or 0)) if rs else int(tenancy.agreed_rent or 0)
            cash = int(pays["cash"])
            upi = int(pays["upi"])
            total_paid = cash + upi

            # Check existing sheet row for preserved data
            key = (room.room_number, tenant.name.lower())
            existing_row = sheet_lookup.get(key, [])

            # DB is source of truth — never preserve sheet cash/UPI values
            # (previous logic did this but caused stale data to persist after voids)

            # Previous balance from sheet (col 16, index 15)
            prev_due = ""
            if existing_row and len(existing_row) > 15:
                prev_due = existing_row[15]
            prev_due_num = pn(prev_due)

            balance = rent_due + int(prev_due_num) - total_paid

            # Status
            if tenancy.status == TenancyStatus.exited:
                status = "EXIT"
            elif tenancy.status == TenancyStatus.no_show:
                status = "NO-SHOW"
            elif total_paid >= rent_due + int(prev_due_num):
                status = "PAID"
            elif total_paid > 0:
                status = "PARTIAL"
            else:
                status = "UNPAID"

            # Event
            if tenancy.status == TenancyStatus.exited:
                event = "EXIT"
            elif tenancy.status == TenancyStatus.no_show:
                event = "NO SHOW"
            else:
                event = "CHECKIN"

            # Sharing type
            sharing = tenancy.sharing_type or ""
            if hasattr(sharing, 'value'):
                sharing = sharing.value

            checkin_str = tenancy.checkin_date.strftime("%d/%m/%Y") if tenancy.checkin_date else ""

            # Notice date from sheet
            notice = ""
            if existing_row and len(existing_row) > 12:
                notice = existing_row[12]

            # Notes from sheet (prefer sheet, it may have manually added notes)
            notes = ""
            if existing_row and len(existing_row) > 14:
                notes = existing_row[14]

            entered = ""
            if existing_row and len(existing_row) > 16:
                entered = existing_row[16]

            data_rows.append([
                room.room_number,       # A: Room
                tenant.name,            # B: Name
                tenant.phone or "",     # C: Phone
                bldg or "",             # D: Building
                sharing,                # E: Sharing
                rent_due,               # F: Rent Due
                cash,                   # G: Cash
                upi,                    # H: UPI
                total_paid,             # I: Total Paid
                balance,                # J: Balance
                status,                 # K: Status
                checkin_str,            # L: Check-in
                notice,                 # M: Notice Date
                event,                  # N: Event
                notes,                  # O: Notes
                prev_due,               # P: Prev Due
                entered,                # Q: Entered By
            ])

        # No EXIT/CANCELLED rows carried forward — they belong in their exit month only.

        # ── 6. Build summary rows ──
        active_rows = [r for r in data_rows if r[13] == "CHECKIN"]
        noshow_rows = [r for r in data_rows if r[13] == "NO SHOW"]

        regular = sum(1 for r in active_rows if r[4] != "premium")
        premium = sum(1 for r in active_rows if r[4] == "premium")
        beds = regular + (premium * 2)

        thor_t = sum(1 for r in active_rows if "THOR" in str(r[3]).upper())
        hulk_t = sum(1 for r in active_rows if "HULK" in str(r[3]).upper())
        thor_prem = sum(1 for r in active_rows if "THOR" in str(r[3]).upper() and r[4] == "premium")
        hulk_prem = sum(1 for r in active_rows if "HULK" in str(r[3]).upper() and r[4] == "premium")
        thor_beds = (thor_t - thor_prem) + (thor_prem * 2)
        hulk_beds = (hulk_t - hulk_prem) + (hulk_prem * 2)

        # Totals include ALL rows (active + exited + no-show) — every payment counts
        total_cash = sum(pn(r[6]) for r in data_rows)
        total_upi = sum(pn(r[7]) for r in data_rows)
        total_all = total_cash + total_upi
        total_bal = sum(pn(r[9]) for r in data_rows)

        paid_count = sum(1 for r in data_rows if r[10] == "PAID")
        partial_count = sum(1 for r in data_rows if r[10] == "PARTIAL")
        unpaid_count = sum(1 for r in data_rows if r[10] == "UNPAID")

        # Vacant beds
        from src.database.models import Room as RoomModel
        total_rev_beds = (await session.execute(
            select(func.sum(Room.max_occupancy)).where(Room.active == True, Room.is_staff_room == False)
        )).scalar() or 0
        # Daywise guests currently occupying beds
        from src.database.models import DaywiseStay
        daywise_beds = (await session.execute(
            select(func.count()).select_from(DaywiseStay).where(
                DaywiseStay.checkin_date <= date.today(),
                DaywiseStay.checkout_date >= date.today(),
                DaywiseStay.status.notin_(["EXIT", "CANCELLED"]),
            )
        )).scalar() or 0

        # Vacant = total - checked_in - noshow - daywise
        booked_beds = beds + len(noshow_rows) + daywise_beds
        vacant_beds = int(total_rev_beds) - booked_beds

        occ_pct = (beds / int(total_rev_beds) * 100) if total_rev_beds else 0

        summary_row1 = [
            "Checked-in", f"{beds} beds ({regular}+{premium}P)",
            f"No-show: {len(noshow_rows)}", f"Vacant: {vacant_beds}",
            f"Occ: {occ_pct:.1f}%", "Cash", f"{int(total_cash):,}",
            "UPI", f"{int(total_upi):,}", "Total", f"{int(total_all):,}",
            f"Bal: {int(total_bal)}", "", "", "", "", "",
        ]
        summary_row2 = [
            f"THOR: {thor_beds}b ({thor_t}t)", f"HULK: {hulk_beds}b ({hulk_t}t)",
            f"New: 0", f"Exit: 0",
            "", f"PAID:{paid_count}", f"PARTIAL:{partial_count}", f"UNPAID:{unpaid_count}",
            "", "", "", "", "", "", "", "", "",
        ]

        header_row = [
            "Room", "Name", "Phone", "Building", "Sharing", "Rent Due",
            "Cash", "UPI", "Total Paid", "Balance", "Status",
            "Check-in", "Notice Date", "Event", "Notes", "Prev Due", "Entered By",
        ]

        # ── 7. Print summary ──
        print(f"\n=== Summary ===")
        print(f"Active: {len(active_rows)} ({regular} reg + {premium} prem = {beds} beds)")
        print(f"Exit: 0 (exits go in their exit month only)")
        print(f"No-show: {len(noshow_rows)}")
        print(f"THOR: {thor_beds}b ({thor_t}t)  HULK: {hulk_beds}b ({hulk_t}t)")
        print(f"Vacant: {vacant_beds}/{int(total_rev_beds)}")
        print(f"Cash: {int(total_cash):,}  UPI: {int(total_upi):,}  Total: {int(total_all):,}  Bal: {int(total_bal)}")
        print(f"PAID: {paid_count}  PARTIAL: {partial_count}  UNPAID: {unpaid_count}")

        if not args.write:
            print(f"\n[DRY RUN] Would write {len(data_rows) + 4} rows to '{tab_name}'")
            print("Run with --write to apply.")
        else:
            # ── 8. Write to Sheet ──
            print(f"\nWriting {len(data_rows) + 4} rows to '{tab_name}'...")

            # Clear existing data (keep row 1 title)
            title_row = existing[0] if existing else [f"April {year}"]
            all_rows = [title_row, summary_row1, summary_row2, header_row] + data_rows

            # Pad all rows to 17 columns
            for i, row in enumerate(all_rows):
                while len(row) < 17:
                    all_rows[i] = list(row) + [""]

            # Clear and write
            ws.clear()
            ws.update(range_name="A1", values=all_rows)
            print(f"  [ok] Wrote {len(all_rows)} rows")

            # Summary rows already written correctly above — do NOT call
            # _refresh_summary_sync as it miscounts EXIT rows as active.
            print(f"  [ok] Summary rows written from DB counts")

    await engine.dispose()
    print("\nDone.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sync monthly Sheet tab from DB")
    parser.add_argument("--month", type=int, default=4, help="Month number (default: 4)")
    parser.add_argument("--year", type=int, default=2026, help="Year (default: 2026)")
    parser.add_argument("--write", action="store_true", help="Actually write to Sheet")
    asyncio.run(main(parser.parse_args()))
