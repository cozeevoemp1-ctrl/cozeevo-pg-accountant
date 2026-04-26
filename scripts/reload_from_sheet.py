"""
scripts/reload_from_sheet.py
============================
Drop and reload April 2026 + Day Wise data in DB from Google Sheet.
Sheet at 17:02 restored version is treated as source of truth.

Safe guards:
  - Only drops April 2026 RentSchedule + rent Payments (period_month = 2026-04-01)
  - Only drops Tenancy(stay_type=daily) + their Payments
  - Tenant rows (name/phone) are never dropped
  - Dec 2025, Jan/Feb/Mar 2026 untouched
  - All other monthly tenancies untouched

Usage:
    venv/Scripts/python scripts/reload_from_sheet.py           # dry run
    venv/Scripts/python scripts/reload_from_sheet.py --write   # apply
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

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8")
from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, selectinload

from src.database.models import (
    Tenant, Tenancy, TenancyStatus, StayType,
    RentSchedule, RentStatus, Payment, PaymentMode, PaymentFor, Room,
)
from src.integrations.gsheets import _get_worksheet_sync

APRIL = date(2026, 4, 1)
DATABASE_URL = os.environ["DATABASE_URL"]
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)


def _norm_phone(p: str) -> str:
    digits = re.sub(r"\D", "", str(p or ""))
    return digits[-10:] if len(digits) >= 10 else digits


def _parse_num(v) -> float:
    try:
        return float(str(v).replace(",", "").strip() or 0)
    except (ValueError, TypeError):
        return 0.0


def _parse_date(s: str) -> date | None:
    s = str(s or "").strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


# ──────────────────────────────────────────────────────────────────────────────
# APRIL 2026 reload
# ──────────────────────────────────────────────────────────────────────────────

async def reload_april(session: AsyncSession, write: bool) -> dict:
    stats = {"rows": 0, "matched": 0, "no_tenant": 0, "no_tenancy": 0,
             "rs_created": 0, "pay_created": 0, "skipped_noshow": 0}

    ws = _get_worksheet_sync("APRIL 2026")
    all_vals = ws.get_all_values()

    # Find header row (first row where col A == "Room")
    hdr_idx = None
    for i, row in enumerate(all_vals):
        if str(row[0] if row else "").strip().lower() == "room":
            hdr_idx = i
            break
    if hdr_idx is None:
        print("ERROR: Could not find header row in APRIL 2026")
        return stats

    headers = [h.strip().lower() for h in all_vals[hdr_idx]]
    def col(name: str) -> int:
        try:
            return headers.index(name.lower())
        except ValueError:
            return -1

    c_room   = col("room");      c_name   = col("name")
    c_phone  = col("phone");     c_rdue   = col("rent due")
    c_cash   = col("cash");      c_upi    = col("upi")
    c_event  = col("event");     c_checkin = col("check-in")

    data_rows = all_vals[hdr_idx + 1:]
    print(f"APRIL 2026: {len(data_rows)} data rows to process")

    # Build phone → tenant map from DB
    all_tenants = (await session.execute(
        select(Tenant).options(
            selectinload(Tenant.tenancies).selectinload(Tenancy.room)
        )
    )).scalars().all()
    phone_map: dict[str, Tenant] = {}
    name_map: dict[str, Tenant] = {}
    for t in all_tenants:
        if t.phone:
            phone_map[_norm_phone(t.phone)] = t
        name_map[t.name.strip().lower()] = t

    # ── DROP existing April RS + rent Payments ────────────────────────────────
    if write:
        del_pay = await session.execute(
            delete(Payment).where(
                Payment.period_month == APRIL,
                Payment.for_type == PaymentFor.rent,
                Payment.is_void == False,
            )
        )
        del_rs = await session.execute(
            delete(RentSchedule).where(RentSchedule.period_month == APRIL)
        )
        print(f"  Dropped {del_pay.rowcount} April rent payments, {del_rs.rowcount} rent schedules")
    else:
        # Count what would be dropped
        cnt_pay = len((await session.execute(
            select(Payment.id).where(
                Payment.period_month == APRIL,
                Payment.for_type == PaymentFor.rent,
                Payment.is_void == False,
            )
        )).all())
        cnt_rs = len((await session.execute(
            select(RentSchedule.id).where(RentSchedule.period_month == APRIL)
        )).all())
        print(f"  [dry] Would drop {cnt_pay} April rent payments, {cnt_rs} rent schedules")

    # ── Reload from sheet ─────────────────────────────────────────────────────
    seen_rs: set[int] = set()  # tenancy_ids that already got an RS this run
    for row in data_rows:
        if not row or not row[0]:
            continue
        name_raw  = row[c_name].strip()  if c_name  >= 0 and c_name  < len(row) else ""
        room_raw  = row[c_room].strip()  if c_room  >= 0 and c_room  < len(row) else ""
        phone_raw = row[c_phone].strip() if c_phone >= 0 and c_phone < len(row) else ""
        event_raw = row[c_event].strip() if c_event >= 0 and c_event < len(row) else ""

        if not name_raw:
            continue
        stats["rows"] += 1

        # Skip NO SHOW — booking advance is not a rent payment
        if "NO SHOW" in event_raw.upper():
            stats["skipped_noshow"] += 1
            continue

        # Match tenant
        tenant = phone_map.get(_norm_phone(phone_raw))
        if not tenant:
            tenant = name_map.get(name_raw.lower())
        if not tenant:
            print(f"  [no tenant] {name_raw} room={room_raw} phone={phone_raw}")
            stats["no_tenant"] += 1
            continue

        # Find monthly tenancy active in April
        tenancy = None
        april_end = date(2026, 4, 30)
        for ten in sorted(tenant.tenancies, key=lambda t: t.checkin_date or date.min, reverse=True):
            if ten.stay_type == StayType.daily:
                continue
            if ten.checkin_date and ten.checkin_date <= april_end:
                tenancy = ten
                break
        if not tenancy:
            print(f"  [no tenancy] {name_raw} room={room_raw}")
            stats["no_tenancy"] += 1
            continue

        stats["matched"] += 1
        rent_due = _parse_num(row[c_rdue] if c_rdue >= 0 and c_rdue < len(row) else 0)
        cash     = _parse_num(row[c_cash] if c_cash >= 0 and c_cash < len(row) else 0)
        upi      = _parse_num(row[c_upi]  if c_upi  >= 0 and c_upi  < len(row) else 0)

        checkin_d = _parse_date(row[c_checkin] if c_checkin >= 0 and c_checkin < len(row) else "")
        pay_date  = checkin_d or APRIL

        if write:
            # RentSchedule — one per tenancy per month (sheet may have duplicate rows for same bed)
            if rent_due > 0 and tenancy.id not in seen_rs:
                rs = RentSchedule(
                    tenancy_id=tenancy.id,
                    period_month=APRIL,
                    rent_due=Decimal(str(rent_due)),
                    adjustment=Decimal("0"),
                )
                session.add(rs)
                seen_rs.add(tenancy.id)
                stats["rs_created"] += 1
            elif rent_due > 0:
                print(f"  [dup RS skipped] {name_raw} tenancy_id={tenancy.id}")

            # Cash payment
            if cash > 0:
                session.add(Payment(
                    tenancy_id=tenancy.id,
                    amount=Decimal(str(cash)),
                    payment_mode=PaymentMode.cash,
                    payment_date=pay_date,
                    period_month=APRIL,
                    for_type=PaymentFor.rent,
                    notes="sheet_reload_apr2026",
                ))
                stats["pay_created"] += 1

            # UPI payment
            if upi > 0:
                session.add(Payment(
                    tenancy_id=tenancy.id,
                    amount=Decimal(str(upi)),
                    payment_mode=PaymentMode.upi,
                    payment_date=pay_date,
                    period_month=APRIL,
                    for_type=PaymentFor.rent,
                    notes="sheet_reload_apr2026",
                ))
                stats["pay_created"] += 1
        else:
            if rent_due > 0:
                stats["rs_created"] += 1
            if cash > 0:
                stats["pay_created"] += 1
            if upi > 0:
                stats["pay_created"] += 1

    # ── Reconcile RS status based on payments ────────────────────────────────
    if write:
        await session.flush()
        rs_rows = (await session.execute(
            select(RentSchedule).where(RentSchedule.period_month == APRIL)
        )).scalars().all()
        paid_cnt = partial_cnt = 0
        for rs in rs_rows:
            total_paid = await session.scalar(
                select(func.sum(Payment.amount)).where(
                    Payment.tenancy_id == rs.tenancy_id,
                    Payment.period_month == APRIL,
                    Payment.for_type == PaymentFor.rent,
                    Payment.is_void == False,
                )
            ) or Decimal("0")
            effective_due = (rs.rent_due or Decimal("0")) + (rs.adjustment or Decimal("0"))
            if total_paid >= effective_due and effective_due > 0:
                rs.status = RentStatus.paid
                paid_cnt += 1
            elif total_paid > 0:
                rs.status = RentStatus.partial
                partial_cnt += 1
        print(f"  RS status reconciled: {paid_cnt} paid, {partial_cnt} partial, {len(rs_rows)-paid_cnt-partial_cnt} pending")

    return stats


# ──────────────────────────────────────────────────────────────────────────────
# DAY WISE reload
# ──────────────────────────────────────────────────────────────────────────────

async def reload_daywise(session: AsyncSession, write: bool) -> dict:
    stats = {"rows": 0, "created": 0, "no_room": 0, "pay_created": 0}

    ws = _get_worksheet_sync("DAY WISE")
    all_vals = ws.get_all_values()

    # Find header row
    hdr_idx = None
    for i, row in enumerate(all_vals):
        if str(row[0] if row else "").strip().lower() == "room":
            hdr_idx = i
            break
    if hdr_idx is None:
        print("ERROR: Could not find header row in DAY WISE")
        return stats

    headers = [h.strip().lower() for h in all_vals[hdr_idx]]
    def col(name: str) -> int:
        try:
            return headers.index(name.lower())
        except ValueError:
            return -1

    c_room    = col("room");       c_name    = col("name")
    c_phone   = col("phone");      c_sharing = col("sharing")
    c_bldg    = col("building");   c_rate    = col("rent/day")
    c_days    = col("days");       c_booking = col("booking amt")
    c_maint   = col("maintenance"); c_cash   = col("cash")
    c_upi     = col("upi");        c_total   = col("total paid")
    c_status  = col("status");     c_checkin = col("check-in")
    c_checkout= col("checkout");   c_notes   = col("notes")
    c_gender  = col("gender");     c_food    = col("food pref")

    data_rows = all_vals[hdr_idx + 1:]
    print(f"DAY WISE: {len(data_rows)} data rows to process")

    # Room lookup
    room_rows = (await session.execute(select(Room))).scalars().all()
    room_map = {str(r.room_number).strip(): r for r in room_rows}

    # Existing tenants by phone
    all_tenants = (await session.execute(select(Tenant))).scalars().all()
    phone_map: dict[str, Tenant] = {}
    for t in all_tenants:
        if t.phone:
            phone_map[_norm_phone(t.phone)] = t

    # ── DROP existing daily-stay tenancies + payments ─────────────────────────
    # Get all daily tenancy IDs first
    dw_ids = [r[0] for r in (await session.execute(
        select(Tenancy.id).where(Tenancy.stay_type == StayType.daily)
    )).all()]

    if write:
        if dw_ids:
            del_pay = await session.execute(
                delete(Payment).where(Payment.tenancy_id.in_(dw_ids))
            )
            del_ten = await session.execute(
                delete(Tenancy).where(Tenancy.id.in_(dw_ids))
            )
            print(f"  Dropped {del_pay.rowcount} daywise payments, {del_ten.rowcount} daywise tenancies")
    else:
        dw_pay_cnt = len((await session.execute(
            select(Payment.id).where(Payment.tenancy_id.in_(dw_ids))
        )).all()) if dw_ids else 0
        print(f"  [dry] Would drop {dw_pay_cnt} daywise payments, {len(dw_ids)} daywise tenancies")

    # ── Reload from sheet ─────────────────────────────────────────────────────
    for row in data_rows:
        if not row or not row[0]:
            continue
        room_raw   = row[c_room].strip()   if c_room  >= 0 and c_room  < len(row) else ""
        name_raw   = row[c_name].strip()   if c_name  >= 0 and c_name  < len(row) else ""
        phone_raw  = row[c_phone].strip()  if c_phone >= 0 and c_phone < len(row) else ""

        if not name_raw:
            continue
        stats["rows"] += 1

        norm_ph = _norm_phone(phone_raw)
        checkin_d  = _parse_date(row[c_checkin]  if c_checkin  >= 0 and c_checkin  < len(row) else "")
        checkout_d = _parse_date(row[c_checkout] if c_checkout >= 0 and c_checkout < len(row) else "")
        daily_rate  = _parse_num(row[c_rate]    if c_rate    >= 0 and c_rate    < len(row) else 0)
        num_days    = _parse_num(row[c_days]    if c_days    >= 0 and c_days    < len(row) else 0)
        booking_amt = _parse_num(row[c_booking] if c_booking >= 0 and c_booking < len(row) else 0)
        maintenance = _parse_num(row[c_maint]   if c_maint   >= 0 and c_maint   < len(row) else 0)
        cash        = _parse_num(row[c_cash]    if c_cash    >= 0 and c_cash    < len(row) else 0)
        upi         = _parse_num(row[c_upi]     if c_upi     >= 0 and c_upi     < len(row) else 0)
        total_paid  = _parse_num(row[c_total]   if c_total   >= 0 and c_total   < len(row) else 0)
        status_raw  = row[c_status].strip().upper() if c_status >= 0 and c_status < len(row) else ""
        notes_raw   = row[c_notes].strip()  if c_notes  >= 0 and c_notes  < len(row) else ""
        gender_raw  = row[c_gender].strip() if c_gender >= 0 and c_gender < len(row) else ""
        food_raw    = row[c_food].strip()   if c_food   >= 0 and c_food   < len(row) else ""

        room_obj = room_map.get(room_raw)
        if not room_obj:
            print(f"  [no room] {name_raw} room={room_raw}")
            stats["no_room"] += 1

        ten_status = TenancyStatus.active if status_raw in ("ACTIVE", "CHECKIN") else TenancyStatus.exited

        if write:
            # Find or create Tenant
            tenant = phone_map.get(norm_ph) if norm_ph else None
            if not tenant:
                # Try by name
                for t in all_tenants:
                    if t.name.strip().lower() == name_raw.lower():
                        tenant = t
                        break
            if not tenant:
                phone_stored = (f"+91{norm_ph}" if norm_ph and len(norm_ph) == 10
                                else phone_raw or None)
                tenant = Tenant(
                    name=name_raw,
                    phone=phone_stored,
                    gender=gender_raw or None,
                    food_preference=food_raw or None,
                )
                session.add(tenant)
                await session.flush()
                if norm_ph:
                    phone_map[norm_ph] = tenant

            tenancy = Tenancy(
                tenant_id=tenant.id,
                room_id=room_obj.id if room_obj else None,
                stay_type=StayType.daily,
                status=ten_status,
                checkin_date=checkin_d,
                checkout_date=checkout_d,
                expected_checkout=checkout_d,
                agreed_rent=Decimal(str(daily_rate)),
                booking_amount=Decimal(str(booking_amt)),
                maintenance_fee=Decimal(str(maintenance)),
                notes=notes_raw or None,
                entered_by="sheet_reload",
            )
            session.add(tenancy)
            await session.flush()
            stats["created"] += 1

            # Payments — prefer cash/upi split if available, else total as cash
            if cash > 0:
                session.add(Payment(
                    tenancy_id=tenancy.id,
                    amount=Decimal(str(cash)),
                    payment_mode=PaymentMode.cash,
                    payment_date=checkin_d or date.today(),
                    for_type=PaymentFor.rent,
                    notes="sheet_reload_daywise",
                ))
                stats["pay_created"] += 1
            if upi > 0:
                session.add(Payment(
                    tenancy_id=tenancy.id,
                    amount=Decimal(str(upi)),
                    payment_mode=PaymentMode.upi,
                    payment_date=checkin_d or date.today(),
                    for_type=PaymentFor.rent,
                    notes="sheet_reload_daywise",
                ))
                stats["pay_created"] += 1
            # If no cash/upi split but total_paid > 0, record as cash
            if cash == 0 and upi == 0 and total_paid > 0:
                session.add(Payment(
                    tenancy_id=tenancy.id,
                    amount=Decimal(str(total_paid)),
                    payment_mode=PaymentMode.cash,
                    payment_date=checkin_d or date.today(),
                    for_type=PaymentFor.rent,
                    notes="sheet_reload_daywise",
                ))
                stats["pay_created"] += 1
        else:
            stats["created"] += 1
            if cash > 0: stats["pay_created"] += 1
            if upi > 0:  stats["pay_created"] += 1
            if cash == 0 and upi == 0 and total_paid > 0:
                stats["pay_created"] += 1

    return stats


# ──────────────────────────────────────────────────────────────────────────────
# TENANTS master resync (monthly only — no daily guests)
# ──────────────────────────────────────────────────────────────────────────────

async def resync_tenants_master() -> dict:
    """Add monthly tenants missing from TENANTS master tab. Read-only check first."""
    import re as _re
    import gspread
    from google.oauth2.service_account import Credentials
    from src.integrations.gsheets import CREDENTIALS_PATH, SHEET_ID
    from src.database.db_manager import init_engine, get_session as _gs
    from sqlalchemy.orm import selectinload as _sl

    stats = {"added": 0, "failed": 0}

    creds = Credentials.from_service_account_file(
        CREDENTIALS_PATH,
        scopes=["https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive"],
    )
    gc = gspread.authorize(creds)
    ss = gc.open_by_key(SHEET_ID)
    ws_t = ss.worksheet("TENANTS")
    rows = ws_t.get_all_values()

    def _np(p):
        d = _re.sub(r"\D", "", str(p or ""))
        return d[-10:] if len(d) >= 10 else d

    sheet_phones = {_np(r[2]) for r in rows[1:] if len(r) > 2}
    print(f"TENANTS master: {len(sheet_phones)} existing phones")

    from src.integrations.gsheets import add_tenant
    from src.database.db_manager import get_session
    from datetime import timedelta, datetime as _dt

    async with get_session() as s:
        cutoff = _dt.utcnow() - timedelta(days=90)  # wider window for this reload
        all_t = (await s.execute(
            select(Tenant)
            .options(_sl(Tenant.tenancies).selectinload(Tenancy.room).selectinload(Room.property))
            .where(Tenant.created_at >= cutoff)
        )).scalars().all()

        seen_t: set[int] = set()
        seen_names: set[str] = set()
        missing = []
        # Also build a name set from TENANTS sheet to catch malformed-phone duplicates
        sheet_names = {r[1].strip().lower() for r in rows[1:] if len(r) > 1 and r[1].strip()}
        for t in all_t:
            ph = _np(t.phone or "")
            if ph and ph in sheet_phones:
                continue
            name_key = t.name.strip().lower()
            if name_key in sheet_names:
                continue
            if t.id in seen_t or name_key in seen_names:
                continue
            # Monthly tenants only — exclude daily stays
            ten = next(
                (x for x in t.tenancies
                 if x.room and str(getattr(x.stay_type, "value", x.stay_type) or "") != "daily"),
                None,
            )
            if not ten:
                continue
            seen_t.add(t.id)
            seen_names.add(name_key)
            missing.append((t, ten))

    print(f"Monthly tenants missing from TENANTS master: {len(missing)}")
    for t, ten in missing:
        print(f"  {t.name:28s} room={ten.room.room_number} checkin={ten.checkin_date}")

    for t, ten in missing:
        phone_s = t.phone
        if phone_s and not phone_s.startswith("+"):
            phone_s = "+91" + phone_s[-10:]
        building = ""
        if ten.room and ten.room.property:
            building = ten.room.property.name
        sharing = ten.sharing_type.value if ten.sharing_type else (
            ten.room.room_type.value if hasattr(ten.room.room_type, "value") else str(ten.room.room_type or "")
        ) if ten.room else ""
        try:
            r = await add_tenant(
                room_number=str(ten.room.room_number),
                name=t.name, phone=phone_s,
                gender=t.gender or "", building=building,
                floor=str(ten.room.floor or "") if ten.room else "",
                sharing=sharing,
                checkin=ten.checkin_date.strftime("%d/%m/%Y") if ten.checkin_date else "",
                agreed_rent=float(ten.agreed_rent or 0),
                deposit=float(ten.security_deposit or 0),
                booking=float(ten.booking_amount or 0),
                maintenance=float(ten.maintenance_fee or 0),
                notes="", entered_by="sheet_reload",
            )
            if r.get("success"):
                stats["added"] += 1
                print(f"  [ok] {t.name} → TENANTS row {r.get('tenants_row')}")
            else:
                stats["failed"] += 1
                print(f"  [fail] {t.name}: {r.get('error')}")
        except Exception as e:
            stats["failed"] += 1
            print(f"  [exc] {t.name}: {e}")

    return stats


# ──────────────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────────────

async def main(write: bool) -> None:
    engine = create_async_engine(DATABASE_URL, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    mode = "WRITE" if write else "DRY RUN"
    print(f"\n{'='*60}")
    print(f"RELOAD FROM SHEET  [{mode}]")
    print(f"{'='*60}\n")

    async with Session() as session:
        # ── April 2026 ────────────────────────────────────────────────────────
        print("─── APRIL 2026 ───")
        apr_stats = await reload_april(session, write)
        print(f"  Rows processed : {apr_stats['rows']}")
        print(f"  Matched        : {apr_stats['matched']}")
        print(f"  No tenant found: {apr_stats['no_tenant']}")
        print(f"  No tenancy     : {apr_stats['no_tenancy']}")
        print(f"  Skipped noshow : {apr_stats['skipped_noshow']}")
        print(f"  RS created     : {apr_stats['rs_created']}")
        print(f"  Payments       : {apr_stats['pay_created']}")

        print()

        # ── Day Wise ──────────────────────────────────────────────────────────
        print("─── DAY WISE ───")
        dw_stats = await reload_daywise(session, write)
        print(f"  Rows processed : {dw_stats['rows']}")
        print(f"  Tenancies      : {dw_stats['created']}")
        print(f"  No room        : {dw_stats['no_room']}")
        print(f"  Payments       : {dw_stats['pay_created']}")

        if write:
            print("\nCommitting…")
            await session.commit()
            print("Committed.")
        else:
            print(f"\n[DRY RUN] No changes written. Re-run with --write to apply.")

    await engine.dispose()

    # ── TENANTS master resync (after DB is loaded) ────────────────────────────
    if write:
        print()
        print("─── TENANTS MASTER RESYNC ───")
        from src.database.db_manager import init_engine
        init_engine(os.environ["DATABASE_URL"])
        t_stats = await resync_tenants_master()
        print(f"  Added: {t_stats['added']}  Failed: {t_stats['failed']}")

    print("\nDone.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(write=args.write))
