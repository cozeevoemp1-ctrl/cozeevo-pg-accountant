"""
CLI: run-reconciliation
Runs daily / weekly / monthly reconciliation and prints results.
"""
import asyncio
import os
from datetime import datetime

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

load_dotenv()
console = Console(highlight=False)


@click.command("run-reconciliation")
@click.option("--period", type=click.Choice(["daily", "weekly", "monthly"]), default="monthly", show_default=True)
@click.option("--year",  type=int,  default=None, help="Year (for monthly, default=current)")
@click.option("--month", type=int,  default=None, help="Month 1-12 (for monthly, default=current)")
def run_reconciliation(period: str, year: int, month: int):
    """
    Run reconciliation for the specified period.

    Examples:\n
        python -m cli.run_reconciliation --period monthly\n
        python -m cli.run_reconciliation --period monthly --year 2025 --month 3\n
        python -m cli.run_reconciliation --period daily
    """
    asyncio.run(_reconcile(period, year, month))


async def _reconcile(period: str, year: int | None, month: int | None):
    from src.database.db_manager import init_db
    from src.reports.reconciliation import ReconciliationEngine

    db_url = os.getenv("DATABASE_URL", "sqlite:///./data/pg_accountant.db")
    await init_db(db_url)

    engine = ReconciliationEngine()
    now = datetime.now()
    y   = year  or now.year
    m   = month or now.month

    console.print(f"\n[bold cyan]Running {period} reconciliation...[/]")

    if period == "monthly":
        data = await engine.monthly_reconcile(y, m)
        label = data.get("month_name", f"{y}-{m:02d}")
    elif period == "weekly":
        data  = await engine.weekly_reconcile()
        label = f"Week {data.get('week_start')} → {data.get('week_end')}"
    else:
        data  = await engine.daily_reconcile()
        label = data.get("date", str(now.date()))

    # Print summary
    from src.reports.report_generator import ReportGenerator
    gen  = ReportGenerator()
    text = gen.format_text_summary(data, period)

    console.print(Panel(text, title=f"[bold]{label}[/]", expand=False))

    # Print rent details
    rent = data.get("rent_summary", {})
    if rent.get("details"):
        console.print("\n[bold]Rent Details:[/]")
        for d in rent["details"]:
            status = "[green]Paid[/]" if d["paid"] else "[red]Pending[/]"
            console.print(f"  {d['customer']:25s} Room {d.get('room','?'):5s} Rs.{d['expected']:,.0f}  {status}")

    # Print salary details
    sal = data.get("salary_summary", {})
    if sal.get("details"):
        console.print("\n[bold]Salary Details:[/]")
        for d in sal["details"]:
            status = "[green]Paid[/]" if d["paid"] else "[red]Pending[/]"
            console.print(f"  {d['employee']:25s} {d.get('role',''):15s} Rs.{d['expected']:,.0f}  {status}")


if __name__ == "__main__":
    run_reconciliation()
