"""
Restore April + May 2026 payments from the JSON backup created by _backup_apr_may_payments.py.
This VOIDS all current Apr+May payments first, then re-inserts the backup records.

Usage:
    python scripts/_restore_apr_may_payments.py --confirm
"""
import asyncio
import json
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select, update

from src.database.db_manager import get_session
from src.database.models import Payment, PaymentMode, PaymentFor


BACKUP_PATH = Path("scripts/_backup_apr_may_payments.json")
APR = date(2026, 4, 1)
JUN = date(2026, 6, 1)


async def main():
    if "--confirm" not in sys.argv:
        print("Safety: pass --confirm to run restore")
        return

    if not BACKUP_PATH.exists():
        print(f"Backup file not found: {BACKUP_PATH}")
        return

    records = json.loads(BACKUP_PATH.read_text(encoding="utf-8"))
    print(f"Restoring {len(records)} payments from backup…")

    async with get_session() as session:
        # Void all current Apr+May payments
        voided = await session.execute(
            update(Payment)
            .where(
                Payment.period_month >= APR,
                Payment.period_month < JUN,
                Payment.is_void == False,
            )
            .values(is_void=True, notes="voided by restore script")
        )
        print(f"  Voided {voided.rowcount} existing payments")

        # Re-insert backup records
        for r in records:
            session.add(Payment(
                tenancy_id=r["tenancy_id"],
                amount=Decimal(r["amount"]),
                payment_date=date.fromisoformat(r["payment_date"]) if r["payment_date"] else None,
                payment_mode=PaymentMode(r["payment_mode"]) if r["payment_mode"] else None,
                for_type=PaymentFor(r["for_type"]) if r["for_type"] else None,
                period_month=date.fromisoformat(r["period_month"]) if r["period_month"] else None,
                notes=f"[RESTORED] {r['notes'] or ''}".strip(),
                is_void=False,
            ))

        await session.commit()
        print(f"  Restored {len(records)} payments. Done.")


asyncio.run(main())
