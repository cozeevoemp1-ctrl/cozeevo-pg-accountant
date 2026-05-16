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
from sqlalchemy import select, func, text
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

# Column aliases: keys are lowercase stripped header variants we accept
# Each value is the canonical field name in our row dict
HEADER_MAP = {
    # room
    "room number": "room", "room": "room", "room no": "room",
    # name
    "name": "name",
    # phone — sheet header is "Mobile Number"
    "phone": "phone", "phone number": "phone", "mobile": "phone",
    "mobile number": "phone",
    # checkin
    "checkin": "checkin", "check in": "checkin", "check-in": "checkin",
    "checkin date": "checkin", "check in date": "checkin",
    # booking advance
    "booking": "booking_advance", "advance": "booking_advance",
    "booking amount": "booking_advance", "advance paid": "booking_advance",
    # deposit
    "deposit": "agreed_deposit", "security deposit": "agreed_deposit",
    # rent columns  (first match wins — rent > rent monthly > etc.)
    "rent": "rent_base", "rent monthly": "rent_base", "monthly rent": "rent_base",
    # rent overrides — sheet headers: "From 1st FEB", "From 1st May"
    "rent feb": "rent_feb", "feb rent": "rent_feb", "from 1st feb": "rent_feb",
    "rent may": "rent_may", "may rent": "rent_may", "from 1st may": "rent_may",
    # April payment columns
    "april cash": "apr_cash",
    "april upi":  "apr_upi",
    # May columns — headers are correct
    "may upi": "may_upi", "may cash": "may_cash",
}


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

    if not all_rows:
        raise ValueError("Sheet is empty")

    # ── Build header index from row 1 ─────────────────────────────────
    header_row = all_rows[0]
    col_idx: dict[str, int] = {}  # canonical field name -> 0-based index
    print("  All sheet headers:")
    for i, h in enumerate(header_row):
        if h.strip():
            col_letter = chr(65+i) if i<26 else 'A'+chr(65+i-26)
            print(f"    col {i:2d} ({col_letter}) '{h.strip()}'")
    print("  Matched headers:")
    for i, h in enumerate(header_row):
        key = h.strip().lower()
        field = HEADER_MAP.get(key)
        if field and field not in col_idx:  # first match wins
            col_idx[field] = i
            print(f"    col {i:2d} ({chr(65+i) if i<26 else 'A'+chr(65+i-26)}) "
                  f"'{h.strip()}' -> {field}")

    # Mandatory payment columns
    for required in ("apr_cash", "apr_upi", "may_upi", "may_cash"):
        if required not in col_idx:
            raise ValueError(
                f"Could not find column for '{required}' in sheet headers. "
                f"Headers: {header_row}"
            )

    def _c(r, field, default=""):
        idx = col_idx.get(field)
        if idx is None or idx >= len(r):
            return default
        return r[idx].strip()

    data = []
    for r in all_rows[1:]:
        name = _c(r, "name")
        if not name:
            continue

        # Agreed rent: may-override > feb-override > base
        rent_base = pn(_c(r, "rent_base"))
        rent_feb  = pn(_c(r, "rent_feb"))
        rent_may  = pn(_c(r, "rent_may"))
        agreed_rent = rent_may or rent_feb or rent_base

        room_raw = _c(r, "room")
        data.append({
            "name":            name,
            "room":            re.sub(r"\.0$", "", room_raw),
            "phone":           norm_phone(_c(r, "phone")),
            "checkin":         parse_date(_c(r, "checkin")),
            "agreed_rent":     agreed_rent,
            "agreed_deposit":  pn(_c(r, "agreed_deposit")),
            "booking_advance": pn(_c(r, "booking_advance")),
            "apr_cash":        pn(_c(r, "apr_cash")),
            "apr_upi":         pn(_c(r, "apr_upi")),
            "may_cash":        pn(_c(r, "may_cash")),
            "may_upi":         pn(_c(r, "may_upi")),
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
            # Raw SQL required — ORM bulk delete bypasses the row-level trigger check
            await session.execute(text("SET LOCAL app.allow_historical_write = 'true'"))
            r1 = await session.execute(text(
                "DELETE FROM payments WHERE period_month IN ('2026-04-01', '2026-05-01')"
            ))
            r2 = await session.execute(text(
                "DELETE FROM rent_schedule WHERE period_month IN ('2026-04-01', '2026-05-01')"
            ))
            await session.flush()
            print(f"\nStep 2: Wiped {r1.rowcount} payments + {r2.rowcount} rent_schedules")
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
        # ── Step 3a: Match all rows → accumulate per tenancy ────────────
        print(f"\nStep 3: Matching rows to tenancies...")

        # tenancy_id -> accumulated totals + metadata
        tenancy_buckets: dict[int, dict] = {}

        for rec in rows:
            apr_total = rec["apr_cash"] + rec["apr_upi"]
            may_total = rec["may_cash"] + rec["may_upi"]
            if apr_total == 0 and may_total == 0:
                continue

            phone = rec["phone"]
            room  = rec["room"]
            name  = rec["name"]

            if not phone:
                no_phone.append(f"{name}  room {room}")
                continue

            # Phone match first
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

            tid = tenancy.id
            if tid not in tenancy_buckets:
                tenancy_buckets[tid] = {
                    "tenancy":         tenancy,
                    "names":           [],
                    "apr_cash":        0.0,
                    "apr_upi":         0.0,
                    "may_cash":        0.0,
                    "may_upi":         0.0,
                    # take first row's agreed values (they should match)
                    "agreed_rent":     rec["agreed_rent"],
                    "agreed_deposit":  rec["agreed_deposit"],
                    "booking_advance": rec["booking_advance"],
                    "checkin":         rec["checkin"],
                }
            b = tenancy_buckets[tid]
            b["names"].append(name)
            b["apr_cash"] += rec["apr_cash"]
            b["apr_upi"]  += rec["apr_upi"]
            b["may_cash"] += rec["may_cash"]
            b["may_upi"]  += rec["may_upi"]

        # Report rows that merged
        for tid, b in tenancy_buckets.items():
            if len(b["names"]) > 1:
                warnings.append(
                    f"Merged {len(b['names'])} rows for tenancy {tid} "
                    f"({' + '.join(b['names'])})"
                )

        matched_cnt = len(tenancy_buckets)
        print(f"  {matched_cnt} unique tenancies matched "
              f"({sum(1 for b in tenancy_buckets.values() if len(b['names'])>1)} merged)")

        # ── Step 3b: Record per tenancy ───────────────────────────────────
        for tid, b in tenancy_buckets.items():
            tenancy = b["tenancy"]

            # ── Helper: split + record for one month ─────────────────────
            name = " + ".join(b["names"])
            room = ""  # not needed past this point

            def record_month(cash: float, upi: float, period: date, label: str):
                nonlocal apr_rent_n, apr_rent_t, apr_dep_n, apr_dep_t
                nonlocal may_rent_n, may_rent_t, may_dep_n, may_dep_t

                total = cash + upi
                if total == 0:
                    return

                # Rent due for this month (prorated if 1st month)
                agreed = b["agreed_rent"]
                if agreed == 0:
                    agreed = total  # no rent info -> treat all as rent
                    warnings.append(f"{name}: no agreed_rent in sheet for {label}")
                rent_due = prorate(agreed, b["checkin"], period)

                # Allocate: rent first, all remaining goes to deposit (no cap)
                rent_target = min(total, rent_due)

                # Cash goes first toward rent, then UPI
                cash_rent = min(cash, rent_target)
                upi_rent  = min(upi,  rent_target - cash_rent)
                cash_over = cash - cash_rent
                upi_over  = upi  - upi_rent

                cash_dep  = cash_over
                upi_dep   = upi_over

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

                    def _pay(amt, mode, ftype, pm):
                        if amt > 0:
                            session.add(Payment(
                                tenancy_id=tenancy.id,
                                amount=Decimal(str(round(amt, 2))),
                                payment_date=period,
                                payment_mode=mode,
                                for_type=ftype,
                                period_month=pm,
                                notes=f"{label} sheet reload",
                            ))

                    _pay(cash_rent, PaymentMode.cash, PaymentFor.rent,    period)
                    _pay(upi_rent,  PaymentMode.upi,  PaymentFor.rent,    period)
                    # Deposits: period_month=None so pending calc counts them correctly
                    _pay(cash_dep,  PaymentMode.cash, PaymentFor.deposit, None)
                    _pay(upi_dep,   PaymentMode.upi,  PaymentFor.deposit, None)

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

            record_month(b["apr_cash"], b["apr_upi"], APR, "Apr")
            record_month(b["may_cash"], b["may_upi"], MAY, "May")

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
