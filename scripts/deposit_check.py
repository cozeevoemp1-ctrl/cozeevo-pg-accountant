"""
Deposit deep-dive — clarify what 'March deposits' means.
Run: PYTHONPATH=. PYTHONUTF8=1 venv/Scripts/python scripts/deposit_check.py
"""
import asyncio, os, sys
from datetime import date
from dotenv import load_dotenv
load_dotenv()

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from src.database.models import Payment, Tenancy, Tenant, PaymentFor, TenancyStatus

DATABASE_URL = os.environ["DATABASE_URL"]

MAR_START = date(2026, 3, 1)
MAR_END   = date(2026, 3, 31)
FEB_START = date(2026, 2, 1)
FEB_END   = date(2026, 2, 28)

async def main():
    engine = create_async_engine(DATABASE_URL, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as s:
        payments   = (await s.execute(select(Payment))).scalars().all()
        tenancies  = (await s.execute(select(Tenancy))).scalars().all()
        tenant_rows = (await s.execute(select(Tenant))).scalars().all()

    await engine.dispose()

    tenant_name = {t.id: t.name for t in tenant_rows}
    tenancy_map = {t.id: t for t in tenancies}

    deposits = [p for p in payments if p.for_type == PaymentFor.deposit and not p.is_void]

    W = 70
    # ── View 1: Deposits received IN March (payment_date in March) ───────────
    mar_received = [p for p in deposits if MAR_START <= p.payment_date <= MAR_END]
    print()
    print("=" * W)
    print("  VIEW 1 — Deposits where payment_date is in MARCH 2026")
    print("  (money physically received in March)")
    print("=" * W)
    print(f"  Count: {len(mar_received)}   Total: Rs {int(sum(p.amount for p in mar_received)):,}")
    print()
    print(f"  {'Tenant':<26} {'Amount':>10}  {'Pay Date':<12}  {'Checkin'}")
    print(f"  {'-'*60}")
    for p in sorted(mar_received, key=lambda x: x.payment_date):
        t = tenancy_map.get(p.tenancy_id)
        tname = tenant_name.get(t.tenant_id, "?") if t else "?"
        checkin = str(t.checkin_date) if t else "?"
        print(f"  {tname:<26} {int(p.amount):>10,}  {str(p.payment_date):<12}  {checkin}")

    # ── View 2: Deposits for tenants who CHECKED IN during March ─────────────
    mar_checkins = {t.id for t in tenancies if t.checkin_date and MAR_START <= t.checkin_date <= MAR_END}
    mar_checkin_deposits = [p for p in deposits if p.tenancy_id in mar_checkins]
    print()
    print("=" * W)
    print("  VIEW 2 — Deposits for tenants whose checkin_date is in MARCH 2026")
    print("  (regardless of when deposit was paid)")
    print("=" * W)
    print(f"  Count: {len(mar_checkin_deposits)}   Total: Rs {int(sum(p.amount for p in mar_checkin_deposits)):,}")
    print()
    print(f"  {'Tenant':<26} {'Amount':>10}  {'Pay Date':<12}  {'Checkin'}")
    print(f"  {'-'*60}")
    for p in sorted(mar_checkin_deposits, key=lambda x: x.payment_date):
        t = tenancy_map.get(p.tenancy_id)
        tname = tenant_name.get(t.tenant_id, "?") if t else "?"
        checkin = str(t.checkin_date) if t else "?"
        print(f"  {tname:<26} {int(p.amount):>10,}  {str(p.payment_date):<12}  {checkin}")

    # ── View 3: Total deposits currently held (all active tenants, ever) ─────
    active_ids = {t.id for t in tenancies if t.status == TenancyStatus.active}
    held_deposits = [p for p in deposits if p.tenancy_id in active_ids]
    print()
    print("=" * W)
    print("  VIEW 3 — Total deposits held right now (all active tenants, any date)")
    print("=" * W)
    print(f"  Active tenancies: {len(active_ids)}")
    print(f"  Deposit payments: {len(held_deposits)}")
    print(f"  Total held:       Rs {int(sum(p.amount for p in held_deposits)):,}")

    # ── View 4: Feb vs March cross — paid in Feb for March checkins ───────────
    paid_feb_checkin_mar = [
        p for p in deposits
        if FEB_START <= p.payment_date <= FEB_END
        and p.tenancy_id in mar_checkins
    ]
    print()
    print("=" * W)
    print("  VIEW 4 — Paid in FEB but checkin in MARCH (advance deposits)")
    print("=" * W)
    print(f"  Count: {len(paid_feb_checkin_mar)}   Total: Rs {int(sum(p.amount for p in paid_feb_checkin_mar)):,}")
    for p in paid_feb_checkin_mar:
        t = tenancy_map.get(p.tenancy_id)
        tname = tenant_name.get(t.tenant_id, "?") if t else "?"
        checkin = str(t.checkin_date) if t else "?"
        print(f"    {tname:<26} Rs {int(p.amount):>8,}  paid {p.payment_date}  checkin {checkin}")

    print()

if __name__ == "__main__":
    asyncio.run(main())
