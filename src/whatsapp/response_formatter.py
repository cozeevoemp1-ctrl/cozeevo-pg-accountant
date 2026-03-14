"""
WhatsApp response formatter.
WhatsApp supports limited markdown: *bold*, _italic_, ~strikethrough~, ```code```
Max message length: 4096 chars (we cap at 1600 for reliability).
"""
from __future__ import annotations

import re

MAX_LENGTH = 1600


def format_response(text: str) -> str:
    """Ensure the response fits WhatsApp constraints."""
    if not text:
        return "Done ✓"
    # Convert markdown headers (##) to bold
    text = re.sub(r"^#{1,3}\s+(.+)$", r"*\1*", text, flags=re.MULTILINE)
    # Trim to max length
    if len(text) > MAX_LENGTH:
        text = text[:MAX_LENGTH - 50] + "\n\n_(truncated — use 'export csv' for full data)_"
    return text.strip()


def format_help_message() -> str:
    return (
        "*PG Accountant Commands*\n\n"
        "📊 *Reports*\n"
        "  • `show march summary`\n"
        "  • `weekly report`\n"
        "  • `today's summary`\n\n"
        "💾 *Exports*\n"
        "  • `export expenses csv`\n"
        "  • `export excel`\n"
        "  • `show dashboard`\n\n"
        "🏠 *Rent*\n"
        "  • `show rent collected`\n"
        "  • `rent pending this month`\n\n"
        "👥 *Master Data*\n"
        "  • `approve <id>`\n"
        "  • `reject <id>`\n\n"
        "📂 *File Ingestion*\n"
        "  • Send a PDF/CSV file directly\n"
    )
