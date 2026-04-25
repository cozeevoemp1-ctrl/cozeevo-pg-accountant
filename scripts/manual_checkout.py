"""
Manual checkout script — run once to complete a missed bot checkout.
Usage: python scripts/manual_checkout.py
"""
import asyncio, os, sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, text

DB_URL = os.environ["DATABASE_URL"]
engine = create_async_engine(DB_URL)
Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# ── Checkout params (edit these) ──────────────────────────────────────────────
TENANCY_ID        = 597
EXIT_DATE         = date(2026, 4, 25)
DEPOSIT_HELD      = 27000
DEDUCTIONS        = 5000      # damage/dues deducted from deposit
REFUND_AMOUNT     = 22000     # 27000 - 5000
CUPBOARD_KEY      = True
MAIN_KEY          = True
DAMAGE_NOTES      = "Deduction Rs.5,000 as per checkout form"
FINGERPRINT_DEL   = True
RECORDED_BY       = "7680814628"   # Lokesh
# ─────────────────────────────────────────────────────────────────────────────

async def run():
    from src.database.models import (
        Tenancy, TenancyStatus, CheckoutRecord, Refund, RefundStatus, Room, Tenant
    )

    async with Session() as s:
        tenancy = await s.get(Tenancy, TENANCY_ID)
        if not tenancy:
            print(f"ERROR: Tenancy {TENANCY_ID} not found")
            return

        if tenancy.status == TenancyStatus.exited:
            print("Already exited — nothing to do")
            return

        tenant = await s.get(Tenant, tenancy.tenant_id)
        room   = await s.get(Room,   tenancy.room_id)
        print(f"Tenant : {tenant.name if tenant else '?'}")
        print(f"Room   : {room.room_number if room else '?'}")
        print(f"Status : {tenancy.status}")
        print(f"Checkout date: {EXIT_DATE}")
        print(f"Deposit: {DEPOSIT_HELD}, Deductions: {DEDUCTIONS}, Refund: {REFUND_AMOUNT}")
        print()

        # Create CheckoutRecord
        existing_cr = await s.scalar(
            select(CheckoutRecord).where(CheckoutRecord.tenancy_id == TENANCY_ID)
        )
        if existing_cr:
            print("CheckoutRecord already exists — skipping record creation")
        else:
            cr = CheckoutRecord(
                tenancy_id=TENANCY_ID,
                cupboard_key_returned=CUPBOARD_KEY,
                main_key_returned=MAIN_KEY,
                damage_notes=DAMAGE_NOTES if DAMAGE_NOTES else None,
                pending_dues_amount=DEDUCTIONS,
                deposit_refunded_amount=REFUND_AMOUNT,
                deposit_refund_date=EXIT_DATE,
                actual_exit_date=EXIT_DATE,
                recorded_by=RECORDED_BY,
            )
            s.add(cr)
            print("  [ok] CheckoutRecord created")

        # Create Refund record
        s.add(Refund(
            tenancy_id  = TENANCY_ID,
            amount      = Decimal(str(REFUND_AMOUNT)),
            refund_date = EXIT_DATE,
            reason      = "deposit refund on checkout (manual — form-based)",
            status      = RefundStatus.pending,
            notes       = f"Manual checkout by {RECORDED_BY}. Physical form on file.",
        ))
        print("  [ok] Refund record created")

        # Mark tenancy exited
        tenancy.status        = TenancyStatus.exited
        tenancy.checkout_date = EXIT_DATE
        print("  [ok] Tenancy marked as exited")

        await s.commit()
        print("  [ok] DB committed")

        # Google Sheets write-back
        if room:
            try:
                from src.integrations.gsheets import record_checkout as gs_checkout
                notice_str = tenancy.notice_date.strftime("%d/%m/%Y") if tenancy.notice_date else None
                tenant_name = tenant.name if tenant else ""
                gs_r = await gs_checkout(
                    room.room_number,
                    tenant_name,
                    notice_str,
                    EXIT_DATE.strftime("%d/%m/%Y"),
                )
                if gs_r.get("success"):
                    print("  [ok] Sheet updated")
                else:
                    print(f"  [warn] Sheet update failed: {gs_r.get('error')}")
            except Exception as e:
                print(f"  [warn] Sheet error: {e}")

        print()
        print(f"Done. Soumya Agarwal (Room {room.room_number if room else '?'}) checked out on {EXIT_DATE}.")

asyncio.run(run())
