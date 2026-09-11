"""Chit / hand-loan instalment register — `chit_payments` table.

Balance-sheet only: never an expense, never in the P&L (REPORTING.md 1.2).

  py -3 scripts/chit_payments.py list [--month 2026-09]
  py -3 scripts/chit_payments.py add --date 2026-09-05 --name Belandur --amount 50000 [--category Chit] [--mode cash] [--notes "..."]
  py -3 scripts/chit_payments.py void --id 7
  py -3 scripts/chit_payments.py seed             # Jul–Sep 2026 instalments from Kiran's list (idempotent)
"""
import argparse, asyncio, os, sys
from datetime import date
from decimal import Decimal
from dotenv import load_dotenv
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

from sqlalchemy import select
from src.database.db_manager import get_session, init_db_for_script
from src.database.models import ChitPayment
from src.utils.inr_format import inr

# Kiran 2026-09-11 (WhatsApp): the chit instalments actually paid so far.
SEED = [
    dict(payment_date=date(2026, 7, 9),  name="Belandur Balaji", category="Chit", amount=500000),
    dict(payment_date=date(2026, 7, 10), name="Boobalan",        category="Chit", amount=350000),
    dict(payment_date=date(2026, 8, 8),  name="Belandur Balaji", category="Chit", amount=500000),
    dict(payment_date=date(2026, 8, 9),  name="Boobalan",        category="Chit", amount=550000),
    dict(payment_date=date(2026, 9, 9),  name="Belandur Balaji", category="Chit", amount=500000),
    dict(payment_date=date(2026, 9, 11), name="Boobalan",        category="Chit", amount=550000),
]
SEED_NOTE = "entered from Kiran's list 2026-09-11"


async def _list(month: str | None):
    async with get_session() as s:
        q = select(ChitPayment).where(ChitPayment.is_void.is_(False)).order_by(ChitPayment.payment_date, ChitPayment.id)
        rows = (await s.execute(q)).scalars().all()
    if month:
        rows = [r for r in rows if r.payment_date.strftime("%Y-%m") == month]
    print(f"{'S.No':>4}  {'Date':10}  {'Name':14}  {'Category':8}  {'Amount':>12}  Mode   Notes")
    total = Decimal(0)
    for r in rows:
        total += r.amount
        print(f"{r.id:>4}  {r.payment_date}  {r.name:14}  {r.category:8}  {inr(r.amount):>12}  {r.payment_mode or '-':6} {r.notes or ''}")
    print(f"{'':4}  {'':10}  {'TOTAL':14}  {'':8}  {inr(total):>12}   ({len(rows)} rows)")


async def _add(a):
    async with get_session() as s:
        row = ChitPayment(payment_date=date.fromisoformat(a.date), name=a.name, category=a.category,
                          amount=Decimal(str(a.amount)), payment_mode=a.mode, notes=a.notes, created_by="cli")
        s.add(row)
        await s.commit()
        await s.refresh(row)
        print(f"added S.No {row.id}: {row.payment_date} {row.name} {row.category} {inr(row.amount)}")


async def _void(a):
    async with get_session() as s:
        row = await s.get(ChitPayment, a.id)
        if not row:
            sys.exit(f"no row id {a.id}")
        row.is_void = True
        await s.commit()
        print(f"voided S.No {a.id}: {row.payment_date} {row.name} {inr(row.amount)}")


async def _seed():
    async with get_session() as s:
        for d in SEED:
            exists = (await s.execute(select(ChitPayment).where(
                ChitPayment.payment_date == d["payment_date"], ChitPayment.name == d["name"],
                ChitPayment.amount == d["amount"]))).scalar_one_or_none()
            if exists:
                print(f"skip {d['name']} {inr(d['amount'])} (S.No {exists.id})")
                continue
            s.add(ChitPayment(**d, payment_mode="cash", notes=SEED_NOTE, created_by="seed"))
            print(f"add  {d['name']} {d['category']} {inr(d['amount'])}")
        await s.commit()


async def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    l = sub.add_parser("list"); l.add_argument("--month")
    a = sub.add_parser("add")
    a.add_argument("--date", required=True); a.add_argument("--name", required=True)
    a.add_argument("--amount", required=True, type=float); a.add_argument("--category", default="Chit")
    a.add_argument("--mode", default="cash", choices=["cash", "bank"]); a.add_argument("--notes")
    v = sub.add_parser("void"); v.add_argument("--id", required=True, type=int)
    sub.add_parser("seed")
    args = p.parse_args()
    await init_db_for_script(os.environ["DATABASE_URL"])
    if args.cmd == "list":       await _list(args.month)
    elif args.cmd == "add":      await _add(args)
    elif args.cmd == "void":     await _void(args)
    elif args.cmd == "seed":     await _seed()

if __name__ == "__main__":
    asyncio.run(main())
