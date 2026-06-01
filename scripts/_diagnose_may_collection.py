"""
Diagnostic: Why does PWA Money Dashboard differ from Google Sheet MAY Cash/UPI?

PWA method_breakdown = period-scoped (all payments tagged period_month=May,
                        regardless of when they were received)
Sheet MAY Cash/UPI   = date-scoped (payments received in May calendar,
                        period_month=May only; prepaid excluded from display cols)

This script shows:
1. Summary of the difference
2. Per-tenant breakdown (who paid early, who paid in May)
3. Any prior-month dues collected in May (not in PWA, not in Sheet Cash/UPI either)
"""

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal
from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from src.database.models import Payment, Tenancy, Tenant, Room, PaymentFor, PaymentMode

DATABASE_URL = os.environ["DATABASE_URL"]
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

_engine = create_async_engine(DATABASE_URL, echo=False)
_session_factory = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)

@asynccontextmanager
async def get_session():
    async with _session_factory() as session:
        yield session

MAY_START = date(2026, 5, 1)
MAY_END = date(2026, 5, 31)
PERIOD = date(2026, 5, 1)


def fmt(n):
    return f"Rs{int(n):,}"


async def main():
    async with get_session() as session:

        # --- All rent payments tagged for May 2026 ---
        may_payments = (await session.execute(
            select(Payment, Tenant.name, Room.room_number)
            .join(Tenancy, Tenancy.id == Payment.tenancy_id)
            .join(Tenant, Tenant.id == Tenancy.tenant_id)
            .join(Room, Room.id == Tenancy.room_id)
            .where(
                Payment.period_month == PERIOD,
                Payment.is_void == False,
                Payment.for_type == PaymentFor.rent,
            )
            .order_by(Room.room_number, Tenant.name, Payment.payment_date)
        )).all()

        # --- Prior dues collected IN May (in May by date, but for prior periods) ---
        prior_dues = (await session.execute(
            select(Payment, Tenant.name, Room.room_number)
            .join(Tenancy, Tenancy.id == Payment.tenancy_id)
            .join(Tenant, Tenant.id == Tenancy.tenant_id)
            .join(Room, Room.id == Tenancy.room_id)
            .where(
                Payment.payment_date >= MAY_START,
                Payment.payment_date <= MAY_END,
                Payment.is_void == False,
                Payment.for_type == PaymentFor.rent,
                Payment.period_month < PERIOD,
            )
            .order_by(Room.room_number, Tenant.name, Payment.payment_date)
        )).all()

        # ── Categorize May-tagged payments ──
        pwa_cash = Decimal("0")
        pwa_upi = Decimal("0")
        sheet_cash = Decimal("0")
        sheet_upi = Decimal("0")

        prepaid_rows = []    # paid before May 1 (in PWA, NOT in Sheet)
        paid_in_may_rows = []

        for pay, name, room in may_payments:
            mode = (pay.payment_mode.value if hasattr(pay.payment_mode, 'value') else str(pay.payment_mode or "cash")).lower()
            is_upi = mode in ("upi", "bank", "online", "neft", "imps", "bank_transfer")

            if is_upi:
                pwa_upi += pay.amount
            else:
                pwa_cash += pay.amount

            in_may = pay.payment_date is not None and MAY_START <= pay.payment_date <= MAY_END
            if in_may:
                if is_upi:
                    sheet_upi += pay.amount
                else:
                    sheet_cash += pay.amount
                paid_in_may_rows.append((pay, name, room))
            else:
                prepaid_rows.append((pay, name, room))

        # ── Print report ──
        print("=" * 65)
        print("MAY 2026 — PWA vs Sheet Cash/UPI Discrepancy Report")
        print("=" * 65)

        print("\n[1] SUMMARY")
        print(f"{'':30s} {'PWA':>12s}  {'Sheet':>12s}  {'Diff':>12s}")
        print(f"{'Cash':30s} {fmt(pwa_cash):>12s}  {fmt(sheet_cash):>12s}  {fmt(pwa_cash - sheet_cash):>12s}")
        print(f"{'UPI':30s} {fmt(pwa_upi):>12s}  {fmt(sheet_upi):>12s}  {fmt(pwa_upi - sheet_upi):>12s}")
        print(f"{'Total':30s} {fmt(pwa_cash+pwa_upi):>12s}  {fmt(sheet_cash+sheet_upi):>12s}  {fmt((pwa_cash+pwa_upi)-(sheet_cash+sheet_upi)):>12s}")

        print(f"\n[2] PREPAID PAYMENTS (in PWA, NOT in Sheet MAY Cash/UPI cols)")
        print(f"    These were tagged for May but payment_date is BEFORE May 1")
        if prepaid_rows:
            print(f"\n    {'Room':6s} {'Name':25s} {'Mode':8s} {'Amount':>10s} {'Pay Date':12s}")
            print(f"    {'-'*6} {'-'*25} {'-'*8} {'-'*10} {'-'*12}")
            pre_total = Decimal("0")
            for pay, name, room in prepaid_rows:
                mode = (pay.payment_mode.value if hasattr(pay.payment_mode, 'value') else str(pay.payment_mode or "cash")).lower()
                pre_total += pay.amount
                print(f"    {str(room):6s} {str(name):25s} {mode:8s} {fmt(pay.amount):>10s} {str(pay.payment_date):12s}")
            print(f"    {'':6s} {'TOTAL':25s} {'':8s} {fmt(pre_total):>10s}")
        else:
            print("    None found — no prepaid entries for May")

        print(f"\n[3] MAY PAYMENTS (in both PWA and Sheet) — sanity check sample")
        print(f"    These were tagged for May AND received in May")
        if paid_in_may_rows:
            print(f"\n    {'Room':6s} {'Name':25s} {'Mode':8s} {'Amount':>10s} {'Pay Date':12s}")
            print(f"    {'-'*6} {'-'*25} {'-'*8} {'-'*10} {'-'*12}")
            for pay, name, room in paid_in_may_rows[:50]:
                mode = (pay.payment_mode.value if hasattr(pay.payment_mode, 'value') else str(pay.payment_mode or "cash")).lower()
                print(f"    {str(room):6s} {str(name):25s} {mode:8s} {fmt(pay.amount):>10s} {str(pay.payment_date):12s}")
            if len(paid_in_may_rows) > 50:
                print(f"    ... ({len(paid_in_may_rows) - 50} more rows)")

        print(f"\n[4] PRIOR DUES COLLECTED IN MAY (NOT in PWA, NOT in Sheet May cols)")
        print(f"    payment_date in May but period_month < May (overdue catch-ups)")
        if prior_dues:
            print(f"\n    {'Room':6s} {'Name':25s} {'Mode':8s} {'Amount':>10s} {'Period':10s} {'Pay Date':12s}")
            print(f"    {'-'*6} {'-'*25} {'-'*8} {'-'*10} {'-'*10} {'-'*12}")
            prior_total = Decimal("0")
            for pay, name, room in prior_dues:
                mode = (pay.payment_mode.value if hasattr(pay.payment_mode, 'value') else str(pay.payment_mode or "cash")).lower()
                prior_total += pay.amount
                print(f"    {str(room):6s} {str(name):25s} {mode:8s} {fmt(pay.amount):>10s} {str(pay.period_month):10s} {str(pay.payment_date):12s}")
            print(f"    {'':6s} {'TOTAL':25s} {'':8s} {fmt(prior_total):>10s}")
        else:
            print("    None found")

        # Per-tenant comparison table
        print(f"\n[5] PER-TENANT BREAKDOWN (May-tagged payments)")
        print(f"\n    {'Room':6s} {'Name':25s} {'PWA UPI':>10s} {'PWA Cash':>10s} {'Sh UPI':>10s} {'Sh Cash':>10s} {'Prepaid':>10s}")
        print(f"    {'-'*6} {'-'*25} {'-'*10} {'-'*10} {'-'*10} {'-'*10} {'-'*10}")

        # Aggregate per tenancy
        tenant_agg = {}  # (tenancy_id, name, room) -> {pwa_upi, pwa_cash, sh_upi, sh_cash, prepaid}
        for pay, name, room in may_payments:
            key = (pay.tenancy_id, str(name), str(room))
            if key not in tenant_agg:
                tenant_agg[key] = {"pwa_upi": Decimal(0), "pwa_cash": Decimal(0),
                                   "sh_upi": Decimal(0), "sh_cash": Decimal(0), "prepaid": Decimal(0)}
            mode = (pay.payment_mode.value if hasattr(pay.payment_mode, 'value') else str(pay.payment_mode or "cash")).lower()
            is_upi = mode in ("upi", "bank", "online", "neft", "imps", "bank_transfer")
            in_may = pay.payment_date is not None and MAY_START <= pay.payment_date <= MAY_END

            if is_upi:
                tenant_agg[key]["pwa_upi"] += pay.amount
            else:
                tenant_agg[key]["pwa_cash"] += pay.amount

            if in_may:
                if is_upi:
                    tenant_agg[key]["sh_upi"] += pay.amount
                else:
                    tenant_agg[key]["sh_cash"] += pay.amount
            else:
                tenant_agg[key]["prepaid"] += pay.amount

        mismatch_rows = []
        for (tid, name, room), d in sorted(tenant_agg.items(), key=lambda x: x[0][2]):
            has_diff = d["prepaid"] > 0 or (d["pwa_upi"] != d["sh_upi"]) or (d["pwa_cash"] != d["sh_cash"])
            marker = " ***" if has_diff else ""
            print(f"    {room:6s} {name:25s} {fmt(d['pwa_upi']):>10s} {fmt(d['pwa_cash']):>10s} {fmt(d['sh_upi']):>10s} {fmt(d['sh_cash']):>10s} {fmt(d['prepaid']):>10s}{marker}")
            if has_diff:
                mismatch_rows.append((room, name, d))

        print(f"\n[6] MISMATCH SUMMARY — tenants where PWA ≠ Sheet")
        if mismatch_rows:
            for room, name, d in mismatch_rows:
                print(f"    Room {room} {name}:")
                if d["prepaid"] > 0:
                    print(f"      Prepaid {fmt(d['prepaid'])} → in PWA but NOT in Sheet Cash/UPI")
                if d["pwa_upi"] != d["sh_upi"]:
                    print(f"      UPI: PWA={fmt(d['pwa_upi'])} vs Sheet={fmt(d['sh_upi'])}")
                if d["pwa_cash"] != d["sh_cash"]:
                    print(f"      Cash: PWA={fmt(d['pwa_cash'])} vs Sheet={fmt(d['sh_cash'])}")
        else:
            print("    No mismatches found")

        print("\n" + "=" * 65)


if __name__ == "__main__":
    asyncio.run(main())
