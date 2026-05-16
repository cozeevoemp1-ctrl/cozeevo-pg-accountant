"""
Fix April + May dues mismatches vs Google Sheet.

For each tenant whose sheet balance ≠ DB dues:
  correct_paid = RS rent_due − sheet_balance
  → void existing rent payments for that period
  → create one new payment for correct_paid

Usage:
  python scripts/_fix_apr_may_dues.py          # dry run
  python scripts/_fix_apr_may_dues.py --write  # commit
"""
import asyncio, os, sys, re, argparse
from decimal import Decimal
from datetime import date
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv; load_dotenv()

import gspread
from google.oauth2.service_account import Credentials
from sqlalchemy import text, select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from src.database.models import (
    Tenant, Tenancy, RentSchedule, Payment,
    TenancyStatus, PaymentMode, PaymentFor, RentStatus,
)

SOURCE_SHEET_ID = "1Vr_fSIOuuKBK4MWF-FVqgAIUPbqun3POszaXYfj-Ea0"
CREDS_FILE      = "credentials/gsheets_service_account.json"
APR = date(2026, 4, 1)
MAY = date(2026, 5, 1)
THRESHOLD = 50   # ignore diffs smaller than this

def pn(v):
    if not v: return 0
    try: return max(0, int(float(str(v).replace(",", ""))))
    except: return 0

def norm_phone(raw):
    d = re.sub(r"\D", "", str(raw or ""))
    if d.startswith("91") and len(d) == 12: d = d[2:]
    return f"+91{d}" if len(d) == 10 else ""


async def main(write: bool):
    tag = "WRITE" if write else "DRY RUN"
    print(f"{'='*65}")
    print(f"FIX APR+MAY DUES  [{tag}]")
    print(f"{'='*65}\n")

    # ── Read sheet ────────────────────────────────────────────────
    scopes = ["https://www.googleapis.com/auth/spreadsheets",
              "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_file(CREDS_FILE, scopes=scopes)
    gc = gspread.authorize(creds)
    ws = gc.open_by_key(SOURCE_SHEET_ID).worksheet("Long term")
    all_rows = ws.get_all_values()
    header = all_rows[0]
    col = {h.strip().lower(): i for i, h in enumerate(header)}

    url = os.environ["DATABASE_URL"].replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(url, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    fixes_applied = 0
    skipped = []

    async with Session() as session:
        session.autoflush = False
        if write:
            await session.execute(text("SET LOCAL app.allow_historical_write = 'true'"))

        for row in all_rows[1:]:
            name = row[col["name"]].strip() if "name" in col else ""
            if not name: continue
            phone = norm_phone(row[col["mobile number"]]) if "mobile number" in col else ""
            if not phone: continue

            apr_bal = pn(row[col["april balance"]]) if "april balance" in col else 0
            jun_bal = pn(row[col["june balance"]]) if "june balance" in col else 0

            if apr_bal == 0 and jun_bal == 0:
                continue

            # Resolve tenancy
            tenant = await session.scalar(
                select(Tenant).where(Tenant.phone == phone)
            )
            if not tenant:
                skipped.append(f"{name}: no tenant in DB")
                continue
            tenancy = await session.scalar(
                select(Tenancy).where(
                    Tenancy.tenant_id == tenant.id,
                    Tenancy.status == TenancyStatus.active,
                )
            )
            if not tenancy:
                skipped.append(f"{name}: no active tenancy")
                continue

            for period, sheet_balance in [(APR, apr_bal), (MAY, jun_bal)]:
                if sheet_balance == 0:
                    continue

                # Get RS for this period
                rs = await session.scalar(
                    select(RentSchedule).where(
                        RentSchedule.tenancy_id == tenancy.id,
                        RentSchedule.period_month == period,
                    )
                )
                if not rs:
                    skipped.append(f"{name}: no RS for {period} (owes {sheet_balance:,})")
                    continue

                eff_due = int(rs.rent_due + (rs.adjustment or 0))

                # Current rent paid for this period
                paid_rows = (await session.execute(
                    select(Payment).where(
                        Payment.tenancy_id == tenancy.id,
                        Payment.for_type == PaymentFor.rent,
                        Payment.period_month == period,
                        Payment.is_void == False,
                    )
                )).scalars().all()
                db_paid = sum(int(p.amount) for p in paid_rows)

                db_dues = max(0, eff_due - db_paid)
                diff = db_dues - sheet_balance

                if abs(diff) <= THRESHOLD:
                    continue  # already matching

                # Correct paid = eff_due - sheet_balance
                correct_paid = max(0, eff_due - sheet_balance)

                # Determine payment mode from sheet April columns
                apr_cash_sheet = pn(row[col.get("april cash", 99)]) if period == APR else pn(row[col.get("may cash", 99)])
                apr_upi_sheet  = pn(row[col.get("april upi",  99)]) if period == APR else pn(row[col.get("may upi",  99)])
                mode = PaymentMode.cash if apr_cash_sheet >= apr_upi_sheet else PaymentMode.upi

                period_label = "APR" if period == APR else "MAY"
                print(f"{period_label} {name:<30} eff_due={eff_due:>8,}  db_paid={db_paid:>8,}  "
                      f"db_dues={db_dues:>8,}  sheet_bal={sheet_balance:>8,}  diff={diff:>+8,}")
                print(f"    → void {len(paid_rows)} payment(s) totalling {db_paid:,}; "
                      f"create {correct_paid:,} {mode.value}")

                if write:
                    # Void existing rent payments for this period
                    for p in paid_rows:
                        p.is_void = True
                        session.add(p)

                    # Create correct payment (if > 0)
                    if correct_paid > 0:
                        session.add(Payment(
                            tenancy_id=tenancy.id,
                            amount=Decimal(str(correct_paid)),
                            payment_date=period,
                            payment_mode=mode,
                            for_type=PaymentFor.rent,
                            period_month=period,
                            notes="dues fix vs sheet balance",
                        ))

                    # Update RS status
                    if correct_paid >= eff_due:
                        rs.status = RentStatus.paid
                    elif correct_paid > 0:
                        rs.status = RentStatus.partial
                    else:
                        rs.status = RentStatus.pending
                    session.add(rs)

                fixes_applied += 1

        if write:
            await session.commit()

    await engine.dispose()

    print(f"\n{'='*65}")
    print(f"Fixes {'applied' if write else 'would apply'}: {fixes_applied}")
    if skipped:
        print(f"Skipped ({len(skipped)}):")
        for s in skipped: print(f"  - {s}")
    if not write:
        print("\n*** DRY RUN — re-run with --write to commit ***")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.write))
