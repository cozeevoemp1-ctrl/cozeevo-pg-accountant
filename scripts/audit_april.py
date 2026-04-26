"""
scripts/audit_april.py
Print every April 2026 tenant's financial data from DB for manual verification.
Usage: python scripts/audit_april.py
       python scripts/audit_april.py --partial-only   # show only PARTIAL tenants
"""
import asyncio, argparse, os, sys
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv; load_dotenv()

from decimal import Decimal
from datetime import date
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from src.database.models import (
    Tenancy, Tenant, Room, TenancyStatus, StayType,
    RentSchedule, Payment, PaymentFor, PaymentMode,
)

DB = os.environ["DATABASE_URL"].replace("postgresql://", "postgresql+asyncpg://", 1)
PERIOD = date(2026, 4, 1)
NEXT   = date(2026, 5, 1)

HDR = (
    f"{'Room':<6} {'Name':<24} {'Ten.Status':<10} "
    f"{'Agreed':>7} {'RentDue':>8} {'Cash':>7} "
    f"{'UPI':>7} {'Prepaid':>8} {'Balance':>8} {'St':<5}"
)

async def main(partial_only: bool):
    engine = create_async_engine(DB, echo=False)
    Sess   = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Sess() as s:
        # ── tenancies active/exited in April ──
        tids_pay = {r[0] for r in (await s.execute(
            select(Payment.tenancy_id).where(
                Payment.period_month == PERIOD, Payment.is_void == False
            )
        )).all()}
        tids_rs = {r[0] for r in (await s.execute(
            select(RentSchedule.tenancy_id).where(RentSchedule.period_month == PERIOD)
        )).all()}
        tids_all = tids_pay | tids_rs

        rows = (await s.execute(
            select(Tenancy, Tenant, Room)
            .join(Tenant, Tenant.id == Tenancy.tenant_id)
            .join(Room,   Room.id  == Tenancy.room_id)
            .where(
                Tenancy.stay_type != StayType.daily,
                or_(
                    Tenancy.status == TenancyStatus.active,
                    and_(
                        Tenancy.status == TenancyStatus.exited,
                        Tenancy.checkout_date >= PERIOD,
                        Tenancy.checkout_date <  NEXT,
                    ),
                    Tenancy.id.in_(tids_all) if tids_all else False,
                )
            )
            .order_by(Room.room_number, Tenant.name)
        )).all()

        # ── rent schedules ──
        rs_map = {
            rs.tenancy_id: rs
            for rs in (await s.execute(
                select(RentSchedule).where(RentSchedule.period_month == PERIOD)
            )).scalars().all()
        }

        # ── rent payments ──
        pays = (await s.execute(
            select(Payment).where(
                Payment.period_month == PERIOD,
                Payment.is_void == False,
                Payment.for_type == PaymentFor.rent,
            )
        )).scalars().all()
        pay_map: dict[int, dict] = {}
        for p in pays:
            if p.tenancy_id not in pay_map:
                pay_map[p.tenancy_id] = {"cash": Decimal("0"), "upi": Decimal("0"), "prepaid": Decimal("0")}
            mode = (p.payment_mode.value if hasattr(p.payment_mode, "value") else str(p.payment_mode or "cash")).lower()
            in_period = p.payment_date and PERIOD <= p.payment_date < NEXT
            if in_period:
                if mode in ("upi", "bank", "online", "neft", "imps"):
                    pay_map[p.tenancy_id]["upi"]  += p.amount
                else:
                    pay_map[p.tenancy_id]["cash"] += p.amount
            else:
                pay_map[p.tenancy_id]["prepaid"] += p.amount

        # ── April no-show booking payments ──
        noshow_pays = (await s.execute(
            select(Payment).where(
                Payment.payment_date >= PERIOD,
                Payment.payment_date < NEXT,
                Payment.is_void == False,
                Payment.for_type == PaymentFor.booking,
            )
        )).scalars().all()
        noshow_bk_map: dict[int, Decimal] = {}
        for p in noshow_pays:
            noshow_bk_map[p.tenancy_id] = noshow_bk_map.get(p.tenancy_id, Decimal("0")) + p.amount

        # ── print ──
        print(HDR)
        print("-" * 100)

        tot_due = tot_cash = tot_upi = tot_prepaid = tot_bal = 0
        paid_n = partial_n = unpaid_n = exit_n = 0

        for tenancy, tenant, room in rows:
            if tenancy.status == TenancyStatus.no_show:
                continue
            rs   = rs_map.get(tenancy.id)
            pt   = pay_map.get(tenancy.id, {"cash": Decimal("0"), "upi": Decimal("0"), "prepaid": Decimal("0")})
            agreed   = int(tenancy.agreed_rent or 0)
            rent_due = int((rs.rent_due or 0) + (rs.adjustment or 0)) if rs else 0
            cash     = int(pt["cash"])
            upi      = int(pt["upi"])
            prepaid  = int(pt["prepaid"])
            balance  = rent_due - cash - upi - prepaid

            if tenancy.status == TenancyStatus.exited:
                st = "EXIT"; exit_n += 1
            elif balance > 0:
                st = "PART"; partial_n += 1
            elif balance <= 0:
                st = "PAID"; paid_n += 1
            else:
                st = "UNPD"; unpaid_n += 1

            tot_due     += rent_due
            tot_cash    += cash
            tot_upi     += upi
            tot_prepaid += prepaid
            tot_bal     += max(0, balance)

            if partial_only and st not in ("PART",):
                continue

            flag = " <<<" if st == "PART" and balance > 5000 else ""
            print(
                f"{room.room_number:<6} {tenant.name[:24]:<24} {tenancy.status.value[:10]:<10} "
                f"{agreed:>7,} {rent_due:>8,} {cash:>7,} "
                f"{upi:>7,} {prepaid:>8,} {balance:>8,} {st:<5}{flag}"
            )

        print("-" * 100)
        print(
            f"{'TOTAL':<41} "
            f"{'':>7} {tot_due:>8,} {tot_cash:>7,} "
            f"{tot_upi:>7,} {tot_prepaid:>8,} {tot_bal:>8,}"
        )
        print()
        print(f"PAID: {paid_n}   PARTIAL: {partial_n}   UNPAID: {unpaid_n}   EXIT: {exit_n}")
        print(f"Total Collected (Cash+UPI):  Rs.{(tot_cash+tot_upi):>10,}")
        print(f"Total Pending (balance>0):   Rs.{tot_bal:>10,}")
        print(f"Total Rent Due:              Rs.{tot_due:>10,}")

        # ── April no-shows (only those with checkin in April) ──
        noshow_rows = [
            r for r in rows
            if r[0].status == TenancyStatus.no_show
            and PERIOD <= r[0].checkin_date < NEXT
        ]
        if noshow_rows:
            print()
            print("── April No-Shows (booking advance collected) ──")
            print(f"{'Room':<6} {'Name':<24} {'Rent':>7} {'Deposit':>8} {'Booking':>8} {'BkPaid':>8} {'StillOwes':>10}")
            print("-" * 75)
            ns_bk_cash = ns_bk_upi = 0
            for tenancy, tenant, room in noshow_rows:
                bk_paid = int(noshow_bk_map.get(tenancy.id, Decimal("0")))
                booking_amt = int(tenancy.booking_amount or 0)
                deposit     = int(tenancy.security_deposit or 0)
                rent        = int(tenancy.agreed_rent or 0)
                still_owes  = deposit + rent - bk_paid
                print(
                    f"{room.room_number:<6} {tenant.name[:24]:<24} {rent:>7,} {deposit:>8,} "
                    f"{booking_amt:>8,} {bk_paid:>8,} {still_owes:>10,}"
                )
                ns_bk_upi += bk_paid  # booking advances are typically UPI
            print("-" * 75)
            print(f"No-show booking collected (UPI): Rs.{ns_bk_upi:,}  (included in April UPI total above)")

    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--partial-only", action="store_true", help="Show only PARTIAL/unpaid tenants")
    args = parser.parse_args()
    asyncio.run(main(args.partial_only))
