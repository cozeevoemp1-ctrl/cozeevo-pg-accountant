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
    RentSchedule, RentStatus, Payment, PaymentFor,
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

        # ── 3. Get RENT payments for this month (exclude deposit/booking/maintenance) ──
        payment_map = {}  # tenancy_id -> {cash, upi}
        pay_rows = (await session.execute(
            select(Payment).where(
                Payment.period_month == period,
                Payment.is_void == False,
                Payment.for_type == PaymentFor.rent,
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

        # ── 3b. Compute prev-month outstanding from DB (not sheet) ──
        prev_period = date(year - 1, 12, 1) if month == 1 else date(year, month - 1, 1)
        prev_rs = (await session.execute(
            select(RentSchedule).where(RentSchedule.period_month == prev_period)
        )).scalars().all()
        prev_pays = (await session.execute(
            select(Payment).where(
                Payment.period_month == prev_period,
                Payment.is_void == False,
                Payment.for_type == PaymentFor.rent,
            )
        )).scalars().all()
        prev_due_map = {}  # tenancy_id -> outstanding
        for rs in prev_rs:
            prev_due_map[rs.tenancy_id] = float(rs.rent_due or 0)
        for p in prev_pays:
            if p.tenancy_id in prev_due_map:
                prev_due_map[p.tenancy_id] -= float(p.amount)
        # Keep only positive balances (unpaid amounts carry forward)
        prev_due_map = {tid: max(0, bal) for tid, bal in prev_due_map.items() if bal > 0}

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

            # Rent due = rent only (maintenance never in dues, per memory rule)
            rent_due = int((rs.rent_due or 0) + (rs.adjustment or 0)) if rs else int(tenancy.agreed_rent or 0)
            cash = int(pays["cash"])
            upi = int(pays["upi"])
            total_paid = cash + upi

            # Check existing sheet row for preserved data (notes, notice, entered-by)
            key = (room.room_number, tenant.name.lower())
            existing_row = sheet_lookup.get(key, [])

            # Prev due from DB (previous month's unpaid rent), not from sheet
            prev_due_num = prev_due_map.get(tenancy.id, 0)
            prev_due = int(prev_due_num) if prev_due_num else ""

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
        exit_rows = [r for r in data_rows if r[13] == "EXIT"]

        regular = sum(1 for r in active_rows if r[4] != "premium")
        premium = sum(1 for r in active_rows if r[4] == "premium")
        beds = regular + (premium * 2)

        thor_t = sum(1 for r in active_rows if "THOR" in str(r[3]).upper())
        hulk_t = sum(1 for r in active_rows if "HULK" in str(r[3]).upper())
        thor_prem = sum(1 for r in active_rows if "THOR" in str(r[3]).upper() and r[4] == "premium")
        hulk_prem = sum(1 for r in active_rows if "HULK" in str(r[3]).upper() and r[4] == "premium")
        thor_beds = (thor_t - thor_prem) + (thor_prem * 2)
        hulk_beds = (hulk_t - hulk_prem) + (hulk_prem * 2)

        # Billing and collection — rent only, all rows
        total_rent_due = sum(pn(r[5]) for r in data_rows)
        total_prev_due = sum(pn(r[15]) for r in data_rows)
        total_cash = sum(pn(r[6]) for r in data_rows)
        total_upi = sum(pn(r[7]) for r in data_rows)
        total_collected = total_cash + total_upi
        total_pending = max(0, total_rent_due + total_prev_due - total_collected)

        paid_count = sum(1 for r in data_rows if r[10] == "PAID")
        partial_count = sum(1 for r in data_rows if r[10] == "PARTIAL")
        unpaid_count = sum(1 for r in data_rows if r[10] == "UNPAID")

        # Vacant beds
        total_rev_beds = (await session.execute(
            select(func.sum(Room.max_occupancy)).where(Room.active == True, Room.is_staff_room == False)
        )).scalar() or 0
        from src.database.models import DaywiseStay
        daywise_beds = (await session.execute(
            select(func.count()).select_from(DaywiseStay).where(
                DaywiseStay.checkin_date <= date.today(),
                DaywiseStay.checkout_date >= date.today(),
                DaywiseStay.status.notin_(["EXIT", "CANCELLED"]),
            )
        )).scalar() or 0

        booked_beds = beds + len(noshow_rows) + daywise_beds
        vacant_beds = int(total_rev_beds) - booked_beds
        occ_pct = (beds / int(total_rev_beds) * 100) if total_rev_beds else 0

        def fmt_lakh(n):
            n = float(n)
            return f"{n/100000:.2f}L" if abs(n) >= 100000 else f"{int(n):,}"

        # 4-row labeled card summary: label | metric | metric | metric ...
        summary_row1 = [
            "OCCUPANCY",
            f"Active: {len(active_rows)}",
            f"Beds: {beds} ({regular}+{premium}P)",
            f"No-show: {len(noshow_rows)}",
            f"Vacant: {vacant_beds}/{int(total_rev_beds)}",
            f"Occupancy: {occ_pct:.1f}%",
            "", "", "", "", "", "", "", "", "", "", "",
        ]
        summary_row2 = [
            "BUILDINGS",
            f"THOR: {thor_beds} beds ({thor_t}t)",
            f"HULK: {hulk_beds} beds ({hulk_t}t)",
            f"Exits: {len(exit_rows)}",
            "", "", "", "", "", "", "", "", "", "", "", "", "",
        ]
        summary_row3 = [
            "COLLECTION",
            f"Cash: {fmt_lakh(total_cash)}",
            f"UPI: {fmt_lakh(total_upi)}",
            f"Collected: {fmt_lakh(total_collected)}",
            f"Rent Billed: {fmt_lakh(total_rent_due)}",
            f"Prev Due: {fmt_lakh(total_prev_due)}",
            "", "", "", "", "", "", "", "", "", "", "",
        ]
        summary_row4 = [
            "STATUS",
            f"PAID: {paid_count}",
            f"PARTIAL: {partial_count}",
            f"UNPAID: {unpaid_count}",
            f"Pending: {fmt_lakh(total_pending)}",
            "", "", "", "", "", "", "", "", "", "", "", "",
        ]

        header_row = [
            "Room", "Name", "Phone", "Building", "Sharing", "Rent Due",
            "Cash", "UPI", "Total Paid", "Balance", "Status",
            "Check-in", "Notice Date", "Event", "Notes", "Prev Due", "Entered By",
        ]

        # ── 7. Print summary ──
        print(f"\n=== Summary ===")
        print(f"OCCUPANCY  Active: {len(active_rows)}  Beds: {beds} ({regular}+{premium}P)  No-show: {len(noshow_rows)}  Vacant: {vacant_beds}/{int(total_rev_beds)}  Occ: {occ_pct:.1f}%")
        print(f"BUILDINGS  THOR: {thor_beds}b ({thor_t}t)  HULK: {hulk_beds}b ({hulk_t}t)  Exits: {len(exit_rows)}")
        print(f"COLLECTION Cash: {fmt_lakh(total_cash)}  UPI: {fmt_lakh(total_upi)}  Collected: {fmt_lakh(total_collected)}  Rent Billed: {fmt_lakh(total_rent_due)}  Prev Due: {fmt_lakh(total_prev_due)}")
        print(f"STATUS     PAID: {paid_count}  PARTIAL: {partial_count}  UNPAID: {unpaid_count}  Pending: {fmt_lakh(total_pending)}")

        if not args.write:
            print(f"\n[DRY RUN] Would write {len(data_rows) + 6} rows to '{tab_name}'")
            print("Run with --write to apply.")
        else:
            # ── 8. Write to Sheet ──
            print(f"\nWriting {len(data_rows) + 6} rows to '{tab_name}'...")

            # Row 1: title | Rows 2-5: summary cards | Row 6: header | Rows 7+: data
            title_row = [f"{MONTH_NAMES[month].title()} {year}"] + [""] * 16
            all_rows = [title_row, summary_row1, summary_row2, summary_row3, summary_row4, header_row] + data_rows

            # Pad all rows to 17 columns
            for i, row in enumerate(all_rows):
                while len(row) < 17:
                    all_rows[i] = list(row) + [""]

            # Clear and write
            ws.clear()
            ws.update(range_name="A1", values=all_rows)

            # Format: title bold 14pt; summary rows with color by section; header bold
            try:
                ws.format("A1:Q1", {"textFormat": {"bold": True, "fontSize": 14},
                                     "backgroundColor": {"red": 0.12, "green": 0.18, "blue": 0.35},
                                     "horizontalAlignment": "LEFT"})
                ws.format("A1:Q1", {"textFormat": {"foregroundColor": {"red": 1, "green": 1, "blue": 1}}})
                # Summary section label column A — bold, color-coded
                ws.format("A2:A5", {"textFormat": {"bold": True}})
                ws.format("A2:Q2", {"backgroundColor": {"red": 0.90, "green": 0.96, "blue": 1.00}})  # occupancy - blue
                ws.format("A3:Q3", {"backgroundColor": {"red": 0.95, "green": 0.95, "blue": 0.98}})  # buildings - grey
                ws.format("A4:Q4", {"backgroundColor": {"red": 0.88, "green": 0.98, "blue": 0.88}})  # collection - green
                ws.format("A5:Q5", {"backgroundColor": {"red": 1.00, "green": 0.96, "blue": 0.85}})  # status - amber
                # Header row bold
                ws.format("A6:Q6", {"textFormat": {"bold": True},
                                     "backgroundColor": {"red": 0.20, "green": 0.24, "blue": 0.40},
                                     "horizontalAlignment": "CENTER"})
                ws.format("A6:Q6", {"textFormat": {"foregroundColor": {"red": 1, "green": 1, "blue": 1}}})
                ws.freeze(rows=6)
            except Exception as e:
                print(f"  [warn] formatting failed: {e}")
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
