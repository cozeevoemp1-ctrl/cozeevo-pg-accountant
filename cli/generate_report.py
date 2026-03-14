"""
CLI: generate-report
Generates a report in text / CSV / Excel / dashboard format.
"""
import asyncio
import os
import webbrowser
from datetime import datetime

import click
from dotenv import load_dotenv
from rich.console import Console

load_dotenv()
console = Console(highlight=False)
OK = "[OK]"


@click.command("generate-report")
@click.option("--format",  "fmt", type=click.Choice(["text", "csv", "excel", "dashboard"]), default="text")
@click.option("--period",  type=click.Choice(["daily", "weekly", "monthly"]), default="monthly")
@click.option("--year",    type=int, default=None)
@click.option("--month",   type=int, default=None)
@click.option("--open",    "open_after", is_flag=True, help="Open in browser/file manager after generation")
def generate_report(fmt: str, period: str, year: int, month: int, open_after: bool):
    """
    Generate a PG Accountant report.

    Examples:\n
        python -m cli.generate_report --format dashboard --open\n
        python -m cli.generate_report --format excel --period monthly --month 3\n
        python -m cli.generate_report --format csv
    """
    asyncio.run(_generate(fmt, period, year, month, open_after))


async def _generate(fmt: str, period: str, year: int | None, month: int | None, open_after: bool):
    from src.database.db_manager import init_db
    from src.reports.reconciliation import ReconciliationEngine
    from src.reports.report_generator import ReportGenerator

    db_url = os.getenv("DATABASE_URL", "sqlite:///./data/pg_accountant.db")
    await init_db(db_url)

    engine = ReconciliationEngine()
    gen    = ReportGenerator()
    now    = datetime.now()
    y      = year  or now.year
    m      = month or now.month

    console.print(f"\n[bold cyan]Generating {fmt} report ({period})...[/]")

    if period == "monthly":
        data = await engine.monthly_reconcile(y, m)
    elif period == "weekly":
        data = await engine.weekly_reconcile()
    else:
        data = await engine.daily_reconcile()

    if fmt == "text":
        text = gen.format_text_summary(data, period)
        console.print(text)

    elif fmt == "csv":
        path = await gen.export_csv(data, period)
        console.print(f"[green][/] CSV exported: {path}")
        if open_after:
            _open_file(path)

    elif fmt == "excel":
        path = await gen.export_excel(data, period)
        console.print(f"[green][/] Excel exported: {path}")
        if open_after:
            _open_file(path)

    elif fmt == "dashboard":
        url = await gen.generate_dashboard(data, period)
        console.print(f"[green][/] Dashboard: {url}")
        if open_after:
            # Open local file directly
            import re
            filename = re.search(r"dashboard_\w+\.html", url)
            if filename:
                path = os.path.join(os.getenv("DASHBOARD_DIR", "./dashboards"), filename.group())
                webbrowser.open(f"file:///{os.path.abspath(path)}")


def _open_file(path: str):
    import subprocess, platform
    try:
        if platform.system() == "Windows":
            os.startfile(path)
        elif platform.system() == "Darwin":
            subprocess.run(["open", path])
        else:
            subprocess.run(["xdg-open", path])
    except Exception:
        pass


if __name__ == "__main__":
    generate_report()
