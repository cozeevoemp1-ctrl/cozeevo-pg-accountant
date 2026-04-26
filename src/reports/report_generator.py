"""
Report generator — text summaries, CSV, Excel, and HTML dashboard.
Pure deterministic Python, no AI.
"""
from __future__ import annotations

import csv
import io
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger


class ReportGenerator:
    def __init__(self):
        self.exports_dir = Path(os.getenv("DATA_EXPORTS_DIR", "./data/exports"))
        self.exports_dir.mkdir(parents=True, exist_ok=True)

    # ── Text summary ──────────────────────────────────────────────────────

    def format_text_summary(self, data: dict, period: str = "monthly") -> str:
        period_label = data.get("month_name") or data.get("date") or period.title()
        lines = [
            f"📊 *{period_label} Summary*",
            f"",
            f"💰 Income:   ₹{data.get('total_income', 0):,.0f}",
            f"💸 Expenses: ₹{data.get('total_expense', 0):,.0f}",
            f"📈 Net:      ₹{data.get('net_income', 0):,.0f}",
            f"🔢 Transactions: {data.get('txn_count', 0)}",
        ]

        # Category breakdown
        by_cat = data.get("by_category", {})
        if by_cat:
            lines.append("")
            lines.append("*Category Breakdown:*")
            for cat, vals in sorted(by_cat.items(), key=lambda x: x[1].get("expense", 0), reverse=True):
                exp = vals.get("expense", 0)
                inc = vals.get("income", 0)
                if exp > 0:
                    lines.append(f"  • {cat}: ₹{exp:,.0f}")
                elif inc > 0:
                    lines.append(f"  • {cat} (income): ₹{inc:,.0f}")

        # Rent
        rent = data.get("rent_summary", {})
        if rent:
            lines += [
                "",
                f"*Rent Collection:*",
                f"  Expected: ₹{rent.get('expected', 0):,.0f}",
                f"  Collected: ₹{rent.get('collected', 0):,.0f}",
                f"  Pending: ₹{rent.get('pending', 0):,.0f}",
            ]
            pending_tenants = [d["customer"] for d in rent.get("details", []) if not d["paid"]]
            if pending_tenants:
                lines.append(f"  Pending tenants: {', '.join(pending_tenants)}")

        # Salary
        sal = data.get("salary_summary", {})
        if sal:
            lines += [
                "",
                f"*Salary Payments:*",
                f"  Expected: ₹{sal.get('expected', 0):,.0f}",
                f"  Paid:     ₹{sal.get('paid', 0):,.0f}",
            ]

        return "\n".join(lines)

    # ── CSV export ────────────────────────────────────────────────────────

    async def export_csv(self, data: dict, period: str = "monthly") -> str:
        filename = f"report_{period}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        out_path = self.exports_dir / filename

        by_cat = data.get("by_category", {})
        rows = []
        for cat, vals in by_cat.items():
            rows.append({
                "Category": cat,
                "Income (₹)": vals.get("income", 0),
                "Expense (₹)": vals.get("expense", 0),
                "Net (₹)": vals.get("income", 0) - vals.get("expense", 0),
                "Transaction Count": vals.get("count", 0),
            })

        with open(out_path, "w", newline="", encoding="utf-8") as f:
            if rows:
                writer = csv.DictWriter(f, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)
            # Summary row
            f.write(f"\nTotal Income,{data.get('total_income', 0)}\n")
            f.write(f"Total Expense,{data.get('total_expense', 0)}\n")
            f.write(f"Net Income,{data.get('net_income', 0)}\n")

        logger.info(f"CSV exported: {out_path}")
        return str(out_path)

    # ── Excel export ──────────────────────────────────────────────────────

    async def export_excel(self, data: dict, period: str = "monthly") -> str:
        from src.reports.excel_exporter import ExcelExporter
        exporter = ExcelExporter(self.exports_dir)
        return await exporter.export(data, period)

