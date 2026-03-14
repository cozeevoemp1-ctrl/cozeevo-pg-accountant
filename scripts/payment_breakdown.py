"""
Payment breakdown by mode + for_type — Feb and March 2026.
Run: PYTHONPATH=. PYTHONUTF8=1 venv/Scripts/python scripts/payment_breakdown.py
"""
import asyncio, os, sys
from datetime import date
from decimal import Decimal
from dotenv import load_dotenv
load_dotenv()

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from src.database.models import Payment, PaymentMode, PaymentFor

DATABASE_URL = os.environ["DATABASE_URL"]

MONTHS = [
    ("December 2025", date(2025, 12, 1), date(2025, 12, 31)),
    ("January 2026",  date(2026,  1, 1), date(2026,  1, 31)),
    ("February 2026", date(2026,  2, 1), date(2026,  2, 28)),
    ("March 2026",    date(2026,  3, 1), date(2026,  3, 31)),
]

async def main():
    engine = create_async_engine(DATABASE_URL, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as s:
        rows = (await s.execute(select(Payment))).scalars().all()

    await engine.dispose()

    W = 70
    for label, m_start, m_end in MONTHS:
        month_rows = [
            p for p in rows
            if m_start <= p.payment_date <= m_end
        ]

        print()
        print("=" * W)
        print(f"  {label}  —  ALL payments (incl. void)")
        print("=" * W)

        # By mode
        print(f"  {'Mode':<18} {'Non-void':>12} {'Void':>10} {'Total rows':>12}")
        print(f"  {'-'*55}")
        for mode in list(PaymentMode):
            mode_rows = [p for p in month_rows if p.payment_mode == mode]
            non_void = sum(p.amount for p in mode_rows if not p.is_void)
            void_amt = sum(p.amount for p in mode_rows if p.is_void)
            if mode_rows:
                print(f"  {mode.value:<18} {int(non_void):>12,} {int(void_amt):>10,} {len(mode_rows):>12}")

        # By for_type
        print()
        print(f"  {'For type':<18} {'Non-void':>12} {'Void':>10}")
        print(f"  {'-'*45}")
        for ft in list(PaymentFor):
            ft_rows = [p for p in month_rows if p.for_type == ft]
            non_void = sum(p.amount for p in ft_rows if not p.is_void)
            void_amt = sum(p.amount for p in ft_rows if p.is_void)
            if ft_rows:
                print(f"  {ft.value:<18} {int(non_void):>12,} {int(void_amt):>10,}")

        # Totals
        total_non_void = sum(p.amount for p in month_rows if not p.is_void)
        total_void     = sum(p.amount for p in month_rows if p.is_void)
        cash_upi       = sum(
            p.amount for p in month_rows
            if not p.is_void and p.payment_mode in (PaymentMode.cash, PaymentMode.upi)
        )
        print()
        print(f"  {'TOTAL non-void:':<28} Rs {int(total_non_void):>10,}")
        print(f"  {'TOTAL void (excluded):':<28} Rs {int(total_void):>10,}")
        print(f"  {'Cash + UPI only:':<28} Rs {int(cash_upi):>10,}")

    print()

if __name__ == "__main__":
    asyncio.run(main())
