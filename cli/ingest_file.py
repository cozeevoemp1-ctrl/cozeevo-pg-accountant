"""
CLI: ingest-file <path>
Parses a CSV/PDF file and saves transactions to the database.
Interactive approval for new master-data entities.
"""
import asyncio
import sys
from pathlib import Path

import click
from dotenv import load_dotenv
from loguru import logger
from rich.console import Console
from rich.table import Table

load_dotenv()
console = Console(highlight=False)

# Windows terminal safe symbols
OK   = "[OK]"
WARN = "[!]"
DONE = "[DONE]"


@click.command("ingest-file")
@click.argument("file_path", type=click.Path(exists=True))
@click.option("--no-interactive", is_flag=True, help="Skip interactive approval prompts")
@click.option("--dry-run", is_flag=True, help="Parse only, do not save to database")
def ingest_file(file_path: str, no_interactive: bool, dry_run: bool):
    """
    Parse and ingest a payment file (CSV or PDF) into the PG Accountant database.

    Examples:\n
        python -m cli.ingest_file data/raw/phonepe_march.csv\n
        python -m cli.ingest_file data/raw/bank_hdfc.pdf --dry-run
    """
    asyncio.run(_ingest(file_path, no_interactive, dry_run))


async def _ingest(file_path: str, no_interactive: bool, dry_run: bool):
    from src.database.db_manager import init_db, get_category_by_name, upsert_transaction
    from src.parsers.dispatcher import parse_file
    from src.rules.deduplication import batch_deduplicate
    from src.rules.categorization_rules import classify_batch
    from src.agents.master_data_agent import detect_unknown_entities, prompt_approval_interactive
    import os

    db_url = os.getenv("DATABASE_URL", "sqlite:///./data/pg_accountant.db")
    await init_db(db_url)

    console.print(f"\n[bold cyan]Parsing:[/] {file_path}")

    # Parse
    raw = parse_file(file_path)
    console.print(f"[green]{OK}[/] Parsed {len(raw)} rows")

    # Deduplicate
    unique, dupes = batch_deduplicate(raw)
    if dupes:
        console.print(f"[yellow]{WARN}[/] Skipped {len(dupes)} duplicates")

    # Classify
    classified = classify_batch(unique)
    ai_needed = sum(1 for t in classified if t.get("needs_ai_review"))
    console.print(f"[green]{OK}[/] Classified {len(classified)} transactions ({ai_needed} need AI review)")

    if dry_run:
        _print_preview(classified)
        console.print("\n[yellow]Dry run — nothing saved.[/]")
        return

    # AI classification for flagged rows
    if ai_needed:
        from src.llm_gateway.claude_client import get_claude_client
        from src.database.db_manager import get_all_categories
        claude = get_claude_client()
        cats = [c.name for c in await get_all_categories()]
        for txn in classified:
            if txn.get("needs_ai_review"):
                result = await claude.classify_merchant(
                    description=txn.get("description", ""),
                    merchant=txn.get("merchant", ""),
                    date=str(txn.get("date", "")),
                    amount=float(txn.get("amount", 0)),
                    txn_type=txn.get("txn_type", "expense"),
                    categories=cats,
                )
                txn["category"]      = result["category"]
                txn["confidence"]    = result["confidence"]
                txn["ai_classified"] = True
        console.print(f"[green]{OK}[/] AI classified {ai_needed} transactions")

    # Interactive approval for new entities
    if not no_interactive:
        suggestions = await detect_unknown_entities(classified)
        if suggestions:
            await prompt_approval_interactive(suggestions)

    # Save to DB
    saved = skipped = 0
    for txn in classified:
        cat = await get_category_by_name(txn.get("category", "Miscellaneous"))
        txn_clean = {
            "date": txn.get("date"),
            "amount": txn.get("amount"),
            "txn_type": txn.get("txn_type"),
            "source": txn.get("source"),
            "description": txn.get("description"),
            "upi_reference": txn.get("upi_reference"),
            "merchant": txn.get("merchant"),
            "category_id": cat.id if cat else None,
            "unique_hash": txn.get("unique_hash"),
            "raw_data": txn.get("raw_data"),
            "ai_classified": txn.get("ai_classified", False),
            "confidence": txn.get("confidence", 1.0),
        }
        _, is_new = await upsert_transaction(txn_clean)
        if is_new:
            saved += 1
        else:
            skipped += 1

    console.print(f"\n[bold green]{DONE}[/] {saved} saved, {skipped} already existed.")


def _print_preview(transactions: list[dict]):
    table = Table(title="Preview (first 20 rows)", show_lines=True)
    table.add_column("Date",    style="cyan")
    table.add_column("Type",    style="magenta")
    table.add_column("Amount",  style="green")
    table.add_column("Merchant")
    table.add_column("Category")

    for t in transactions[:20]:
        table.add_row(
            str(t.get("date", "")),
            t.get("txn_type", ""),
            f"Rs.{float(t.get('amount', 0)):,.2f}",
            t.get("merchant", "")[:30],
            t.get("category", "?"),
        )
    console.print(table)


if __name__ == "__main__":
    ingest_file()
