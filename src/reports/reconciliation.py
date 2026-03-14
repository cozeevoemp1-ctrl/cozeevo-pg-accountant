"""
Reconciliation engine — 100% deterministic, zero AI calls.
Computes daily / weekly / monthly summaries from the transactions table.
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from loguru import logger
from sqlalchemy import select, func, and_

from src.database.db_manager import get_session, get_monthly_summary
from src.database.models import Transaction, Category, Customer, Employee, TransactionType


class ReconciliationEngine:

    # ── Monthly ───────────────────────────────────────────────────────────

    async def monthly_reconcile(
        self, year: int, month: int, property_id: Optional[int] = None
    ) -> dict:
        _, last_day = monthrange(year, month)
        start = date(year, month, 1)
        end   = date(year, month, last_day)

        summary = await self._period_summary(start, end, property_id)
        summary["period"]      = "monthly"
        summary["year"]        = year
        summary["month"]       = month
        summary["month_name"]  = datetime(year, month, 1).strftime("%B %Y")
        summary["rent_summary"] = await self._rent_summary(start, end)
        summary["salary_summary"] = await self._salary_summary(start, end)

        logger.info(
            f"[Reconcile] {summary['month_name']} | "
            f"Income=₹{summary['total_income']:.0f} | "
            f"Expense=₹{summary['total_expense']:.0f} | "
            f"Net=₹{summary['net_income']:.0f}"
        )
        return summary

    # ── Weekly ────────────────────────────────────────────────────────────

    async def weekly_reconcile(self, ref_date: Optional[date] = None) -> dict:
        today = ref_date or date.today()
        start = today - timedelta(days=today.weekday())   # Monday
        end   = start + timedelta(days=6)                 # Sunday

        summary = await self._period_summary(start, end)
        summary["period"] = "weekly"
        summary["week_start"] = str(start)
        summary["week_end"]   = str(end)
        return summary

    # ── Daily ─────────────────────────────────────────────────────────────

    async def daily_reconcile(self, ref_date: Optional[date] = None) -> dict:
        target = ref_date or date.today()
        summary = await self._period_summary(target, target)
        summary["period"] = "daily"
        summary["date"]   = str(target)
        return summary

    # ── Core aggregation ──────────────────────────────────────────────────

    async def _period_summary(
        self, start: date, end: date, property_id: Optional[int] = None
    ) -> dict:
        async with get_session() as session:
            # Total income
            income = await session.scalar(
                select(func.sum(Transaction.amount)).where(
                    and_(
                        Transaction.date.between(start, end),
                        Transaction.txn_type == TransactionType.income,
                        Transaction.is_void == False,
                    )
                )
            ) or Decimal("0")

            # Total expense
            expense = await session.scalar(
                select(func.sum(Transaction.amount)).where(
                    and_(
                        Transaction.date.between(start, end),
                        Transaction.txn_type == TransactionType.expense,
                        Transaction.is_void == False,
                    )
                )
            ) or Decimal("0")

            # By category
            cat_rows = (await session.execute(
                select(
                    Category.name,
                    Transaction.txn_type,
                    func.sum(Transaction.amount).label("total"),
                    func.count(Transaction.id).label("count"),
                )
                .join(Category, Transaction.category_id == Category.id, isouter=True)
                .where(
                    and_(
                        Transaction.date.between(start, end),
                        Transaction.is_void == False,
                    )
                )
                .group_by(Category.name, Transaction.txn_type)
            )).all()

            by_category: dict[str, dict] = {}
            for cat_name, txn_type, total, count in cat_rows:
                cat_name = cat_name or "Uncategorized"
                if cat_name not in by_category:
                    by_category[cat_name] = {"income": 0.0, "expense": 0.0, "count": 0}
                by_category[cat_name][txn_type.value] += float(total or 0)
                by_category[cat_name]["count"] += count

            # Transaction count
            txn_count = await session.scalar(
                select(func.count(Transaction.id)).where(
                    and_(
                        Transaction.date.between(start, end),
                        Transaction.is_void == False,
                    )
                )
            ) or 0

        return {
            "start_date":    str(start),
            "end_date":      str(end),
            "total_income":  float(income),
            "total_expense": float(expense),
            "net_income":    float(income) - float(expense),
            "txn_count":     txn_count,
            "by_category":   by_category,
        }

    # ── Rent tracking ─────────────────────────────────────────────────────

    async def _rent_summary(self, start: date, end: date) -> dict:
        async with get_session() as session:
            rows = (await session.execute(
                select(Customer)
                .where(Customer.active == True)
            )).scalars().all()

            total_expected = sum(float(c.rent_amount or 0) for c in rows)

            # Find rent transactions for this period
            rent_cat = (await session.execute(
                select(Category).where(Category.name == "Rent")
            )).scalar_one_or_none()
            if not rent_cat:
                return {"expected": total_expected, "collected": 0.0, "pending": total_expected, "details": []}

            rent_txns = (await session.execute(
                select(Transaction).where(
                    and_(
                        Transaction.date.between(start, end),
                        Transaction.category_id == rent_cat.id,
                        Transaction.is_void == False,
                    )
                )
            )).scalars().all()

            collected = sum(float(t.amount) for t in rent_txns)
            paid_customer_ids = {t.customer_id for t in rent_txns if t.customer_id}

            details = []
            for c in rows:
                paid = c.id in paid_customer_ids
                details.append({
                    "customer": c.name,
                    "room": c.room_number,
                    "expected": float(c.rent_amount or 0),
                    "paid": paid,
                })

        return {
            "expected":  total_expected,
            "collected": collected,
            "pending":   max(0.0, total_expected - collected),
            "details":   details,
        }

    # ── Salary summary ────────────────────────────────────────────────────

    async def _salary_summary(self, start: date, end: date) -> dict:
        async with get_session() as session:
            rows = (await session.execute(
                select(Employee).where(Employee.active == True)
            )).scalars().all()

            total_expected = sum(float(e.monthly_salary or 0) for e in rows)

            sal_cat = (await session.execute(
                select(Category).where(Category.name == "Salary")
            )).scalar_one_or_none()

            if not sal_cat:
                return {"expected": total_expected, "paid": 0.0, "details": []}

            sal_txns = (await session.execute(
                select(Transaction).where(
                    and_(
                        Transaction.date.between(start, end),
                        Transaction.category_id == sal_cat.id,
                        Transaction.is_void == False,
                    )
                )
            )).scalars().all()

            paid_total = sum(float(t.amount) for t in sal_txns)
            paid_emp_ids = {t.employee_id for t in sal_txns if t.employee_id}

            details = [
                {
                    "employee": e.name,
                    "role": e.role,
                    "expected": float(e.monthly_salary or 0),
                    "paid": e.id in paid_emp_ids,
                }
                for e in rows
            ]

        return {"expected": total_expected, "paid": paid_total, "details": details}
