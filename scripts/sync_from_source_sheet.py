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
        # SAFETY: only April. Earlier history (incl. March settlements
        # inserted by settle_march_dues.py) MUST stay intact. A previous
        # version of this script accidentally voided 116 March settlement
        # payments via "sheet-reload" tag — never again.
        if write:
            old_pays = (await s.execute(
                select(Payment).where(Payment.period_month == APRIL)
            )).scalars().all()
            for p in old_pays:
                if p.period_month and p.period_month < APRIL:
                    raise RuntimeError(
                        f"REFUSING to delete payment id={p.id} period={p.period_month} "
                        f"— sync_from_source must never touch pre-April rows."
                    )
                await s.delete(p)
            print(f"Deleted {len(old_pays)} old April payments (all for_types)")

            # Reassign orphan booking payments that got stamped period_month=APRIL
            # going forward: booking payments should have period_month=NULL (not a rent period)

            old_rs = (await s.execute(
                select(RentSchedule).where(RentSchedule.period_month == APRIL)
            )).scalars().all()
            deleted_rs = 0
            for r in old_rs:
                if r.adjustment_note == "MANUAL_LOCK":
                    continue  # manually zeroed balance — do not overwrite
                await s.delete(r)
                deleted_rs += 1
            print(f"Deleted {deleted_rs} old April rent_schedule rows (skipped MANUAL_LOCK entries)")
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

            # Find/create tenant (by phone+name). Do NOT fall back to
            # phone-only — two people can share a phone (roommates on one SIM)
            # and we need separate Tenants so their payments don't merge.
            tenant = tenant_map.get((phone, name.lower().strip()))
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
                # Update status, sharing, room, and money fields. Source is
                # truth for deposit/maintenance/booking — older bot actions
                # might have left these stale, so overwrite from source.
                if tenancy.status != status:
                    tenancy.status = status
                    stats["updated_status"] += 1
                    # If source says the tenant is currently checked in, any
                    # stale checkout_date from a prior "absconded" or voided
                    # exit must go — otherwise bed counts under-report.
                    if status == TenancyStatus.active and tenancy.checkout_date:
                        tenancy.checkout_date = None
                if sharing and tenancy.sharing_type != sharing:
                    tenancy.sharing_type = sharing
                if tenancy.room_id != room.id:
                    tenancy.room_id = room.id
                src_dep = Decimal(str(pn(row[COL["deposit"]])))
                src_maint = Decimal(str(pn(row[COL["maintenance"]])))
                src_book = Decimal(str(pn(row[COL["booking"]])))
                if (tenancy.security_deposit or Decimal("0")) != src_dep:
                    tenancy.security_deposit = src_dep
                    stats["updated_deposit"] = stats.get("updated_deposit", 0) + 1
                if (tenancy.maintenance_fee or Decimal("0")) != src_maint:
                    tenancy.maintenance_fee = src_maint
                    stats["updated_maintenance"] = stats.get("updated_maintenance", 0) + 1
                if (tenancy.booking_amount or Decimal("0")) != src_book:
                    tenancy.booking_amount = src_book
                    stats["updated_booking"] = stats.get("updated_booking", 0) + 1
                stats["matched"] += 1

            # ── Rent schedule for April (skip EXIT/CANCELLED) ─────────
            # Dedupe: only insert if no existing April rent_schedule for this tenancy
            # ── Parse comments for expected_checkout + notice_date ────
            # Be careful: a phrase like "jun 5" is an exit date ONLY when
            # the surrounding text actually means "leaving" — NOT when it
            # appears inside a lock-in/agreement clause (e.g. "@ months
            # lockin until jun 5th or 7th"), which is just the earliest
            # date the tenant is contractually free to leave.
            import re as _re
            cmt_raw = (row[COL["comments"]] or "").strip()
            cmt = cmt_raw.lower()
            is_lockin_note = bool(_re.search(r"lock\s*-?\s*in", cmt))

            # Derive lock-in months from the comment regardless ("@" was a
            # corruption of "2" in the source spreadsheet).
            lockin_m = _re.search(r"(?:^|\s)(\d|@)\s*months?\s+lock\s*-?\s*in", cmt)
            if write and lockin_m:
                raw_n = lockin_m.group(1)
                months_n = 2 if raw_n == "@" else int(raw_n)
                if (tenancy.lock_in_months or 0) != months_n:
                    tenancy.lock_in_months = months_n
                    stats["lockin_set"] = stats.get("lockin_set", 0) + 1

            exp_exit = None
            if not is_lockin_note:
                if "july 18" in cmt or "jul 18" in cmt or "july 18th" in cmt:
                    exp_exit = date(2026, 7, 18)
                elif "jun 5" in cmt or "june 5" in cmt or "jun 7" in cmt or "june 7" in cmt:
                    exp_exit = date(2026, 6, 7)
                elif "this month end exit" in cmt or "april end exit" in cmt or "end of april" in cmt:
                    exp_exit = date(2026, 4, 30)
                elif "leave after april" in cmt or "exit after april" in cmt:
                    exp_exit = date(2026, 4, 30)
                elif "may 31" in cmt or "end of may" in cmt:
                    exp_exit = date(2026, 5, 31)
            if write and exp_exit and tenancy.expected_checkout != exp_exit:
                tenancy.expected_checkout = exp_exit
                stats["expected_exit_set"] = stats.get("expected_exit_set", 0) + 1
                if not tenancy.notice_date:
                    tenancy.notice_date = date.today()

            # Only create April RentSchedule if tenant's checkin is on or before
            # April month (not for future May/June check-ins that are parked as
            # no-show with a next-month checkin_date — they don't owe April rent).
            checkin_in_or_before_apr = (checkin and checkin < date(2026, 5, 1))
            if inout in ("CHECKIN", "NO SHOW") and checkin_in_or_before_apr:
                existing_rs = (await s.execute(
                    select(RentSchedule).where(
                        RentSchedule.tenancy_id == tenancy.id,
                        RentSchedule.period_month == APRIL,
                    )
                )).scalar()
                if not existing_rs:
                    from src.services.rent_schedule import first_month_rent_due
                    rent_amt = first_month_rent_due(tenancy, APRIL)
                    rs_status = RentStatus.pending if inout == "CHECKIN" else RentStatus.na
                    s.add(RentSchedule(
                        tenancy_id=tenancy.id,
                        period_month=APRIL,
                        rent_due=rent_amt,
                        maintenance_due=Decimal("0"),
                        status=rs_status,
                        due_date=APRIL,
                        notes=(cmt_raw or None)[:250] if cmt_raw else None,
                    ))

            # ── Helpers for "paid in <month>" pre-payments ────────────
            import re as _re2
            _PREV_MONTH_RE = _re2.compile(
                r"paid\s+in\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)",
                _re2.I,
            )
            _MONTH_LAST_DAY = {
                "jan": date(2026, 1, 31), "feb": date(2026, 2, 28),
                "mar": date(2026, 3, 31), "apr": date(2026, 4, 30),
                "may": date(2026, 5, 31), "jun": date(2026, 6, 30),
                "jul": date(2026, 7, 31), "aug": date(2026, 8, 31),
                "sep": date(2026, 9, 30), "oct": date(2026, 10, 31),
                "nov": date(2026, 11, 30), "dec": date(2026, 12, 31),
            }

            def _maybe_prepayment(cell_text: str, default_mode: PaymentMode):
                """If cell contains 'paid in <month>', return (amount, mode, pay_date, note). Else None."""
                if not cell_text:
                    return None
                m = _PREV_MONTH_RE.search(cell_text)
                if not m:
                    return None
                month_key = m.group(1).lower()[:3]
                pay_dt = _MONTH_LAST_DAY.get(month_key, date(2026, 3, 31))
                # Mode: if the text says "by cash" → cash, else trust the column default
                mode = PaymentMode.cash if "by cash" in cell_text.lower() else default_mode
                amt = Decimal(str(pn(row[COL["monthly_rent"]]) or 0))
                if amt == 0:
                    return None
                note = f"Pre-paid in {month_key.title()} for April rent — source sheet"
                return (amt, mode, pay_dt, note)

            # ── Cash payment ──────────────────────────────────────────
            cash_text = str(row[COL["apr_cash"]] or "")
            cash = pn(cash_text)
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
            else:
                pre = _maybe_prepayment(cash_text, PaymentMode.cash)
                if pre:
                    amt, mode, pd, note = pre
                    s.add(Payment(
                        tenancy_id=tenancy.id, amount=amt, payment_date=pd,
                        payment_mode=mode, for_type=PaymentFor.rent,
                        period_month=APRIL, notes=note,
                    ))
                    stats["prepaid_added"] = stats.get("prepaid_added", 0) + 1

            # ── UPI payment ───────────────────────────────────────────
            upi_text = str(row[COL["apr_upi"]] or "")
            upi = pn(upi_text)
            if upi > 0:
                # Check if description contains chandra
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
            else:
                pre = _maybe_prepayment(upi_text, PaymentMode.upi)
                if pre:
                    amt, mode, pd, note = pre
                    s.add(Payment(
                        tenancy_id=tenancy.id, amount=amt, payment_date=pd,
                        payment_mode=mode, for_type=PaymentFor.rent,
                        period_month=APRIL, notes=note,
                    ))
                    stats["prepaid_added"] = stats.get("prepaid_added", 0) + 1

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
