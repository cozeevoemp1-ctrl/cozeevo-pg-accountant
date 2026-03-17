"""
Delta import from Untitled spreadsheet.xlsx → Supabase DB.

Only adds rows that are MISSING from the DB.
Never modifies or deletes existing tenants, tenancies, or payments.

Usage:
    python -m src.database.delta_import                    # dry run (no writes)
    python -m src.database.delta_import --write            # actually insert

Matches on: phone number (primary) → name+room (fallback)
Imports: CHECKIN (active) + NO SHOW rows with a valid room number.
Skips:   EXIT, Cancelled, blank status, room="May", rows with no name.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import openpyxl
from dotenv import load_dotenv
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

load_dotenv()

SPREADSHEET = Path(__file__).parent.parent.parent / "Untitled spreadsheet.xlsx"
DB_URL = os.getenv("DATABASE_URL", "").replace("postgresql://", "postgresql+asyncpg://")

# ── helpers ────────────────────────────────────────────────────────────────────

def _norm_phone(raw) -> str:
    """Normalize phone to 10-digit string. Returns '' if invalid."""
    if raw is None:
        return ""
    s = str(raw).strip()
    # float like 9361245271.0 → "9361245271"
    if s.endswith(".0"):
        s = s[:-2]
    digits = re.sub(r"\D", "", s)
    if digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    if len(digits) == 10 and digits[0] in "6789":
        return digits
    return ""


def _norm_room(raw) -> str:
    """Normalize room number to string. Returns '' for May/blank/invalid."""
    if raw is None:
        return ""
    s = str(raw).strip()
    if s.endswith(".0"):
        s = s[:-2]
    s = s.upper()
    if not s or s in ("MAY", "NONE", "NAN", ""):
        return ""
    return s


def _norm_amount(raw) -> Decimal:
    if raw is None:
        return Decimal("0")
    try:
        return Decimal(str(int(float(str(raw)))))
    except Exception:
        return Decimal("0")


def _norm_food(raw) -> str:
    if not raw:
        return "none"
    s = str(raw).strip().lower()
    if "non" in s:
        return "non-veg"
    if "egg" in s:
        return "egg"
    if "veg" in s:
        return "veg"
    return "none"


def _norm_status(raw) -> str | None:
    """Returns 'active', 'no_show', or None (skip)."""
    if not raw:
        return None
    s = str(raw).strip().upper()
    if s == "CHECKIN":
        return "active"
    if s == "NO SHOW":
        return "no_show"
    return None


def _norm_date(raw) -> date | None:
    if raw is None:
        return None
    if isinstance(raw, (datetime, date)):
        return raw.date() if isinstance(raw, datetime) else raw
    try:
        return datetime.strptime(str(raw).strip(), "%d/%m/%Y").date()
    except Exception:
        return None


# ── read spreadsheet ──────────────────────────────────────────────────────────

def read_spreadsheet() -> list[dict]:
    wb = openpyxl.load_workbook(SPREADSHEET, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    headers = [str(h).strip() if h else "" for h in rows[0]]

    def col(row, name):
        try:
            return row[headers.index(name)]
        except ValueError:
            return None

    records = []
    for i, row in enumerate(rows[1:], start=2):
        status = _norm_status(col(row, "IN/OUT"))
        if not status:
            continue

        room = _norm_room(col(row, "Room No"))
        if not room:
            continue  # no-room no-shows (coming in May etc.) — skip

        name = str(col(row, "Name") or "").strip()
        if not name:
            continue

        records.append({
            "row":        i,
            "name":       name,
            "phone":      _norm_phone(col(row, "Mobile Number")),
            "room":       room,
            "block":      str(col(row, "BLOCK") or "").strip().upper(),
            "checkin":    _norm_date(col(row, "Checkin date")),
            "rent":       _norm_amount(col(row, "Monthly Rent")),
            "deposit":    _norm_amount(col(row, "Security Deposit")),
            "advance":    _norm_amount(col(row, "Booking")),
            "maintenance":_norm_amount(col(row, "Maintence")),
            "food":       _norm_food(col(row, "veg/nonveg/egg")),
            "status":     status,
        })
    return records


# ── import logic ───────────────────────────────────────────────────────────────

async def run_delta(write: bool) -> None:
    from src.database.models import (
        Tenant, Tenancy, TenancyStatus, Room, Property,
        RentSchedule, RentStatus, Payment, PaymentMode, PaymentFor,
    )

    if not DB_URL or DB_URL.endswith("+asyncpg://"):
        print("ERROR: DATABASE_URL not set in .env")
        sys.exit(1)

    engine = create_async_engine(DB_URL, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    records = read_spreadsheet()
    print(f"\nSpreadsheet rows to process: {len(records)}")
    print(f"Mode: {'WRITE' if write else 'DRY RUN (pass --write to actually insert)'}\n")

    skipped = added_tenants = added_tenancies = 0
    skip_reasons: dict[str, int] = {}

    async with Session() as session:
        # Pre-load property map: "THOR" → id, "HULK" → id
        props = (await session.execute(select(Property))).scalars().all()
        prop_map = {}
        for p in props:
            if "THOR" in p.name.upper():
                prop_map["THOR"] = p.id
            elif "HULK" in p.name.upper():
                prop_map["HULK"] = p.id

        for rec in records:
            # ── 1. Resolve property ──
            prop_id = prop_map.get(rec["block"])
            if not prop_id:
                skip_reasons["unknown block"] = skip_reasons.get("unknown block", 0) + 1
                skipped += 1
                continue

            # ── 2. Resolve room ──
            room_row = await session.scalar(
                select(Room).where(
                    Room.property_id == prop_id,
                    Room.room_number.ilike(rec["room"])
                )
            )
            if not room_row:
                skip_reasons[f"room not found: {rec['room']} ({rec['block']})"] = \
                    skip_reasons.get(f"room not found: {rec['room']} ({rec['block']})", 0) + 1
                skipped += 1
                continue

            # ── 3. Resolve or create tenant ──
            tenant = None
            if rec["phone"]:
                tenant = await session.scalar(
                    select(Tenant).where(Tenant.phone == rec["phone"])
                )
            if not tenant:
                # fallback: name match
                tenant = await session.scalar(
                    select(Tenant).where(Tenant.name.ilike(rec["name"]))
                )

            if not tenant:
                tenant = Tenant(name=rec["name"], phone=rec["phone"] or None)
                if write:
                    session.add(tenant)
                    await session.flush()
                added_tenants += 1
                print(f"  [NEW TENANT] {rec['name']} ({rec['phone'] or 'no phone'})")
            else:
                # ── 4. Check if tenancy already exists ──
                existing = await session.scalar(
                    select(Tenancy).where(
                        Tenancy.tenant_id == tenant.id,
                        Tenancy.room_id == room_row.id,
                        Tenancy.status.in_(["active", "no_show"]),
                    )
                )
                if existing:
                    skip_reasons["tenancy exists"] = skip_reasons.get("tenancy exists", 0) + 1
                    skipped += 1
                    continue

            # ── 5. Create tenancy ──
            checkin = rec["checkin"] or date.today()
            status_enum = TenancyStatus.active if rec["status"] == "active" else TenancyStatus.no_show

            tenancy = Tenancy(
                tenant_id        = tenant.id if write else 0,
                room_id          = room_row.id,
                checkin_date     = checkin,
                agreed_rent      = rec["rent"] or Decimal("0"),
                security_deposit = rec["deposit"],
                booking_amount   = rec["advance"],
                maintenance_fee  = rec["maintenance"],
                status           = status_enum,
            )
            if write:
                session.add(tenancy)
                await session.flush()

            added_tenancies += 1
            print(f"  [NEW TENANCY] {rec['name']} -> Room {rec['room']} ({rec['block']}) "
                  f"| {rec['status']} | checkin {checkin} | rent {rec['rent']}")

            if not write:
                continue

            # ── 6. Generate RentSchedule from checkin month to today ──
            today = date.today()
            period = checkin.replace(day=1)
            current = today.replace(day=1)
            while period <= current:
                existing_rs = await session.scalar(
                    select(RentSchedule).where(
                        RentSchedule.tenancy_id == tenancy.id,
                        RentSchedule.period_month == period,
                    )
                )
                if not existing_rs:
                    session.add(RentSchedule(
                        tenancy_id      = tenancy.id,
                        period_month    = period,
                        rent_due        = rec["rent"] or Decimal("0"),
                        maintenance_due = rec["maintenance"],
                        status          = RentStatus.pending,
                        due_date        = period,
                    ))
                # advance to next month
                if period.month == 12:
                    period = date(period.year + 1, 1, 1)
                else:
                    period = date(period.year, period.month + 1, 1)

            # ── 7. Log advance payment ──
            if rec["advance"] > 0:
                session.add(Payment(
                    tenancy_id   = tenancy.id,
                    amount       = rec["advance"],
                    payment_date = checkin,
                    payment_mode = PaymentMode.cash,
                    for_type     = PaymentFor.booking,
                    period_month = checkin.replace(day=1),
                    notes        = "Booking advance — delta import",
                ))

        if write:
            await session.commit()

    print(f"\n{'='*50}")
    print(f"New tenants added  : {added_tenants}")
    print(f"New tenancies added: {added_tenancies}")
    print(f"Skipped            : {skipped}")
    if skip_reasons:
        print("Skip reasons:")
        for reason, count in sorted(skip_reasons.items(), key=lambda x: -x[1]):
            print(f"  {count:4d}  {reason}")
    print(f"{'='*50}")
    if not write:
        print("\nRun with --write to apply these changes.")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Delta import from spreadsheet to DB")
    parser.add_argument("--write", action="store_true", help="Actually insert (default: dry run)")
    args = parser.parse_args()
    await run_delta(write=args.write)


if __name__ == "__main__":
    asyncio.run(main())
else:
    asyncio.run(main.__wrapped__() if hasattr(main, "__wrapped__") else main())
