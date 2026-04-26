"""
scripts/audit_month.py
Monthly financial dashboard — active, exited, and no-show tenants.

Usage:
    python scripts/audit_month.py                    # current month
    python scripts/audit_month.py --month 2026-04    # specific month
    python scripts/audit_month.py --month 2026-04 --partial-only
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
    RentSchedule, Payment, PaymentFor,
)

DB = os.environ["DATABASE_URL"].replace("postgresql://", "postgresql+asyncpg://", 1)

HDR = (
    f"{'Room':<6} {'Name':<24} {'Status':<10} "
    f"{'Agreed':>7} {'Due':>9} {'Cash':>7} "
    f"{'UPI':>7} {'Prepaid':>8} {'Balance':>8} {'St':<5}"
)


async def main(period: date, partial_only: bool):
    if period.month == 12:
        next_period = date(period.year + 1, 1, 1)
    else:
        next_period = date(period.year, period.month + 1, 1)

    engine = create_async_engine(DB, echo=False)
    Sess   = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Sess() as s:

        # ── tenancy IDs with rent activity this period ─────────────────────
        tids_pay = {r[0] for r in (await s.execute(
            select(Payment.tenancy_id).where(
                Payment.period_month == period, Payment.is_void == False
            )
        )).all()}
        tids_rs = {r[0] for r in (await s.execute(
            select(RentSchedule.tenancy_id).where(RentSchedule.period_month == period)
        )).all()}
        tids_all = tids_pay | tids_rs

        # ── fetch all relevant tenancies ────────────────────────────────────
        rows = (await s.execute(
            select(Tenancy, Tenant, Room)
            .join(Tenant, Tenant.id == Tenancy.tenant_id)
            .join(Room,   Room.id  == Tenancy.room_id)
            .where(
                Tenancy.stay_type != StayType.daily,
                or_(
                    # active long-term tenants
                    Tenancy.status == TenancyStatus.active,
                    # exited during this month
                    and_(
                        Tenancy.status == TenancyStatus.exited,
                        Tenancy.checkout_date >= period,
                        Tenancy.checkout_date <  next_period,
                    ),
                    # all no-shows carry forward until receptionist checks them in
                    Tenancy.status == TenancyStatus.no_show,
                    # any tenancy with rent schedule / payment this period
                    Tenancy.id.in_(tids_all) if tids_all else False,
                )
            )
            .order_by(Room.room_number, Tenant.name)
        )).all()

        # ── rent schedules for this period ──────────────────────────────────
        rs_map = {
            rs.tenancy_id: rs
            for rs in (await s.execute(
                select(RentSchedule).where(RentSchedule.period_month == period)
            )).scalars().all()
        }

        # ── rent payments for this period ───────────────────────────────────
        pays = (await s.execute(
            select(Payment).where(
                Payment.period_month == period,
                Payment.is_void == False,
                Payment.for_type == PaymentFor.rent,
            )
        )).scalars().all()
        pay_map: dict[int, dict] = {}
        for p in pays:
            if p.tenancy_id not in pay_map:
                pay_map[p.tenancy_id] = {"cash": Decimal("0"), "upi": Decimal("0"), "prepaid": Decimal("0")}
            mode = (p.payment_mode.value if hasattr(p.payment_mode, "value") else str(p.payment_mode or "cash")).lower()
            in_period = p.payment_date and period <= p.payment_date < next_period
            if in_period:
                if mode in ("upi", "bank", "online", "neft", "imps"):
                    pay_map[p.tenancy_id]["upi"]  += p.amount
                else:
                    pay_map[p.tenancy_id]["cash"] += p.amount
            else:
                pay_map[p.tenancy_id]["prepaid"] += p.amount

        # ── booking payments for no-shows (all time — shows total committed) ─
        noshow_ten_ids = [t.id for t, _, _ in rows if t.status == TenancyStatus.no_show]
        noshow_bk_map: dict[int, Decimal] = {}
        if noshow_ten_ids:
            bk_pays = (await s.execute(
                select(Payment).where(
                    Payment.tenancy_id.in_(noshow_ten_ids),
                    Payment.is_void == False,
                    Payment.for_type == PaymentFor.booking,
                )
            )).scalars().all()
            for p in bk_pays:
                noshow_bk_map[p.tenancy_id] = noshow_bk_map.get(p.tenancy_id, Decimal("0")) + p.amount

        # ── print ───────────────────────────────────────────────────────────
        print(f"\n{'='*100}")
        print(f"  MONTHLY DASHBOARD — {period.strftime('%B %Y').upper()}")
        print(f"{'='*100}")
        print(HDR)
        print("-" * 100)

        tot_due = tot_cash = tot_upi = tot_prepaid = tot_bal = 0
        paid_n = partial_n = exit_n = noshow_n = 0

        for tenancy, tenant, room in rows:
            agreed = int(tenancy.agreed_rent or 0)

            # ── No-show row (carries forward until checked in) ───────────
            if tenancy.status == TenancyStatus.no_show:
                bk_paid  = int(noshow_bk_map.get(tenancy.id, Decimal("0")))
                deposit  = int(tenancy.security_deposit or 0)
                due      = deposit + agreed          # total to pay to move in
                balance  = due - bk_paid
                st = "NOSH"; noshow_n += 1
                tot_due  += due
                tot_upi  += bk_paid                 # booking advance (usually UPI)
                # Only count dues for no-shows whose check-in was due this month or earlier
                if tenancy.checkin_date < next_period:
                    tot_bal += max(0, balance)
                if not partial_only:
                    print(
                        f"{room.room_number:<6} {tenant.name[:24]:<24} {'no_show':<10} "
                        f"{agreed:>7,} {due:>9,} {0:>7,} "
                        f"{bk_paid:>7,} {0:>8,} {balance:>8,} {st:<5}"
                    )
                continue

            # ── Active / Exited row ──────────────────────────────────────
            rs      = rs_map.get(tenancy.id)
            pt      = pay_map.get(tenancy.id, {"cash": Decimal("0"), "upi": Decimal("0"), "prepaid": Decimal("0")})
            rent_due = int((rs.rent_due or 0) + (rs.adjustment or 0)) if rs else 0
            cash     = int(pt["cash"])
            upi      = int(pt["upi"])
            prepaid  = int(pt["prepaid"])
            balance  = rent_due - cash - upi - prepaid

            if tenancy.status == TenancyStatus.exited:
                st = "EXIT"; exit_n += 1
            elif balance > 0:
                st = "PART"; partial_n += 1
            else:
                st = "PAID"; paid_n += 1

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
                f"{agreed:>7,} {rent_due:>9,} {cash:>7,} "
                f"{upi:>7,} {prepaid:>8,} {balance:>8,} {st:<5}{flag}"
            )

        # ── Totals ───────────────────────────────────────────────────────────
        print("-" * 100)
        print(
            f"{'TOTAL':<41} "
            f"{'':>7} {tot_due:>9,} {tot_cash:>7,} "
            f"{tot_upi:>7,} {tot_prepaid:>8,} {tot_bal:>8,}"
        )
        print()
        print(f"PAID: {paid_n}   PARTIAL: {partial_n}   EXIT: {exit_n}   NO-SHOW: {noshow_n}")
        print(f"Total Collected (Cash+UPI):   Rs.{(tot_cash + tot_upi):>10,}")
        print(f"  of which — Cash:            Rs.{tot_cash:>10,}")
        print(f"  of which — UPI:             Rs.{tot_upi:>10,}")
        print(f"Total Pending (active):       Rs.{tot_bal:>10,}")
        print(f"Total Due (rent + no-show):   Rs.{tot_due:>10,}")

    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", default=None,
                        help="Month to audit: YYYY-MM (default: current month)")
    parser.add_argument("--partial-only", action="store_true",
                        help="Show only PARTIAL tenants")
    args = parser.parse_args()

    if args.month:
        try:
            period = date.fromisoformat(args.month + "-01")
        except ValueError:
            print(f"Bad --month format: {args.month}  (use YYYY-MM)")
            sys.exit(1)
    else:
        period = date.today().replace(day=1)

    asyncio.run(main(period, args.partial_only))
