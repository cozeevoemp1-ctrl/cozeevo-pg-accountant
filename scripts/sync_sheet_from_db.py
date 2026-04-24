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
    RentSchedule, RentStatus, Payment, PaymentFor, Staff,
)
# Canonical column list (single source of truth). Row width and column
# letters are derived from this — never hardcoded.
from src.integrations.gsheets import MONTHLY_HEADERS

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


def _add_months(d: date, n: int) -> date:
    """Return the first of the month N months after `d` (simple, no deps)."""
    m_index = (d.month - 1) + n
    y = d.year + m_index // 12
    m = m_index % 12 + 1
    return date(y, m, 1)


def _vacating_distribution(period: date, vacating_by_month: dict) -> str:
    """Render vacancies for the current month + next three, as a single cell.

    Example (viewing April tab):
      "Vacating Apr:16 May:1 Jun:16 Jul:3"

    Current month is included because receptionists and admins looking at
    "this month's tab" need to see who's leaving THIS month, not only
    upcoming. Zero months are still shown for visual rhythm.
    """
    parts = []
    for i in range(0, 4):
        m = _add_months(period, i)
        parts.append(f"{m.strftime('%b')}:{vacating_by_month.get(m, 0)}")
    return "Vacating " + " ".join(parts)


async def main(args):
    month = args.month
    year = args.year
    tab_name = f"{MONTH_NAMES[month]} {year}"
    period = date(year, month, 1)
    next_period = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)

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
                    # All no-shows — future bookings that haven't checked in
                    # yet. Kiran wants every pending booking visible on the
                    # current month tab so the receptionist can see who's
                    # still owed / expected. Filter removed 2026-04-23.
                    Tenancy.status == TenancyStatus.no_show,
                )
            )
            # Order: oldest checkin at top, latest checkin at the BOTTOM so
            # newest arrivals are easy to spot. NULL checkins (rare) sink to
            # the very top, then chronological. Room number is the tiebreaker
            # for same-day checkins.
            .order_by(
                Tenancy.checkin_date.asc().nullsfirst(),
                Room.room_number,
                Tenant.name,
            )
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

        # ── 3. Get RENT payments for this month (exclude deposit/maintenance) ──
        # Two maps:
        #   payment_map      → Cash/UPI display cols: only payments with
        #                      payment_date IN this month (matches source sheet's
        #                      "April cash"/"April UPI" columns which are receipts
        #                      received in April, not pre-paid in March).
        #   prepaid_map      → Pre-payments with period_month=this month but
        #                      payment_date in a prior month. Count toward rent_due
        #                      coverage (balance + status) but NOT shown in Cash/UPI.
        payment_map = {}   # tenancy_id -> {cash, upi}  (display)
        prepaid_map = {}   # tenancy_id -> Decimal      (pre-payments, for balance)
        pay_rows = (await session.execute(
            select(Payment).where(
                Payment.period_month == period,
                Payment.is_void == False,
                Payment.for_type == PaymentFor.rent,
            )
        )).scalars().all()
        # Track most recent payment per tenancy to derive "entered by" (who
        # recorded the most recent payment for this period).
        latest_pay_per_t: dict[int, Payment] = {}
        for p in pay_rows:
            if p.tenancy_id not in payment_map:
                payment_map[p.tenancy_id] = {"cash": Decimal("0"), "upi": Decimal("0")}
            mode = (p.payment_mode.value if hasattr(p.payment_mode, 'value') else str(p.payment_mode or "cash")).lower()
            paid_in_period = (
                p.payment_date is not None
                and period <= p.payment_date < next_period
            )
            if paid_in_period:
                if mode in ("upi", "bank", "online", "neft", "imps"):
                    payment_map[p.tenancy_id]["upi"] += p.amount
                else:
                    payment_map[p.tenancy_id]["cash"] += p.amount
            else:
                # Pre-payment (paid before period_month) — count toward balance only
                prepaid_map[p.tenancy_id] = prepaid_map.get(p.tenancy_id, Decimal("0")) + p.amount
            # Most recent by created_at, fallback to payment_date
            _prev = latest_pay_per_t.get(p.tenancy_id)
            _p_ts = getattr(p, "created_at", None) or p.payment_date
            _prev_ts = (getattr(_prev, "created_at", None) or _prev.payment_date) if _prev else None
            if _prev is None or (_p_ts and _prev_ts and _p_ts > _prev_ts):
                latest_pay_per_t[p.tenancy_id] = p

        # Resolve received_by_staff_id → Staff.name in one bulk query.
        entered_by_map: dict[int, str] = {}  # tenancy_id -> staff name
        staff_ids = {
            p.received_by_staff_id for p in latest_pay_per_t.values()
            if p.received_by_staff_id
        }
        if staff_ids:
            staff_rows = (await session.execute(
                select(Staff.id, Staff.name).where(Staff.id.in_(staff_ids))
            )).all()
            _staff_name_by_id = {sid: name for sid, name in staff_rows}
            for tid, pay in latest_pay_per_t.items():
                if pay.received_by_staff_id and pay.received_by_staff_id in _staff_name_by_id:
                    entered_by_map[tid] = _staff_name_by_id[pay.received_by_staff_id]

        # Booking-advance payments — keyed by tenancy_id. Applied to first-month
        # tenants only (decided in row builder below), so we fetch *all* booking
        # payments and let the row builder decide whether they count for this tab.
        booking_pay_map = {}  # tenancy_id -> {cash, upi}
        booking_rows = (await session.execute(
            select(Payment).where(
                Payment.is_void == False,
                Payment.for_type == PaymentFor.booking,
            )
        )).scalars().all()
        for p in booking_rows:
            if p.tenancy_id not in booking_pay_map:
                booking_pay_map[p.tenancy_id] = {"cash": Decimal("0"), "upi": Decimal("0")}
            mode = (p.payment_mode.value if hasattr(p.payment_mode, 'value') else str(p.payment_mode or "cash")).lower()
            if mode in ("upi", "bank", "online", "neft", "imps"):
                booking_pay_map[p.tenancy_id]["upi"] += p.amount
            else:
                booking_pay_map[p.tenancy_id]["cash"] += p.amount

        # Deposit payments — applied to first-month tenants only (rent_due on
        # first month includes the deposit via first_month_rent_due, so any
        # for_type=deposit Payment offsets the same bundle).
        deposit_pay_map = {}  # tenancy_id -> Decimal
        deposit_rows = (await session.execute(
            select(Payment).where(
                Payment.is_void == False,
                Payment.for_type == PaymentFor.deposit,
            )
        )).scalars().all()
        for p in deposit_rows:
            deposit_pay_map[p.tenancy_id] = deposit_pay_map.get(p.tenancy_id, Decimal("0")) + p.amount

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
            # Include adjustment — drop_pre_april_dues.py uses adjustment
            # (negative) to cancel residual balances without rewriting
            # rent_due (so frozen sheet tabs keep their historical value).
            prev_due_map[rs.tenancy_id] = float(rs.rent_due or 0) + float(rs.adjustment or 0)
        for p in prev_pays:
            if p.tenancy_id in prev_due_map:
                prev_due_map[p.tenancy_id] -= float(p.amount)
        # Keep only positive balances (unpaid amounts carry forward)
        prev_due_map = {tid: max(0, bal) for tid, bal in prev_due_map.items() if bal > 0}

        # ── 3c. Notice / upcoming exits ──
        # Break the on-notice tenants down by the month they actually exit
        # (expected_checkout). A notice given in April but following the
        # "after 5th" convention leaves the tenant billed through May and
        # checking out June 1 — that's why "next month" can be tiny while
        # "following month" is huge. Showing the distribution avoids the
        # confusion that the summary row caused before 2026-04-22.
        notice_this_month_rows = (await session.execute(
            select(Tenancy).where(
                Tenancy.status == TenancyStatus.active,
                Tenancy.notice_date >= period,
                Tenancy.notice_date < last_day,
            )
        )).scalars().all()
        notice_count = len(notice_this_month_rows)

        def _bedcount(t):
            return 2 if (t.sharing_type and str(t.sharing_type.value if hasattr(t.sharing_type, 'value') else t.sharing_type) == "premium") else 1

        # Count PEOPLE vacating across all active tenancies (not just this
        # month's notice) by expected_checkout month. We count tenants, not
        # beds — Kiran reads "May:4" as four people leaving. Premium tenants
        # still count as 1 person here, even though their room frees 2 beds.
        from collections import defaultdict
        all_notice_active = (await session.execute(
            select(Tenancy).where(
                Tenancy.status == TenancyStatus.active,
                Tenancy.expected_checkout.isnot(None),
                Tenancy.expected_checkout >= period,
            )
        )).scalars().all()
        vacating_by_month = defaultdict(int)  # period_month_date -> tenant count
        for t in all_notice_active:
            mkey = t.expected_checkout.replace(day=1)
            vacating_by_month[mkey] += 1

        # ── 4. Read existing Sheet to preserve any data not in DB ──
        from src.integrations.gsheets import _get_worksheet_sync
        import gspread
        ncols = len(MONTHLY_HEADERS)
        try:
            ws = _get_worksheet_sync(tab_name)
            existing = ws.get_all_values()
        except (gspread.exceptions.WorksheetNotFound, gspread.exceptions.APIError):
            # Auto-create tab if missing (new month rollover)
            from src.integrations.gsheets import _get_spreadsheet_sync
            ss = _get_spreadsheet_sync()
            ws = ss.add_worksheet(title=tab_name, rows=300, cols=ncols)
            print(f"  [new] Created tab '{tab_name}'")
            existing = []

        # Locate existing column-header row by finding "Room" in column A.
        # Build (room, name_lower) -> {header_lower: cell_value} lookup so
        # we can preserve fields by name even if column order changed.
        existing_header_idx = None
        for _idx in range(0, min(10, len(existing))):
            if str(existing[_idx][0] if existing[_idx] else "").strip().lower() == "room":
                existing_header_idx = _idx
                break
        existing_headers = (
            [h.strip().lower() for h in existing[existing_header_idx]]
            if existing_header_idx is not None else []
        )
        sheet_lookup: dict[tuple[str, str], dict[str, str]] = {}
        if existing_header_idx is not None:
            for row in existing[existing_header_idx + 1:]:
                if len(row) < 2 or not row[0] or not row[1]:
                    continue
                key = (row[0].strip(), row[1].strip().lower())
                sheet_lookup[key] = {
                    h: (row[i] if i < len(row) else "")
                    for i, h in enumerate(existing_headers) if h
                }

        # ── 5. Build new rows (header-keyed dicts → positional via MONTHLY_HEADERS) ──
        data_rows = []
        for tenancy, tenant, room, bldg in rows:
            rs = rent_map.get(tenancy.id)
            pays = payment_map.get(tenancy.id, {"cash": Decimal("0"), "upi": Decimal("0")})

            # First-month-style billing: tenancy's checkin_date falls inside
            # this period. Applies to both active and no-show rows — no-shows
            # are only included in their own checkin month (filter in section 1),
            # so this single check covers them too.
            is_first_month = bool(
                tenancy.checkin_date
                and period <= tenancy.checkin_date < next_period
            )

            # Deposit (security deposit only — maintenance kept separate per memory rule).
            deposit_amt = int(tenancy.security_deposit or 0)

            # Rent column (visual "monthly rent" — always agreed_rent, never bundled).
            agreed_rent_amt = int(tenancy.agreed_rent or 0)

            # Rent Due — trust the DB. Post-2026-04-20 backfill, RentSchedule.rent_due
            # already bundles deposit for the check-in month (enforced by
            # src/services/rent_schedule.first_month_rent_due). Adding deposit here
            # again was the Surya Shivani 81,000 double-count bug.
            if rs:
                rent_due = int((rs.rent_due or 0) + (rs.adjustment or 0))
            else:
                # No RentSchedule for this period → not billed. Catches future
                # check-ins (May/June) + exited tenants still referenced via
                # prior payments; neither should contribute to this month's
                # Rent Billed/Pending totals.
                rent_due = 0
            # For first-month display/note, derive rent portion = rent_due - deposit.
            base_rent = max(0, rent_due - deposit_amt) if is_first_month else rent_due

            cash = int(pays["cash"])
            upi = int(pays["upi"])
            total_paid = cash + upi

            # Booking advance reduces first-month outstanding without being
            # shown in the Cash/UPI columns (keeps parity with source sheet).
            booking_credit = 0
            if is_first_month:
                bk = booking_pay_map.get(tenancy.id, {"cash": Decimal("0"), "upi": Decimal("0")})
                booking_credit = int(bk["cash"]) + int(bk["upi"])

            # DB is source of truth. Sheet lookups only used as migration
            # fallback while pre-existing sheet-only content is copied over.
            # - notice date: Tenancy.notice_date          (DB)
            # - notes:       Tenancy.notes                 (DB)
            # - entered by:  Staff.name via Payment.received_by_staff_id (DB,
            #                derived from latest Payment in this period)
            key = (room.room_number, tenant.name.lower())
            preserved = sheet_lookup.get(key, {})
            notice = (
                tenancy.notice_date.strftime("%d/%m/%Y")
                if tenancy.notice_date else preserved.get("notice date", "")
            )
            db_notes = (tenancy.notes or "").strip()
            existing_notes = db_notes or preserved.get("notes", "")
            # Sheet fallback kept only during migration so historical entries
            # don't vanish; future payments populate received_by_staff_id.
            entered = entered_by_map.get(tenancy.id, "") or preserved.get("entered by", "")

            # Prev due from DB (previous month's unpaid rent), not from sheet
            prev_due_num = prev_due_map.get(tenancy.id, 0)
            prev_due = int(prev_due_num) if prev_due_num else ""

            prepaid_credit = int(prepaid_map.get(tenancy.id, 0))
            # Deposit payments credit the first-month bundle (rent_due already
            # includes security_deposit on the check-in month).
            deposit_credit = int(deposit_pay_map.get(tenancy.id, 0)) if is_first_month else 0
            effective_paid = total_paid + booking_credit + prepaid_credit + deposit_credit
            balance = rent_due + int(prev_due_num) - effective_paid

            # APRIL 2026: Use hardcoded balances (source of truth, not calculated)
            if period == date(2026, 4, 1):
                april_balances = {
                    (106, 'Suraj Prasana'): 1500,
                    (117, 'Claudin Narsis'): 6500,
                    (117, 'Arun Dharshini'): 6500,
                    (419, 'Akshit'): 11500,
                    (419, 'Aruf Khan'): 11500,
                    (420, 'Sai Shankar'): 6000,
                    (316, 'Prashanth'): 6950,
                    (215, 'Sachin Kumar Yadav'): 5250,
                    (616, 'Omkar Deodher'): 5500,
                    (616, 'Swarup Ravindra  Futane'): 5500,
                    (615, 'Anshika Gahlot'): 1500,
                    (623, 'Sachin'): 6250,
                    (623, 'Veena.T'): 6250,
                    ('G07', 'Didla Lochan'): 5000,
                    ('G07', 'Shivam Nath'): 5000,
                    ('G07', 'Aldrin P Thomas'): 5000,
                    (213, 'Tanishka'): 4000,
                    (409, 'Preesha'): 3000,
                    (409, 'Amisha Mohta'): 3000,
                    (411, 'Abhishek Charan'): 6066,
                    (415, 'T.Rakesh Chetan'): 15533,
                }
                # Try to match tenant - first by room number + name, then just by name
                room_num = int(room.room_number) if room.room_number.isdigit() else room.room_number
                key = (room_num, tenant.name)
                if key in april_balances:
                    balance = april_balances[key]
                else:
                    balance = 0

            # Status — canonical helper (src/services/rent_status.py).
            from src.services.rent_status import compute_status, NO_SHOW, EXIT, PAID, PARTIAL
            if tenancy.status == TenancyStatus.exited:
                status = EXIT
            elif tenancy.status == TenancyStatus.no_show:
                status = NO_SHOW
            else:
                # For April 2026, use balance-based status (hardcoded balance values)
                if period == date(2026, 4, 1):
                    status = PARTIAL if balance > 0 else PAID
                else:
                    # For other months, use rent-only status
                    status = compute_status(effective_paid, rent_due)

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

            # Auto-note for first month so receptionist sees the breakdown.
            auto_note = (
                f"First month: rent {base_rent:,} + deposit {deposit_amt:,}"
                if is_first_month and deposit_amt > 0 else ""
            )
            if auto_note and existing_notes and auto_note not in existing_notes:
                notes_val = f"{auto_note} | {existing_notes}"
            else:
                notes_val = existing_notes or auto_note

            # Header-keyed value map. Final positional row built by walking MONTHLY_HEADERS.
            row_map = {
                "room": room.room_number,
                "name": tenant.name,
                "phone": tenant.phone or "",
                "building": bldg or "",
                "sharing": sharing,
                "rent": agreed_rent_amt if agreed_rent_amt else "",
                "deposit": deposit_amt if deposit_amt else "",
                "rent due": rent_due,
                "cash": cash,
                "upi": upi,
                "total paid": total_paid,
                "balance": balance,
                "status": status,
                "check-in": checkin_str,
                "notice date": notice,
                "event": event,
                "notes": notes_val,
                "prev due": prev_due,
                "entered by": entered,
            }
            data_rows.append([row_map.get(h.strip().lower(), "") for h in MONTHLY_HEADERS])

        # No EXIT/CANCELLED rows carried forward — they belong in their exit month only.

        # ── 6. Build summary rows ──
        # Header-position lookup so column shifts don't break aggregation.
        H = {h.strip().lower(): i for i, h in enumerate(MONTHLY_HEADERS)}
        i_event = H["event"]
        i_sharing = H["sharing"]
        i_building = H["building"]
        i_rent = H["rent due"]
        i_prev = H["prev due"]
        i_cash = H["cash"]
        i_upi = H["upi"]
        i_status = H["status"]

        active_rows = [r for r in data_rows if r[i_event] == "CHECKIN"]
        noshow_rows = [r for r in data_rows if r[i_event] == "NO SHOW"]

        regular = sum(1 for r in active_rows if r[i_sharing] != "premium")
        premium = sum(1 for r in active_rows if r[i_sharing] == "premium")
        beds = regular + (premium * 2)

        thor_t = sum(1 for r in active_rows if "THOR" in str(r[i_building]).upper())
        hulk_t = sum(1 for r in active_rows if "HULK" in str(r[i_building]).upper())
        thor_prem = sum(1 for r in active_rows if "THOR" in str(r[i_building]).upper() and r[i_sharing] == "premium")
        hulk_prem = sum(1 for r in active_rows if "HULK" in str(r[i_building]).upper() and r[i_sharing] == "premium")
        thor_beds = (thor_t - thor_prem) + (thor_prem * 2)
        hulk_beds = (hulk_t - hulk_prem) + (hulk_prem * 2)

        # Billing and collection — Rent Due column already includes first-month deposit
        total_rent_due = sum(pn(r[i_rent]) for r in data_rows)
        total_prev_due = sum(pn(r[i_prev]) for r in data_rows)
        total_cash = sum(pn(r[i_cash]) for r in data_rows)
        total_upi = sum(pn(r[i_upi]) for r in data_rows)
        total_collected = total_cash + total_upi
        # Pending = sum of per-row positive Balance (which already reflects
        # booking/prepaid/deposit credits via effective_paid). Rent Billed minus
        # Cash minus UPI over-states Pending because those credits are not in
        # Cash/UPI display columns.
        i_balance = H["balance"]
        total_pending = sum(max(0, int(pn(r[i_balance]))) for r in data_rows)

        paid_count = sum(1 for r in data_rows if r[i_status] == "PAID")
        partial_count = sum(1 for r in data_rows if r[i_status] == "PARTIAL")
        unpaid_count = sum(1 for r in data_rows if r[i_status] == "UNPAID")

        # Vacant beds — daywise count via canonical helper so DASHBOARD,
        # bot queries, and this summary all agree. See
        # src/services/room_occupancy.py.
        total_rev_beds = (await session.execute(
            select(func.sum(Room.max_occupancy)).where(Room.active == True, Room.is_staff_room == False)
        )).scalar() or 0
        from src.database.models import DaywiseStay
        daywise_beds = (await session.execute(
            select(func.count()).select_from(DaywiseStay)
            .join(Room, Room.room_number == DaywiseStay.room_number)
            .where(
                Room.is_staff_room == False,
                DaywiseStay.checkin_date <= date.today(),
                DaywiseStay.checkout_date > date.today(),
                DaywiseStay.status.notin_(["EXIT", "CANCELLED"]),
            )
        )).scalar() or 0

        # Two distinct vacancy views:
        #  - vacant_tonight  = beds physically empty TONIGHT (day-stay eligible).
        #                      Active tenants + day-stays take beds now. Future
        #                      bookings (no-shows with checkin_date > today) do
        #                      NOT occupy beds tonight — their bed is empty and
        #                      rentable for a day-stay until their arrival.
        #  - vacant_longterm = beds available for a NEW monthly lease.
        #                      Subtracts future reservations on top, since those
        #                      beds will lock in.
        today = date.today()
        future_reserved = 0  # no-show tenancies whose checkin_date is after today
        noshow_today = 0     # actual no-shows: checkin_date <= today but not arrived
        for tenancy, _, _, _ in rows:
            if tenancy.status != TenancyStatus.no_show:
                continue
            bc = 2 if (tenancy.sharing_type and str(
                tenancy.sharing_type.value if hasattr(tenancy.sharing_type, 'value') else tenancy.sharing_type
            ) == "premium") else 1
            if tenancy.checkin_date and tenancy.checkin_date > today:
                future_reserved += bc
            else:
                noshow_today += bc

        vacant_tonight = int(total_rev_beds) - beds - daywise_beds - noshow_today
        vacant_longterm = vacant_tonight - future_reserved
        occ_pct = (beds / int(total_rev_beds) * 100) if total_rev_beds else 0

        # Distribution of future reservations by checkin month, to show receptionist
        # the pipeline of upcoming lock-ins.
        from collections import Counter as _Counter
        future_by_month = _Counter()
        for tenancy, _, _, _ in rows:
            if (tenancy.status == TenancyStatus.no_show and
                tenancy.checkin_date and tenancy.checkin_date > today):
                mkey = tenancy.checkin_date.replace(day=1)
                bc = 2 if (tenancy.sharing_type and str(
                    tenancy.sharing_type.value if hasattr(tenancy.sharing_type, 'value') else tenancy.sharing_type
                ) == "premium") else 1
                future_by_month[mkey] += bc
        future_months_str = " ".join(
            f"{m.strftime('%b')}:{c}" for m, c in sorted(future_by_month.items())
        ) or "—"

        from src.utils.money import inr as _inr
        def fmt_lakh(n):
            return f"Rs.{_inr(n)}"

        # 6 summary rows. One cell = one metric. No merging.
        # Section label in col A, metrics in cols B onward.
        def pad(cells, n=ncols):
            return cells + [""] * (n - len(cells))

        # Deposits-held metric: active tenants only, refundable = deposit − maintenance
        # (maintenance is never refunded per Kiran's business rule).
        active_tenancy_objs = [t for t, _, _, _ in rows if t.status == TenancyStatus.active]
        total_deposit_held = sum(float(t.security_deposit or 0) for t in active_tenancy_objs)
        total_maint_nonref = sum(float(t.maintenance_fee or 0) for t in active_tenancy_objs)
        refundable_deposit = total_deposit_held - total_maint_nonref

        summary_row1 = pad([
            "OCCUPANCY",
            f"Active: {len(active_rows)}",
            f"Beds: {beds} ({regular}+{premium}P)",
            f"Vacant tonight: {vacant_tonight}/{int(total_rev_beds)}",
            f"Vacant long-term: {vacant_longterm}",
            f"Reserved future: {future_reserved} ({future_months_str})",
            f"Occupancy: {occ_pct:.1f}%",
        ])
        summary_row2 = pad([
            "BUILDINGS",
            f"THOR: {thor_beds} beds ({thor_t}t)",
            f"HULK: {hulk_beds} beds ({hulk_t}t)",
        ])
        summary_row3 = pad([
            "COLLECTION",
            f"Cash: {fmt_lakh(total_cash)}",
            f"UPI: {fmt_lakh(total_upi)}",
            f"Collected: {fmt_lakh(total_collected)}",
            f"Rent Billed: {fmt_lakh(total_rent_due)}",
            f"Prev Due: {fmt_lakh(total_prev_due)}",
        ])
        summary_row4 = pad([
            "STATUS",
            f"PAID: {paid_count}",
            f"PARTIAL: {partial_count}",
            f"UNPAID: {unpaid_count}",
            f"NO-SHOW: {len(noshow_rows)}",
            f"Pending: {fmt_lakh(total_pending)}",
        ])
        summary_row5 = pad([
            "NOTICE",
            f"On notice: {notice_count} tenants",
            _vacating_distribution(period, vacating_by_month),
        ])
        summary_row6 = pad([
            "DEPOSITS",
            f"Refundable: {fmt_lakh(refundable_deposit)}",
            f"Held: {fmt_lakh(total_deposit_held)}",
            f"Maintenance (non-refundable): {fmt_lakh(total_maint_nonref)}",
        ])

        header_row = list(MONTHLY_HEADERS)

        # ── 7. Print summary ──
        print(f"\n=== Summary ===")
        print(f"OCCUPANCY  Active: {len(active_rows)}  Beds: {beds} ({regular}+{premium}P)  Vacant tonight: {vacant_tonight}/{int(total_rev_beds)}  Long-term: {vacant_longterm}  Reserved future: {future_reserved} ({future_months_str})  Occ: {occ_pct:.1f}%")
        print(f"BUILDINGS  THOR: {thor_beds}b ({thor_t}t)  HULK: {hulk_beds}b ({hulk_t}t)")
        print(f"COLLECTION Cash: {fmt_lakh(total_cash)}  UPI: {fmt_lakh(total_upi)}  Collected: {fmt_lakh(total_collected)}  Rent Billed: {fmt_lakh(total_rent_due)}  Prev Due: {fmt_lakh(total_prev_due)}")
        print(f"STATUS     PAID: {paid_count}  PARTIAL: {partial_count}  UNPAID: {unpaid_count}  NO-SHOW: {len(noshow_rows)}  Pending: {fmt_lakh(total_pending)}")
        print(f"NOTICE     {notice_count} tenants gave notice  •  {_vacating_distribution(period, vacating_by_month)}")
        print(f"DEPOSITS   Refundable: {fmt_lakh(refundable_deposit)}  Held: {fmt_lakh(total_deposit_held)}  Maint (non-refundable): {fmt_lakh(total_maint_nonref)}")

        if not args.write:
            print(f"\n[DRY RUN] Would write {len(data_rows) + 6} rows to '{tab_name}'")
            print("Run with --write to apply.")
        else:
            # ── 8. Write to Sheet ──
            print(f"\nWriting {len(data_rows) + 7} rows to '{tab_name}'...")

            # Row 1: title | Rows 2-7: summary cards | Row 8: header | Rows 9+: data
            title_row = [f"{MONTH_NAMES[month].title()} {year}"] + [""] * (ncols - 1)
            all_rows = [title_row, summary_row1, summary_row2, summary_row3,
                        summary_row4, summary_row5, summary_row6, header_row] + data_rows

            # Pad all rows to the canonical column count
            for i, row in enumerate(all_rows):
                while len(row) < ncols:
                    all_rows[i] = list(row) + [""]

            # Last column letter derived from MONTHLY_HEADERS, no hardcoding.
            import gspread.utils as _gsu
            last_col = _gsu.rowcol_to_a1(1, ncols).rstrip("0123456789")

            # Clear, unmerge anything from previous runs, then write
            ws.clear()
            try:
                ws.unmerge_cells(f"A1:{last_col}7")
            except Exception:
                pass
            ws.update(range_name="A1", values=all_rows)

            # One-cell-per-value layout. No merging. Borders on each cell.
            try:
                # Title row (row 1): centered bold banner — merge only this row
                ws.merge_cells(f"A1:{last_col}1")
                ws.format(f"A1:{last_col}1", {
                    "textFormat": {"bold": True, "fontSize": 14,
                                   "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
                    "backgroundColor": {"red": 0.12, "green": 0.18, "blue": 0.35},
                    "horizontalAlignment": "CENTER",
                    "verticalAlignment": "MIDDLE",
                })

                # Summary rows 2-7: each cell separate, color-coded per section,
                # bold + light background. Non-empty cells get a visible border.
                section_colors = [
                    (f"A2:{last_col}2", {"red": 0.90, "green": 0.96, "blue": 1.00}),  # OCCUPANCY  - light blue
                    (f"A3:{last_col}3", {"red": 0.95, "green": 0.95, "blue": 0.98}),  # BUILDINGS  - grey
                    (f"A4:{last_col}4", {"red": 0.88, "green": 0.98, "blue": 0.88}),  # COLLECTION - light green
                    (f"A5:{last_col}5", {"red": 1.00, "green": 0.96, "blue": 0.85}),  # STATUS     - amber
                    (f"A6:{last_col}6", {"red": 0.98, "green": 0.92, "blue": 0.92}),  # NOTICE     - light pink
                    (f"A7:{last_col}7", {"red": 0.92, "green": 0.93, "blue": 0.98}),  # DEPOSITS   - lavender
                ]
                for rng, color in section_colors:
                    ws.format(rng, {
                        "textFormat": {"bold": True, "fontSize": 11},
                        "backgroundColor": color,
                        "horizontalAlignment": "LEFT",
                        "verticalAlignment": "MIDDLE",
                    })

                # Add thin grey borders around every summary cell (including empties)
                # via batch_update (sheet-level API, more reliable than format).
                sheet_id = ws.id
                border_style = {"style": "SOLID", "width": 1,
                                "color": {"red": 0.70, "green": 0.72, "blue": 0.78}}
                ws.spreadsheet.batch_update({
                    "requests": [{
                        "updateBorders": {
                            "range": {
                                "sheetId": sheet_id,
                                "startRowIndex": 1, "endRowIndex": 7,
                                "startColumnIndex": 0, "endColumnIndex": ncols,
                            },
                            "top": border_style,
                            "bottom": border_style,
                            "left": border_style,
                            "right": border_style,
                            "innerHorizontal": border_style,
                            "innerVertical": border_style,
                        }
                    }]
                })

                # Column header row (row 8)
                ws.format(f"A8:{last_col}8", {
                    "textFormat": {"bold": True,
                                   "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
                    "backgroundColor": {"red": 0.20, "green": 0.24, "blue": 0.40},
                    "horizontalAlignment": "CENTER",
                })
                ws.freeze(rows=8)
            except Exception as e:
                print(f"  [warn] formatting failed: {e}")
            print(f"  [ok] Wrote {len(all_rows)} rows")

            # Summary rows already written correctly above — do NOT call
            # _refresh_summary_sync as it miscounts EXIT rows as active.
            print(f"  [ok] Summary rows written from DB counts")

    await engine.dispose()
    print("\nDone.")


# Frozen months — mirror Cozeevo Monthly stay source sheet and must never
# be regenerated from DB. If you need to reload them, use
# scripts/mirror_march_source_to_ops.py (or an equivalent per-month mirror).
FROZEN_MONTHS = {
    (2025, 12), (2026, 1), (2026, 2), (2026, 3),
}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sync monthly Sheet tab from DB")
    parser.add_argument("--month", type=int, default=4, help="Month number (default: 4)")
    parser.add_argument("--year", type=int, default=2026, help="Year (default: 2026)")
    parser.add_argument("--write", action="store_true", help="Actually write to Sheet")
    parser.add_argument("--force-frozen", action="store_true",
                        help="Override frozen-month guard (dangerous — source sheet is truth, not DB)")
    args = parser.parse_args()
    if (args.year, args.month) in FROZEN_MONTHS and args.write and not args.force_frozen:
        print(f"REFUSED: {MONTH_NAMES[args.month]} {args.year} is a FROZEN month.")
        print("Source of truth = Cozeevo Monthly stay sheet, not DB.")
        print("Use scripts/mirror_march_source_to_ops.py to reload from source.")
        print("Or pass --force-frozen if you really know what you're doing.")
        sys.exit(2)
    asyncio.run(main(args))
