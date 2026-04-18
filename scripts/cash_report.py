"""
scripts/cash_report.py
=======================
Standard cash collection report — single source of truth.

Run: venv/Scripts/python scripts/cash_report.py [--all] [--month YYYY-MM]

Default: shows cash RENT collections by month (excludes deposits + booking advances)
--all: shows all cash by for_type (rent / booking / deposit / maintenance)
--month: show one month detailed (every txn)
"""
import asyncio
import os
import sys
from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import select, func, extract
from src.database.db_manager import init_engine, get_session
from src.database.models import Payment, PaymentMode, PaymentFor, Tenancy, Tenant, Room


async def show_summary(s, mode_filter=None):
    """Cash summary by for_type x month."""
    rows = await s.execute(
        select(
            extract("year", Payment.payment_date).label("y"),
            extract("month", Payment.payment_date).label("m"),
            Payment.for_type,
            func.sum(Payment.amount),
            func.count(Payment.id),
        )
        .where(
            Payment.payment_mode == PaymentMode.cash,
            Payment.is_void == False,
        )
        .group_by("y", "m", Payment.for_type)
        .order_by("y", "m")
    )
    from collections import defaultdict

    data = defaultdict(lambda: defaultdict(lambda: [0.0, 0]))
    for y, m, ft, amt, cnt in rows.all():
        key = f"{int(y)}-{int(m):02d}"
        ft_label = ft.value if ft else "unknown"
        data[key][ft_label] = [float(amt or 0), cnt]

    print(f"{'Month':<10}{'Rent':>14}{'Deposit':>14}{'Booking':>14}{'Other':>14}{'TOTAL':>14}")
    print("-" * 80)
    grand = {"rent": 0, "deposit": 0, "booking": 0, "other": 0}
    for k in sorted(data):
        rent = data[k].get("rent", [0, 0])[0]
        dep = data[k].get("deposit", [0, 0])[0]
        bk = data[k].get("booking", [0, 0])[0]
        other = sum(v[0] for ft, v in data[k].items() if ft not in ("rent", "deposit", "booking"))
        tot = rent + dep + bk + other
        grand["rent"] += rent
        grand["deposit"] += dep
        grand["booking"] += bk
        grand["other"] += other
        print(f"{k:<10}{rent:>14,.0f}{dep:>14,.0f}{bk:>14,.0f}{other:>14,.0f}{tot:>14,.0f}")
    gtot = sum(grand.values())
    print("-" * 80)
    print(
        f"{'TOTAL':<10}{grand['rent']:>14,.0f}{grand['deposit']:>14,.0f}"
        f"{grand['booking']:>14,.0f}{grand['other']:>14,.0f}{gtot:>14,.0f}"
    )


async def show_month_detail(s, year_month):
    y, m = map(int, year_month.split("-"))
    rows = await s.execute(
        select(Payment, Tenant.name, Room.room_number)
        .join(Tenancy, Payment.tenancy_id == Tenancy.id)
        .join(Tenant, Tenancy.tenant_id == Tenant.id)
        .join(Room, Tenancy.room_id == Room.id, isouter=True)
        .where(
            extract("year", Payment.payment_date) == y,
            extract("month", Payment.payment_date) == m,
            Payment.payment_mode == PaymentMode.cash,
            Payment.is_void == False,
            Payment.for_type == PaymentFor.rent,
        )
        .order_by(Payment.payment_date, Payment.id)
    )
    print(f"\nCASH RENT DETAIL — {year_month}")
    print("-" * 90)
    print(f"{'Date':<12}{'Room':<8}{'Tenant':<28}{'Amount':>12}  Notes")
    print("-" * 90)
    total = 0
    for p, name, room in rows.all():
        amt = float(p.amount)
        total += amt
        room_str = str(room or "")[:7]
        print(
            f"{p.payment_date.isoformat():<12}{room_str:<8}{(name or '')[:27]:<28}"
            f"{amt:>12,.0f}  {(p.notes or '')[:40]}"
        )
    print("-" * 90)
    print(f"{'TOTAL':<48}  Rs.{total:>10,.0f}")


async def main():
    init_engine(os.getenv("DATABASE_URL"))

    show_all = "--all" in sys.argv
    month = None
    if "--month" in sys.argv:
        idx = sys.argv.index("--month")
        if idx + 1 < len(sys.argv):
            month = sys.argv[idx + 1]

    async with get_session() as s:
        if month:
            await show_month_detail(s, month)
        else:
            print("CASH COLLECTIONS BY MONTH (DB)")
            print("=" * 80)
            await show_summary(s)
            print()
            print("Notes:")
            print("  - 'Rent' = actual monthly rent collected in cash")
            print("  - 'Deposit' = security deposit (one-time, at check-in)")
            print("  - 'Booking' = booking advance (refundable at check-in)")
            print("  - For monthly cash sales: read the 'Rent' column only")


if __name__ == "__main__":
    asyncio.run(main())
