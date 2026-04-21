"""
scripts/sync_from_source_sheet.py
==================================
Pull April Month Collection data directly from Kiran's Google Sheet
(READ-ONLY — never writes back to the source).

Source: https://docs.google.com/spreadsheets/d/1Vr_fSIOuuKBK4MWF-FVqgAIUPbqun3POszaXYfj-Ea0
Destination: DB (tenants, tenancies, payments, rent_schedule)

Usage:
    python scripts/sync_from_source_sheet.py          # dry run
    python scripts/sync_from_source_sheet.py --write  # commit to DB

After this, run sync_sheet_from_db.py to update the Operations sheet.
"""
import asyncio
import os
import re
import sys
from datetime import date, datetime
from decimal import Decimal

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

import gspread
from google.oauth2.service_account import Credentials

from sqlalchemy import select
from src.database.db_manager import init_engine, get_session
from src.database.models import (
    Tenant, Tenancy, Room, Payment, RentSchedule,
    TenancyStatus, SharingType, StayType, PaymentMode, PaymentFor, RentStatus,
)

# ── Source ────────────────────────────────────────────────────────────────
SOURCE_SHEET_ID = "1Vr_fSIOuuKBK4MWF-FVqgAIUPbqun3POszaXYfj-Ea0"
CREDENTIALS_PATH = "credentials/gsheets_service_account.json"

APRIL = date(2026, 4, 1)

# Column indices (0-based) — matches April Month Collection schema
COL = {
    "room": 0, "name": 1, "gender": 2, "phone": 3, "checkin": 4,
    "booking": 5, "deposit": 6, "maintenance": 7, "day_rent": 8,
    "monthly_rent": 9, "rent_feb": 10, "rent_may": 11, "sharing": 12,
    "paid_date": 13, "comments": 14, "staff": 15, "inout": 16,
    "block": 17, "floor": 18, "apr_status": 19, "mar_balance": 20,
    "apr_cash": 21, "apr_upi": 22, "apr_balance": 23,
    "food": 24, "complaints": 25, "vacation": 26,
}


def pn(val):
    """Parse numeric — empty/text → 0.0, number/numeric-string → float."""
    if val is None or val == "":
        return 0.0
    s = str(val).replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


def norm_phone(raw):
    d = re.sub(r"\D", "", str(raw or ""))
    if d.startswith("91") and len(d) == 12:
        d = d[2:]
    return f"+91{d}" if len(d) == 10 else ""


def norm_gender(raw):
    return "female" if str(raw or "").strip().lower() == "female" else "male"


def norm_sharing(raw):
    s = str(raw or "").strip().lower()
    if "prem" in s: return SharingType.premium
    if "single" in s: return SharingType.single
    if "double" in s: return SharingType.double
    if "triple" in s: return SharingType.triple
    return None


def status_from_inout(raw):
    s = str(raw or "").strip().upper()
    if s == "CHECKIN": return TenancyStatus.active
    if s == "EXIT": return TenancyStatus.exited
    if s == "NO SHOW": return TenancyStatus.no_show
    if s == "CANCELLED": return TenancyStatus.cancelled
    return None


def parse_checkin(raw):
    if not raw:
        return None
    if isinstance(raw, datetime):
        return raw.date()
    s = str(raw).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


async def fetch_sheet():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SOURCE_SHEET_ID)
    ws = sh.worksheet("Long term")
    data = ws.get_all_values()
    return data


async def main(write: bool):
    print(f"Mode: {'WRITE' if write else 'DRY RUN'}")
    print(f"Source: Google Sheet {SOURCE_SHEET_ID}")

    rows = await fetch_sheet()
    print(f"Fetched {len(rows)} rows from Long term tab")
    header = rows[0]
    print(f"Header cols: {len(header)}")

    # Stats
    stats = {"parsed": 0, "skipped": 0, "matched": 0, "created_tenant": 0,
             "created_tenancy": 0, "updated_status": 0, "cash_added": 0, "upi_added": 0}
    missing_rooms = []

    init_engine(os.getenv("DATABASE_URL"))
    async with get_session() as s:
        # Index rooms
        room_rows = (await s.execute(select(Room))).scalars().all()
        by_room = {r.room_number: r for r in room_rows}
        unassigned = by_room.get("UNASSIGNED") or room_rows[0]

        # Index existing tenants by (phone, name_lower)
        tenant_rows = (await s.execute(select(Tenant))).scalars().all()
        tenant_map = {}
        for t in tenant_rows:
            tenant_map[(t.phone, t.name.lower().strip())] = t
            tenant_map.setdefault(("phone_only", t.phone), t)

        # ── 1. Hard-DELETE all April payments (any for_type) + schedules ─
        if write:
            old_pays = (await s.execute(
                select(Payment).where(Payment.period_month == APRIL)
            )).scalars().all()
            for p in old_pays:
                await s.delete(p)
            print(f"Deleted {len(old_pays)} old April payments (all for_types)")

            # Reassign orphan booking payments that got stamped period_month=APRIL
            # going forward: booking payments should have period_month=NULL (not a rent period)

            old_rs = (await s.execute(
                select(RentSchedule).where(RentSchedule.period_month == APRIL)
            )).scalars().all()
            for r in old_rs:
                await s.delete(r)
            print(f"Deleted {len(old_rs)} old April rent_schedule rows")
            await s.flush()

        # ── 2. Process each sheet row ──────────────────────────────────
        for ri, row in enumerate(rows[1:], start=2):
            if len(row) < 17 or not row[COL["name"]].strip():
                continue
            inout = row[COL["inout"]].strip().upper()
            if inout not in ("CHECKIN", "EXIT", "NO SHOW", "CANCELLED"):
                continue
            stats["parsed"] += 1

            name = row[COL["name"]].strip().title()
            phone = norm_phone(row[COL["phone"]])
            if not phone:
                phone = f"NOPHONE_{row[COL['room']]}_{name[:10]}"

            # Room lookup — handle "june"/"May"/numeric/G-prefix
            # "410.0" → "410" (strip ONLY trailing ".0", not all zeros)
            raw_room = re.sub(r'\.0+$', '', str(row[COL["room"]]).strip())
            room = by_room.get(raw_room)
            if not room:
                # Try without leading zeros
                for k, v in by_room.items():
                    if k.lstrip("0") == raw_room.lstrip("0"):
                        room = v
                        break
            if not room:
                room = unassigned
                missing_rooms.append((name, raw_room))

            checkin = parse_checkin(row[COL["checkin"]])
            if not checkin:
                checkin = APRIL

            status = status_from_inout(inout)
            sharing = norm_sharing(row[COL["sharing"]])

            # Find/create tenant (by phone+name, allow shared phones)
            tenant = tenant_map.get((phone, name.lower().strip())) \
                  or tenant_map.get(("phone_only", phone))
            if not tenant and write:
                tenant = Tenant(
                    name=name, phone=phone,
                    gender=norm_gender(row[COL["gender"]]),
                )
                s.add(tenant)
                await s.flush()
                tenant_map[(phone, name.lower().strip())] = tenant
                stats["created_tenant"] += 1

            if not write:
                continue  # dry run — skip DB writes

            # Find/create tenancy (by tenant + room)
            tenancy = (await s.execute(
                select(Tenancy).where(Tenancy.tenant_id == tenant.id)
                .order_by(Tenancy.id.desc())
            )).scalar()
            if not tenancy:
                tenancy = Tenancy(
                    tenant_id=tenant.id, room_id=room.id,
                    stay_type=StayType.monthly,
                    status=status,
                    checkin_date=checkin,
                    sharing_type=sharing,
                    agreed_rent=Decimal(str(pn(row[COL["monthly_rent"]]))),
                    security_deposit=Decimal(str(pn(row[COL["deposit"]]))),
                    booking_amount=Decimal(str(pn(row[COL["booking"]]))),
                    maintenance_fee=Decimal(str(pn(row[COL["maintenance"]]))),
                )
                s.add(tenancy)
                await s.flush()
                stats["created_tenancy"] += 1
            else:
                # Update status, sharing, room
                if tenancy.status != status:
                    tenancy.status = status
                    stats["updated_status"] += 1
                if sharing and tenancy.sharing_type != sharing:
                    tenancy.sharing_type = sharing
                if tenancy.room_id != room.id:
                    tenancy.room_id = room.id
                stats["matched"] += 1

            # ── Rent schedule for April (skip EXIT/CANCELLED) ─────────
            # Dedupe: only insert if no existing April rent_schedule for this tenancy
            if inout in ("CHECKIN", "NO SHOW"):
                existing_rs = (await s.execute(
                    select(RentSchedule).where(
                        RentSchedule.tenancy_id == tenancy.id,
                        RentSchedule.period_month == APRIL,
                    )
                )).scalar()
                if not existing_rs:
                    rent_amt = Decimal(str(pn(row[COL["monthly_rent"]])))
                    rs_status = RentStatus.pending if inout == "CHECKIN" else RentStatus.na
                    s.add(RentSchedule(
                        tenancy_id=tenancy.id,
                        period_month=APRIL,
                        rent_due=rent_amt,
                        maintenance_due=Decimal("0"),
                        status=rs_status,
                        due_date=APRIL,
                        notes=(row[COL["comments"]] or "")[:250] or None,
                    ))

            # ── Cash payment ──────────────────────────────────────────
            cash = pn(row[COL["apr_cash"]])
            if cash > 0:
                s.add(Payment(
                    tenancy_id=tenancy.id,
                    amount=Decimal(str(cash)),
                    payment_date=APRIL,
                    payment_mode=PaymentMode.cash,
                    for_type=PaymentFor.rent,
                    period_month=APRIL,
                    notes="April cash — live sync from source sheet",
                ))
                stats["cash_added"] += 1

            # ── UPI payment ───────────────────────────────────────────
            upi = pn(row[COL["apr_upi"]])
            if upi > 0:
                # Check if description contains chandra
                cash_text = str(row[COL["apr_cash"]] or "")
                bal_text = str(row[COL["apr_balance"]] or "")
                chandra_note = ""
                if "chandra" in cash_text.lower() or "chandra" in bal_text.lower():
                    chandra_note = " | Need to collect from Chandra"
                s.add(Payment(
                    tenancy_id=tenancy.id,
                    amount=Decimal(str(upi)),
                    payment_date=APRIL,
                    payment_mode=PaymentMode.upi,
                    for_type=PaymentFor.rent,
                    period_month=APRIL,
                    notes=f"April UPI — live sync from source sheet{chandra_note}",
                ))
                stats["upi_added"] += 1

        if write:
            await s.commit()

    print("\n=== SYNC SUMMARY ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    if missing_rooms:
        print(f"\nMissing rooms ({len(missing_rooms)}) — routed to UNASSIGNED:")
        for name, room in missing_rooms:
            print(f"  {name} → '{room}'")


if __name__ == "__main__":
    write = "--write" in sys.argv
    asyncio.run(main(write))
