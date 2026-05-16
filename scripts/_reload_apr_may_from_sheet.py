"""
CLEAN WIPE + RELOAD of April + May 2026 payments from Google Sheet "Long term" tab.

What it does:
  1. Deletes ALL payments where period_month in (Apr, May) -- all for_types.
  2. Deletes ALL rent_schedules where period_month in (Apr, May).
  3. Reads sheet row by row and re-creates everything from sheet data only.

Split logic (sheet data only, no DB amount references):
  - agreed_rent: from sheet cols (may-override > feb-override > monthly)
  - 1st-month prorated if checkin date falls in that period month
  - booking_advance: from sheet COL_BOOKING -- already paid, reduces deposit shortfall
  - deposit_shortfall = agreed_deposit - booking_advance
  - For each month: rent_allocated = min(total_paid, rent_due)
                    deposit_allocated = min(total_paid - rent_allocated, deposit_shortfall)
  - Cash first toward rent, then UPI, then deposit.

Usage:
    python scripts/_reload_apr_may_from_sheet.py          # dry run
    python scripts/_reload_apr_may_from_sheet.py --write  # commit
"""
import asyncio, os, sys, re, math, argparse
from datetime import date, datetime
from decimal import Decimal

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv; load_dotenv()

import gspread
from google.oauth2.service_account import Credentials
from sqlalchemy import select, delete as sa_delete, func
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from src.database.models import (
    Tenant, Tenancy, Room, RentSchedule, Payment,
    TenancyStatus, PaymentMode, PaymentFor, RentStatus,
)

# ── Config ─────────────────────────────────────────────────────────────────────
SOURCE_SHEET_ID = "1Vr_fSIOuuKBK4MWF-FVqgAIUPbqun3POszaXYfj-Ea0"
CREDS_FILE      = "credentials/gsheets_service_account.json"
APR = date(2026, 4, 1)
MAY = date(2026, 5, 1)

# 0-based column indices in "Long term" tab
COL_ROOM     = 0   # A
COL_NAME     = 1   # B
COL_CHECKIN  = 4   # E
COL_BOOKING  = 5   # F  advance already paid (reduces deposit shortfall)
COL_DEPOSIT  = 6   # G  agreed security deposit
COL_RENT_M   = 9   # J  agreed rent (monthly base)
COL_RENT_FEB = 10  # K  rent override from Feb
COL_RENT_MAY = 11  # L  rent override from May
COL_PHONE    = 3   # D
COL_APR_CASH = 22  # W
COL_APR_UPI  = 23  # X
COL_MAY_UPI  = 25  # Z
COL_MAY_CASH = 26  # AA


# ── Helpers ───────────────────────────────────────────────────────────────────
def pn(v):
    """Parse cell to positive float, 0 on failure."""
    if not v: return 0.0
    s = str(v).replace(",", "").strip()
    try:
        f = float(s)
        return max(0.0, f)
    except ValueError:
        return 0.0


def norm_phone(raw):
    d = re.sub(r"\D", "", str(raw or ""))
    if d.startswith("91") and len(d) == 12:
        d = d[2:]
    return f"+91{d}" if len(d) == 10 else ""


def parse_date(v):
    if not v: return None
    s = str(v).strip()
    for fmt in ("%d-%m-%Y", "%d-%m-%y", "%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def prorate(agreed: float, checkin: date, period: date) -> float:
    """
    If checkin falls in period month, return floor-prorated rent.
    Otherwise return full agreed rent.
    """
    if checkin and checkin.year == period.year and checkin.month == period.month:
        import calendar
        days = calendar.monthrange(period.year, period.month)[1]
        remaining = days - checkin.day + 1
        return math.floor(agreed * remaining / days)
    return agreed


# ── Sheet reader ──────────────────────────────────────────────────────────────
def read_sheet():
    scopes = ["https://www.googleapis.com/auth/spreadsheets",
              "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_file(CREDS_FILE, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SOURCE_SHEET_ID)
    ws = sh.worksheet("Long term")
    all_rows = ws.get_all_values()

    data = []
    for r in all_rows[1:]:
        def _c(col): return r[col].strip() if len(r) > col else ""

        name = _c(COL_NAME)
        if not name:
            continue

        # Agreed rent: may-override > feb-override > monthly base
        rent_base = pn(_c(COL_RENT_M))
        rent_feb  = pn(_c(COL_RENT_FEB))
        rent_may  = pn(_c(COL_RENT_MAY))
        agreed_rent = rent_may or rent_feb or rent_base

        data.append({
            "name":            name,
            "room":            re.sub(r"\.0$", "", _c(COL_ROOM)),
            "phone":           norm_phone(_c(COL_PHONE)),
            "checkin":         parse_date(_c(COL_CHECKIN)),
            "agreed_rent":     agreed_rent,
            "agreed_deposit":  pn(_c(COL_DEPOSIT)),
            "booking_advance": pn(_c(COL_BOOKING)),   # advance already paid, not part of Apr/May
            "apr_cash":        pn(_c(COL_APR_CASH)),
            "apr_upi":         pn(_c(COL_APR_UPI)),
            "may_cash":        pn(_c(COL_MAY_CASH)),
            "may_upi":         pn(_c(COL_MAY_UPI)),
        })

    return data


# ── Core logic ────────────────────────────────────────────────────────────────
async def run(write: bool):
    tag = "WRITE" if write else "DRY RUN"
    print(f"{'='*65}")
    print(f"APR+MAY RELOAD FROM SHEET  [{tag}]")
    print(f"{'='*65}")

    print("\nStep 1: Reading Long term sheet...")
    rows = read_sheet()
    has_any = [r for r in rows if r["apr_cash"] or r["apr_upi"] or r["may_cash"] or r["may_upi"]]
    print(f"  Total rows: {len(rows)}  rows with Apr/May payments: {len(has_any)}")
    print(f"  Sheet Apr: Cash={sum(r['apr_cash'] for r in rows):,.0f}  "
          f"UPI={sum(r['apr_upi'] for r in rows):,.0f}")
    print(f"  Sheet May: Cash={sum(r['may_cash'] for r in rows):,.0f}  "
          f"UPI={sum(r['may_upi'] for r in rows):,.0f}")

    url = os.environ["DATABASE_URL"]
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(url, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    matched_cnt = 0
    no_phone    = []
    no_match    = []
    warnings    = []

    apr_rent_n = 0;  apr_rent_t = 0.0
    apr_dep_n  = 0;  apr_dep_t  = 0.0
    may_rent_n = 0;  may_rent_t = 0.0
    may_dep_n  = 0;  may_dep_t  = 0.0

    async with Session() as session:
        session.autoflush = False

        # ── Step 2: Wipe Apr + May payments + rent schedules ─────────────
        if write:
            del_pay = await session.execute(
                sa_delete(Payment).where(
                    Payment.period_month.in_([APR, MAY])
                )
            )
            del_rs = await session.execute(
                sa_delete(RentSchedule).where(
                    RentSchedule.period_month.in_([APR, MAY])
                )
            )
            await session.flush()
            print(f"\nStep 2: Wiped {del_pay.rowcount} payments + {del_rs.rowcount} rent_schedules")
        else:
            cnt_pay = await session.scalar(
                select(func.count()).select_from(Payment).where(
                    Payment.period_month.in_([APR, MAY])
                )
            ) or 0
            cnt_rs = await session.scalar(
                select(func.count()).select_from(RentSchedule).where(
                    RentSchedule.period_month.in_([APR, MAY])
                )
            ) or 0
            print(f"\nStep 2 (dry): Would wipe {cnt_pay} payments + {cnt_rs} rent_schedules")

        # ── Step 3: Match + record ────────────────────────────────────────
        print(f"\nStep 3: Processing rows...")
        seen_tenancies = set()  # guard against duplicate rows for same tenancy

        for rec in rows:
            apr_total = rec["apr_cash"] + rec["apr_upi"]
            may_total = rec["may_cash"] + rec["may_upi"]
            if apr_total == 0 and may_total == 0:
                continue

            # ── Match tenancy ────────────────────────────────────────────
            phone  = rec["phone"]
            room   = rec["room"]
            name   = rec["name"]

            if not phone:
                no_phone.append(f"{name}  room {room}")
                continue

            # Try phone match first
            tenant = await session.scalar(
                select(Tenant).where(Tenant.phone == phone)
            )
            tenancy = None
            if tenant:
                tenancy = await session.scalar(
                    select(Tenancy).where(
                        Tenancy.tenant_id == tenant.id,
                        Tenancy.status == TenancyStatus.active,
                    )
                )
                if not tenancy:
                    # fallback: any tenancy (exited tenants still had payments)
                    tenancy = await session.scalar(
                        select(Tenancy).where(
                            Tenancy.tenant_id == tenant.id,
                        ).order_by(Tenancy.checkin_date.desc())
                    )

            # Fallback: room number match
            if not tenancy and room:
                room_obj = await session.scalar(
                    select(Room).where(Room.room_number == room)
                )
                if room_obj:
                    tenancy = await session.scalar(
                        select(Tenancy).where(
                            Tenancy.room_id == room_obj.id,
                            Tenancy.status == TenancyStatus.active,
                        )
                    )

            if not tenancy:
                no_match.append(f"{name}  room {room}  phone {phone}")
                continue

            if tenancy.id in seen_tenancies:
                warnings.append(f"Duplicate row for {name} room {room} -- skipping second row")
                continue
            seen_tenancies.add(tenancy.id)
            matched_cnt += 1

            # ── Deposit shortfall from SHEET data only ───────────────────
            booking_advance  = rec["booking_advance"]   # already paid before Apr/May
            agreed_deposit   = rec["agreed_deposit"]
            deposit_shortfall = max(0.0, agreed_deposit - booking_advance)

            # ── Helper: split + record for one month ─────────────────────
            def record_month(cash: float, upi: float, period: date, label: str):
                nonlocal deposit_shortfall
                nonlocal apr_rent_n, apr_rent_t, apr_dep_n, apr_dep_t
                nonlocal may_rent_n, may_rent_t, may_dep_n, may_dep_t

                total = cash + upi
                if total == 0:
                    return

                # Rent due for this month (prorated if 1st month)
                agreed = rec["agreed_rent"]
                if agreed == 0:
                    agreed = total  # no rent info -> treat all as rent
                    warnings.append(f"{name} room {room}: no agreed_rent in sheet for {label}")
                rent_due = prorate(agreed, rec["checkin"], period)

                # Allocate
                rent_target = min(total, rent_due)
                raw_excess  = total - rent_target
                dep_target  = min(raw_excess, deposit_shortfall)

                # Cash goes first toward rent, then UPI
                cash_rent = min(cash, rent_target)
                upi_rent  = min(upi,  rent_target - cash_rent)
                cash_over = cash - cash_rent
                upi_over  = upi  - upi_rent

                cash_dep  = min(cash_over, dep_target)
                upi_dep   = min(upi_over,  max(0.0, dep_target - cash_dep))

                deposit_shortfall -= (cash_dep + upi_dep)

                # Rent schedule (status based on coverage)
                if rent_target >= rent_due:
                    rs_status = RentStatus.paid
                elif rent_target > 0:
                    rs_status = RentStatus.partial
                else:
                    rs_status = RentStatus.pending

                if write:
                    session.add(RentSchedule(
                        tenancy_id=tenancy.id,
                        period_month=period,
                        rent_due=Decimal(str(round(rent_due, 2))),
                        maintenance_due=Decimal("0"),
                        status=rs_status,
                        due_date=period,
                        notes=f"{label} sheet reload",
                    ))

                    def _pay(amt, mode, ftype):
                        if amt > 0:
                            session.add(Payment(
                                tenancy_id=tenancy.id,
                                amount=Decimal(str(round(amt, 2))),
                                payment_date=period,
                                payment_mode=mode,
                                for_type=ftype,
                                period_month=period,
                                notes=f"{label} sheet reload",
                            ))

                    _pay(cash_rent, PaymentMode.cash, PaymentFor.rent)
                    _pay(upi_rent,  PaymentMode.upi,  PaymentFor.rent)
                    _pay(cash_dep,  PaymentMode.cash, PaymentFor.deposit)
                    _pay(upi_dep,   PaymentMode.upi,  PaymentFor.deposit)

                # Stats
                if period == APR:
                    if cash_rent > 0: apr_rent_n += 1; apr_rent_t += cash_rent
                    if upi_rent  > 0: apr_rent_n += 1; apr_rent_t += upi_rent
                    if cash_dep  > 0: apr_dep_n  += 1; apr_dep_t  += cash_dep
                    if upi_dep   > 0: apr_dep_n  += 1; apr_dep_t  += upi_dep
                else:
                    if cash_rent > 0: may_rent_n += 1; may_rent_t += cash_rent
                    if upi_rent  > 0: may_rent_n += 1; may_rent_t += upi_rent
                    if cash_dep  > 0: may_dep_n  += 1; may_dep_t  += cash_dep
                    if upi_dep   > 0: may_dep_n  += 1; may_dep_t  += upi_dep

            record_month(rec["apr_cash"], rec["apr_upi"], APR, "Apr")
            record_month(rec["may_cash"], rec["may_upi"], MAY, "May")

        if write:
            await session.commit()

    await engine.dispose()

    print(f"\n{'='*65}")
    print(f"RESULTS [{tag}]")
    print(f"  Matched:              {matched_cnt}")
    print(f"  Apr rent payments:    {apr_rent_n}  Rs.{apr_rent_t:,.0f}")
    print(f"  Apr deposit payments: {apr_dep_n}  Rs.{apr_dep_t:,.0f}")
    print(f"  May rent payments:    {may_rent_n}  Rs.{may_rent_t:,.0f}")
    print(f"  May deposit payments: {may_dep_n}  Rs.{may_dep_t:,.0f}")
    print(f"  Apr total:            Rs.{apr_rent_t+apr_dep_t:,.0f}")
    print(f"  May total:            Rs.{may_rent_t+may_dep_t:,.0f}")

    if no_phone:
        print(f"\n  NO PHONE ({len(no_phone)}):")
        for x in no_phone: print(f"    - {x}")
    if no_match:
        print(f"\n  NO DB MATCH ({len(no_match)}):")
        for x in no_match: print(f"    - {x}")
    if warnings:
        print(f"\n  WARNINGS ({len(warnings)}):")
        for x in warnings: print(f"    ! {x}")

    if not write:
        print("\n  *** DRY RUN - nothing saved. Re-run with --write to commit. ***")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true",
                        help="Commit to DB (default: dry run)")
    args = parser.parse_args()
    asyncio.run(run(args.write))
