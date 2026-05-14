"""
Excel → Supabase full import (drop/reload).

Uses scripts/clean_and_load.py as the SINGLE parser (no duplication).
Reads parsed records and writes to DB tables:
  tenants, tenancies, rent_schedule, payments.

Prerequisites:
  - L0 tables (rooms, properties, staff, food_plans) must exist (run seed.py)
  - Run `python -m src.database.wipe_imported --confirm` first to clear L1+L2

Usage:
  python -m src.database.excel_import                 # dry run
  python -m src.database.excel_import --write          # actually import
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

load_dotenv()

# Add project root to path so we can import from scripts/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from scripts.clean_and_load import read_history, sn, clean_num  # noqa: E402 — single parser
from src.database.models import (  # noqa: E402
    Payment, PaymentFor, PaymentMode,
    Property, RentSchedule, RentStatus, Room,
    SharingType, Staff, Tenancy, TenancyStatus, Tenant,
)


def _norm_sharing(raw: str) -> SharingType | None:
    s = str(raw or "").strip().lower()
    if "prem" in s:
        return SharingType.premium
    if "single" in s:
        return SharingType.single
    if "double" in s:
        return SharingType.double
    if "triple" in s:
        return SharingType.triple
    return None

DATABASE_URL = os.environ["DATABASE_URL"]

# ── Month payment config ─────────────────────────────────────────────────────
# Maps parsed record keys → (period, cash_key, upi_key)
MONTH_COLS = [
    ("dec_st", date(2025, 12, 1), None,       None),
    ("jan_st", date(2026,  1, 1), "jan_cash", "jan_upi"),
    ("feb_st", date(2026,  2, 1), "feb_cash", "feb_upi"),
    ("mar_st", date(2026,  3, 1), "mar_cash", "mar_upi"),
]


# ── Comment classification ───────────────────────────────────────────────────

_PERMANENT_SIGNALS = re.compile(
    r"(?:always|agreed|checkout|planned|lease|contract|first.*months|from.*month|company|student|parent)",
    re.I,
)
_MONTHLY_SIGNALS = re.compile(
    r"(?:will pay|by \d+|next week|balance|partial|collected|pending)",
    re.I,
)


def classify_comment(comment: str) -> str:
    """Classify a comment as 'permanent', 'monthly', or 'ambiguous'."""
    if not comment or not comment.strip():
        return "permanent"
    if _PERMANENT_SIGNALS.search(comment):
        return "permanent"
    if _MONTHLY_SIGNALS.search(comment):
        return "monthly"
    return "ambiguous"


# ── DB-specific normalization (not in parser) ────────────────────────────────

def _norm_phone(raw: str) -> str:
    """Normalize phone to +91XXXXXXXXXX for DB storage."""
    if not raw:
        return ""
    digits = re.sub(r'\D', '', raw)
    if digits.startswith('91') and len(digits) == 12:
        digits = digits[2:]
    if len(digits) == 10 and digits[0] in '6789':
        return f"+91{digits}"
    return ""


def _norm_gender(raw: str) -> str:
    return 'female' if str(raw).strip().lower() == 'female' else 'male'


def _norm_food(raw: str) -> str:
    if not raw:
        return ''
    s = str(raw).strip().lower()
    if 'non' in s:
        return 'non-veg'
    if 'egg' in s:
        return 'egg'
    if 'veg' in s:
        return 'veg'
    return ''


def _status_to_enum(status_str: str) -> TenancyStatus:
    return {
        'Active':    TenancyStatus.active,
        'Exited':    TenancyStatus.exited,
        'No-show':   TenancyStatus.no_show,
        'Cancelled': TenancyStatus.cancelled,
    }.get(status_str, TenancyStatus.active)


def _rent_status_to_enum(st: str) -> RentStatus:
    if st == 'PAID':
        return RentStatus.paid
    if st == 'PARTIAL':
        return RentStatus.partial
    if st in ('EXIT', 'EXITED'):
        return RentStatus.exit
    if st in ('NO SHOW', 'CANCELLED'):
        return RentStatus.na
    return RentStatus.pending


def _norm_staff(raw: str) -> str:
    if not raw:
        return ''
    s = str(raw).strip().title()
    if s.lower() == 'lokesh lk':
        return 'Lokesh'
    return s.split()[0]


def _placeholder_phone(room: str, name: str) -> str:
    safe = re.sub(r'[^a-zA-Z0-9]', '', name)[:12]
    return f"NOPHONE_{room}_{safe}"


def _to_dec(val) -> Decimal:
    """Convert float/int to Decimal safely."""
    if not val:
        return Decimal("0")
    try:
        return Decimal(str(int(val)))
    except (ValueError, TypeError):
        return Decimal("0")


# ── Preview notes ─────────────────────────────────────────────────────────────

async def preview_notes():
    """Show classification of all tenant comments for review."""
    import json

    tenants = read_history()
    rows_with_comments = [(i, t) for i, t in enumerate(tenants, 1) if t.get("comment", "").strip()]

    print(f"\n{'Row':>4}  {'Tenant':<20}  {'Comment':<45}  Type")
    print("-" * 95)

    ambiguous = []
    for row_num, t in rows_with_comments:
        comment = t["comment"].strip()
        cls = classify_comment(comment)
        tag = "PERM" if cls == "permanent" else ("MONTH" if cls == "monthly" else "???")
        print(f"{row_num:>4}  {t['name']:<20}  {comment:<45}  {tag}")
        if cls == "ambiguous":
            ambiguous.append({
                "row": row_num,
                "tenant": t["name"],
                "comment": comment,
                "type": "permanent",  # default for user to change
            })

    if ambiguous:
        out_path = Path("data/notes_classification.json")
        out_path.parent.mkdir(exist_ok=True)
        out_path.write_text(json.dumps(ambiguous, indent=2))
        print(f"\n{len(ambiguous)} ambiguous comments need classification.")
        print(f"Edit {out_path} and re-run with --write")
    else:
        print(f"\nAll {len(rows_with_comments)} comments auto-classified. No manual review needed.")


# ── Main import ──────────────────────────────────────────────────────────────

async def run_import(write: bool) -> None:
    url = DATABASE_URL
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(url, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Use the standard parser from clean_and_load.py
    records = read_history()

    active    = sum(1 for r in records if r['status'] == 'Active')
    exited    = sum(1 for r in records if r['status'] == 'Exited')
    noshow    = sum(1 for r in records if r['status'] == 'No-show')
    cancelled = sum(1 for r in records if r['status'] == 'Cancelled')

    print(f"\nHistory rows parsed: {len(records)}")
    print(f"  Active: {active}  Exited: {exited}  No-show: {noshow}  Cancelled: {cancelled}")
    print(f"Mode: {'WRITE' if write else 'DRY RUN (pass --write to actually insert)'}\n")

    stats = {"tenants": 0, "tenancies": 0, "rent_schedule": 0, "payments": 0, "skipped": 0}

    async with Session() as session:
        # Pre-load lookups
        props = {p.name: p for p in (await session.execute(select(Property))).scalars().all()}
        thor = next((p for n, p in props.items() if 'THOR' in n.upper()), None)
        hulk = next((p for n, p in props.items() if 'HULK' in n.upper()), None)
        if not thor or not hulk:
            print("ERROR: properties not found. Run seed.py first.")
            return

        all_rooms = (await session.execute(select(Room))).scalars().all()
        # Room lookup by number (DB building is truth, Excel BLOCK may be wrong)
        room_by_num: dict[str, Room] = {}  # room_number → Room (first match wins)
        for r in all_rooms:
            if r.room_number not in room_by_num:
                room_by_num[r.room_number] = r

        # Pre-load dummy room for future no-shows (May bookings etc.)
        dummy_room = room_by_num.get("000")
        if not dummy_room:
            dummy_room = Room(
                property_id=thor.id, room_number="000", floor=0,
                room_type="single", max_occupancy=1, active=False,
                notes="Dummy room for future no-shows with no room assigned",
            )
            session.add(dummy_room)
            await session.flush()
            room_by_num["000"] = dummy_room
            print("  + Created UNASSIGNED dummy room for future no-shows")

        all_staff = (await session.execute(select(Staff))).scalars().all()
        staff_map = {s.name: s for s in all_staff}

        tenant_cache: dict[str, Tenant] = {}

        # Pre-load existing payments to prevent duplicates on re-run.
        # Key: (tenancy_id, period_month_str, for_type_str, payment_mode_str) -> total_amount
        from sqlalchemy import text as _sql_text
        _ep_rows = (await session.execute(_sql_text(
            "SELECT tenancy_id, period_month::text, for_type::text, payment_mode::text, "
            "SUM(amount) as total "
            "FROM payments WHERE is_void = false "
            "GROUP BY tenancy_id, period_month, for_type, payment_mode"
        ))).all()
        existing_pmt_totals: dict[tuple, float] = {}
        for _r in _ep_rows:
            _k = (_r.tenancy_id, str(_r.period_month), str(_r.for_type), str(_r.payment_mode))
            existing_pmt_totals[_k] = float(_r.total)

        for rec in records:
            # 1. Normalize room number (handle edge cases)
            room_num = rec['room']
            if not room_num:
                room_num = "000"
                print(f"  WARN: no room for {rec['name']} — assigning UNASSIGNED")

            # Edge case: "May" = future no-show, no room assigned
            if room_num.upper() == 'MAY':
                room_num = "000"

            # Edge case: "617/416" or "617/621" → use first room number
            if '/' in room_num:
                room_num = room_num.split('/')[0].strip()

            # 2. Resolve room — DB building is truth, ignore Excel BLOCK
            #    NEVER skip a tenant. If room not found, assign UNASSIGNED.
            room = room_by_num.get(room_num)
            if not room:
                print(f"  WARN: room {room_num} not in DB — {rec['name']} → UNASSIGNED")
                room = room_by_num["000"]

            # 3. Resolve or create tenant (dedup by phone+name)
            #    Two people can share a phone (roommates/family) — use both as key
            phone = _norm_phone(rec['phone'])
            if not phone:
                phone = _placeholder_phone(room_num, rec['name'])
            norm_name = rec['name'].strip().title()
            cache_key = f"{phone}|{norm_name}"

            tenant = tenant_cache.get(cache_key)
            if not tenant and write:
                existing = await session.scalar(
                    select(Tenant).where(Tenant.phone == phone, Tenant.name == norm_name)
                )
                if existing:
                    tenant = existing
                else:
                    # Partners/family in same room can share phone — DB allows duplicate phones
                    # if (phone, name) is unique. Drop the unique-on-phone-only constraint.
                    tenant = Tenant(
                        name=norm_name,
                        phone=phone,
                        gender=_norm_gender(rec['gender']),
                        food_preference=_norm_food(rec.get('food', '')) or None,
                    )
                    session.add(tenant)
                    await session.flush()
                    stats["tenants"] += 1
                tenant_cache[cache_key] = tenant
            elif not tenant:
                stats["tenants"] += 1
                continue  # dry run — skip DB writes

            # 4. Checkin date — NEVER skip, use fallback if missing
            checkin = rec['checkin']
            if not checkin:
                if rec['status'] == 'No-show':
                    checkin = date(2025, 12, 1)
                else:
                    checkin = date(2026, 1, 1)  # fallback — flag for review
                    print(f"  WARN: no checkin date for {rec['name']} — using 2026-01-01 fallback")

            # 5. Staff
            staff_name = _norm_staff(rec['staff'])
            staff_obj = staff_map.get(staff_name)

            # 6. Classify comment
            comment = rec.get('comment') or ""
            # Load overrides if available
            classification_path = Path("data/notes_classification.json")
            overrides = {}
            if classification_path.exists():
                import json as _json
                for entry in _json.loads(classification_path.read_text()):
                    overrides[entry["tenant"]] = entry["type"]

            cls = overrides.get(rec["name"], classify_comment(comment))
            monthly_note = None
            if cls == "monthly":
                tenancy_notes = None
                monthly_note = comment
            else:
                tenancy_notes = comment or None
                monthly_note = None

            # Check for existing tenancy (dedup by tenant+room)
            existing_tenancy = await session.scalar(
                select(Tenancy).where(
                    Tenancy.tenant_id == tenant.id,
                    Tenancy.room_id == room.id,
                )
            )
            if existing_tenancy:
                # Already exists — skip, don't create duplicate
                continue

            # Create tenancy
            tenancy = Tenancy(
                tenant_id=tenant.id,
                room_id=room.id,
                checkin_date=checkin,
                agreed_rent=_to_dec(rec['current_rent']),
                security_deposit=_to_dec(rec['deposit']),
                booking_amount=_to_dec(rec['booking']),
                maintenance_fee=_to_dec(rec['maintenance']),
                sharing_type=_norm_sharing(rec.get('sharing', '')),
                status=_status_to_enum(rec['status']),
                assigned_staff_id=staff_obj.id if staff_obj else None,
                notes=tenancy_notes,
            )
            session.add(tenancy)
            await session.flush()
            stats["tenancies"] += 1

            # 7. Rent schedule + payments per month
            for st_key, period, cash_key, upi_key in MONTH_COLS:
                st_val = rec.get(st_key, '')

                # Check for payments even if rent status is blank
                has_cash = False
                has_upi = False
                if cash_key:
                    cv, _, _, _ = clean_num(rec.get(cash_key, 0))
                    has_cash = cv > 0
                if upi_key:
                    uv, _, _, _ = clean_num(rec.get(upi_key, 0))
                    has_upi = uv > 0

                if not st_val and not has_cash and not has_upi:
                    continue

                # Rent for this period (use revision columns from parser)
                if period >= date(2026, 5, 1) and rec.get('rent_may', 0) > 0:
                    period_rent = rec['rent_may']
                elif period >= date(2026, 2, 1) and rec.get('rent_feb', 0) > 0:
                    period_rent = rec['rent_feb']
                else:
                    period_rent = rec.get('rent_monthly', 0) or rec['current_rent']

                # Rent schedule (only if status exists)
                if st_val:
                    rent_due_val = _to_dec(period_rent)
                    # First (check-in) month bundles security deposit per business rule
                    if tenancy.checkin_date and period == tenancy.checkin_date.replace(day=1):
                        rent_due_val += Decimal(str(tenancy.security_deposit or 0))
                    session.add(RentSchedule(
                        tenancy_id=tenancy.id,
                        period_month=period,
                        rent_due=rent_due_val,
                        maintenance_due=Decimal("0"),
                        status=_rent_status_to_enum(st_val),
                        due_date=period,
                    ))
                    stats["rent_schedule"] += 1

                # Cash payment (use clean_num to match Sheet parsing exactly)
                if cash_key:
                    cash_val, _, _, _ = clean_num(rec.get(cash_key, 0))
                    if cash_val > 0:
                        _ck = (tenancy.id, str(period), "rent", "cash")
                        if existing_pmt_totals.get(_ck, 0.0) < cash_val:
                            session.add(Payment(
                                tenancy_id=tenancy.id,
                                amount=_to_dec(cash_val - existing_pmt_totals.get(_ck, 0.0)),
                                payment_date=period,
                                payment_mode=PaymentMode.cash,
                                for_type=PaymentFor.rent,
                                period_month=period,
                                notes="Imported from Excel",
                            ))
                            stats["payments"] += 1

                # UPI payment (use clean_num to match Sheet parsing exactly)
                if upi_key:
                    upi_val, _, _, _ = clean_num(rec.get(upi_key, 0))
                    if upi_val > 0:
                        _uk = (tenancy.id, str(period), "rent", "upi")
                        if existing_pmt_totals.get(_uk, 0.0) < upi_val:
                            session.add(Payment(
                                tenancy_id=tenancy.id,
                                amount=_to_dec(upi_val - existing_pmt_totals.get(_uk, 0.0)),
                                payment_date=period,
                                payment_mode=PaymentMode.upi,
                                for_type=PaymentFor.rent,
                                period_month=period,
                                notes="Imported from Excel",
                            ))
                            stats["payments"] += 1

            # Apply monthly-classified comment to most recent rent_schedule
            if monthly_note:
                last_rs = await session.scalar(
                    select(RentSchedule).where(
                        RentSchedule.tenancy_id == tenancy.id,
                    ).order_by(RentSchedule.period_month.desc()).limit(1)
                )
                if last_rs:
                    last_rs.notes = monthly_note

            # 8. Deposit payment
            # Excel has no cash/UPI column for deposits — default to UPI.
            if rec['deposit'] > 0:
                _dk = (tenancy.id, "None", "deposit", "upi")
                if existing_pmt_totals.get(_dk, 0.0) < rec['deposit']:
                    session.add(Payment(
                        tenancy_id=tenancy.id,
                        amount=_to_dec(rec['deposit']),
                        payment_date=checkin,
                        payment_mode=PaymentMode.upi,
                        for_type=PaymentFor.deposit,
                        period_month=None,
                        notes="Security deposit — imported from Excel",
                    ))
                    stats["payments"] += 1

            # 9. Booking advance
            # Excel has no cash/UPI column for bookings — default to UPI.
            if rec['booking'] > 0:
                _bk = (tenancy.id, "None", "booking", "upi")
                if existing_pmt_totals.get(_bk, 0.0) < rec['booking']:
                    session.add(Payment(
                        tenancy_id=tenancy.id,
                        amount=_to_dec(rec['booking']),
                        payment_date=checkin,
                        payment_mode=PaymentMode.upi,
                        for_type=PaymentFor.booking,
                        period_month=None,
                        notes="Booking advance — imported from Excel",
                    ))
                stats["payments"] += 1

        if write:
            await session.commit()

    await engine.dispose()

    print("\n" + "=" * 60)
    print("IMPORT SUMMARY")
    print("=" * 60)
    print(f"  Tenants created    : {stats['tenants']}")
    print(f"  Tenancies created  : {stats['tenancies']}")
    print(f"  Rent schedule rows : {stats['rent_schedule']}")
    print(f"  Payment rows       : {stats['payments']}")
    print(f"  Skipped            : {stats['skipped']}")
    print("=" * 60)

    if not write:
        print("\nDRY RUN — nothing written. Re-run with --write to import.")
    else:
        print("\nIMPORT COMPLETE. Run verification next.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Excel -> DB full import (drop/reload)")
    parser.add_argument("--write", action="store_true", help="Actually write (default: dry run)")
    parser.add_argument("--preview-notes", action="store_true", help="Preview comment classification")
    args = parser.parse_args()
    if args.preview_notes:
        asyncio.run(preview_notes())
    else:
        asyncio.run(run_import(write=args.write))
