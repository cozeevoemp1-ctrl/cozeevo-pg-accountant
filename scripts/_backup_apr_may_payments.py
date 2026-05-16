"""
Export all April + May 2026 payment records to a JSON backup file.
Run BEFORE any drop/reload operation.

Usage:
    python scripts/_backup_apr_may_payments.py
"""
import asyncio, os, sys, json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv; load_dotenv()

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from src.database.models import Payment

BACKUP_PATH = Path("scripts/_backup_apr_may_payments.json")
APR = date(2026, 4, 1)
JUN = date(2026, 6, 1)


def _serial(obj):
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return str(obj)
    raise TypeError(f"Not serializable: {type(obj)}")


async def main():
    url = os.environ["DATABASE_URL"]
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(url, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as session:
        rows = (await session.execute(
            select(Payment).where(
                Payment.period_month >= APR,
                Payment.period_month < JUN,
                Payment.is_void == False,
            ).order_by(Payment.id)
        )).scalars().all()

        records = []
        for p in rows:
            records.append({
                "id":           p.id,
                "tenancy_id":   p.tenancy_id,
                "amount":       str(p.amount),
                "payment_date": p.payment_date.isoformat() if p.payment_date else None,
                "payment_mode": p.payment_mode.value if p.payment_mode else None,
                "for_type":     p.for_type.value if p.for_type else None,
                "period_month": p.period_month.isoformat() if p.period_month else None,
                "notes":        p.notes,
                "is_void":      p.is_void,
            })

        BACKUP_PATH.write_text(json.dumps(records, indent=2, default=_serial), encoding="utf-8")

        apr_rows = [r for r in records if r["period_month"] and r["period_month"].startswith("2026-04")]
        may_rows = [r for r in records if r["period_month"] and r["period_month"].startswith("2026-05")]
        print(f"Backed up {len(records)} payments -> {BACKUP_PATH}")
        print(f"  April: {len(apr_rows)} rows  Rs.{sum(Decimal(r['amount']) for r in apr_rows):,}")
        print(f"  May:   {len(may_rows)} rows  Rs.{sum(Decimal(r['amount']) for r in may_rows):,}")

    await engine.dispose()


asyncio.run(main())
