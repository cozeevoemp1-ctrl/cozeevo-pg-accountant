"""
src/workers/gmail_poller.py
============================
Daily Gmail poller — reads bank statement emails, auto-reconciles UPI payments.

Run manually:      python -m src.workers.gmail_poller
Run via cron:      set up system cron (see docs/AUTOMATION.md)

Required .env vars:
  GMAIL_USER          — Gmail address that receives bank reports
  GMAIL_APP_PASSWORD  — Gmail app password (not account password)
                        Create at: myaccount.google.com/apppasswords
  HULK_EMAIL_SENDER   — sender address for HULK bank reports (or subject keyword)
  THOR_EMAIL_SENDER   — sender address for THOR bank reports (or subject keyword)
  HULK_EMAIL_SUBJECT  — subject keyword to identify HULK bank emails (e.g. "HULK")
  THOR_EMAIL_SUBJECT  — subject keyword to identify THOR bank emails (e.g. "THOR")
  ADMIN_WHATSAPP      — Kiran's number for unmatched alert (e.g. 917845952289)

How to set up bank email forwarding:
  1. Log in to UPI app / Yes Bank dashboard
  2. Enable "Daily collection report" email to GMAIL_USER
  3. For HULK account: set subject prefix "HULK" or use a dedicated email
  4. Test by uploading manually once via PWA first

Dedup: RRN unique constraint — re-processing the same email is always safe.
"""
from __future__ import annotations

import asyncio
import email
import imaplib
import logging
import os
import re
from datetime import date, datetime
from email.header import decode_header
from typing import Optional

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

GMAIL_USER         = os.getenv("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
HULK_EMAIL_SUBJECT = os.getenv("HULK_EMAIL_SUBJECT", "HULK")
THOR_EMAIL_SUBJECT = os.getenv("THOR_EMAIL_SUBJECT", "THOR")
ADMIN_WHATSAPP     = os.getenv("ADMIN_WHATSAPP", "917845952289")


# ── IMAP helpers ──────────────────────────────────────────────────────────────

def _connect_imap() -> imaplib.IMAP4_SSL:
    imap = imaplib.IMAP4_SSL("imap.gmail.com")
    imap.login(GMAIL_USER, GMAIL_APP_PASSWORD)
    return imap

def _decode_subject(raw: bytes) -> str:
    parts = decode_header(raw.decode() if isinstance(raw, bytes) else raw)
    decoded = []
    for chunk, enc in parts:
        if isinstance(chunk, bytes):
            decoded.append(chunk.decode(enc or "utf-8", errors="replace"))
        else:
            decoded.append(chunk)
    return " ".join(decoded)

def _identify_account(subject: str) -> Optional[str]:
    su = subject.upper()
    if HULK_EMAIL_SUBJECT.upper() in su: return "HULK"
    if THOR_EMAIL_SUBJECT.upper() in su: return "THOR"
    return None

def _get_attachment(msg: email.message.Message) -> tuple[Optional[bytes], Optional[str]]:
    """Return (file_bytes, filename) for first XLSX/CSV attachment."""
    for part in msg.walk():
        cd = part.get("Content-Disposition", "")
        if "attachment" not in cd: continue
        fname = part.get_filename() or ""
        if fname.lower().endswith((".xlsx", ".csv")):
            return part.get_payload(decode=True), fname
    return None, None

def fetch_today_bank_emails() -> list[tuple[str, bytes, str]]:
    """
    Returns list of (account_name, file_bytes, filename) for today's bank emails.
    Marks emails as read after processing.
    """
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        logger.warning("GMAIL_USER or GMAIL_APP_PASSWORD not set — skipping email fetch")
        return []

    results = []
    today_str = datetime.now().strftime("%d-%b-%Y")  # e.g. "11-May-2026"

    try:
        imap = _connect_imap()
        imap.select("INBOX")

        # Search unseen emails from today
        _, msg_ids = imap.search(None, f'(UNSEEN SINCE "{today_str}")')
        if not msg_ids[0]:
            logger.info("No unseen emails today")
            imap.logout()
            return []

        for mid in msg_ids[0].split():
            _, data = imap.fetch(mid, "(RFC822)")
            raw = data[0][1]
            msg = email.message_from_bytes(raw)
            subject = _decode_subject(msg.get("Subject", ""))
            account = _identify_account(subject)
            if not account:
                continue  # not a bank report email

            file_bytes, filename = _get_attachment(msg)
            if not file_bytes:
                logger.warning("Bank email found but no XLSX/CSV attachment: %s", subject)
                continue

            results.append((account, file_bytes, filename))
            imap.store(mid, "+FLAGS", "\\Seen")  # mark read
            logger.info("Fetched %s bank file from email: %s (%s bytes)", account, filename, len(file_bytes))

        imap.logout()
    except Exception:
        logger.exception("IMAP fetch failed")

    return results


# ── WhatsApp alert ────────────────────────────────────────────────────────────

async def _send_whatsapp_unmatched_alert(unmatched: list[dict], account: str, period: date) -> None:
    """Send Kiran a WhatsApp message listing unmatched UPI entries."""
    if not unmatched:
        return

    from src.integrations.whatsapp import send_text_message

    lines = [f"*UPI Reconcile — {account} {period.strftime('%b %Y')}*"]
    lines.append(f"{len(unmatched)} entries couldn't be matched to a tenant:\n")
    total = 0
    for e in sorted(unmatched, key=lambda x: -x["amount"])[:15]:
        lines.append(f"  Rs.{e['amount']:,.0f}  {e['payer_name']}")
        total += e["amount"]
    if len(unmatched) > 15:
        lines.append(f"  ...and {len(unmatched) - 15} more")
    lines.append(f"\n*Total unmatched: Rs.{total:,.0f}*")
    lines.append("Assign via app: Finance → Reconcile → Unmatched")

    msg = "\n".join(lines)
    try:
        await send_text_message(ADMIN_WHATSAPP, msg)
        logger.info("Sent unmatched alert to %s", ADMIN_WHATSAPP)
    except Exception:
        logger.exception("Failed to send WhatsApp unmatched alert")


# ── Main reconciliation run ───────────────────────────────────────────────────

async def run_daily_reconciliation(emails: Optional[list] = None) -> None:
    """
    Fetch today's bank emails and reconcile each one.
    Pass `emails` directly (list of (account, bytes, filename)) to skip IMAP fetch
    — used in tests and manual runs.
    """
    from src.database.db_manager import get_session
    from src.services.upi_reconciliation import reconcile_upi_file

    items = emails if emails is not None else fetch_today_bank_emails()
    if not items:
        logger.info("No bank emails to process today")
        return

    today = date.today()
    period = date(today.year, today.month, 1)

    for account_name, file_bytes, filename in items:
        logger.info("Reconciling %s — %s (%d bytes)", account_name, filename, len(file_bytes))
        try:
            async with get_session() as session:
                result = await reconcile_upi_file(
                    session, file_bytes, filename, account_name, period
                )

            logger.info(
                "%s: %d matched (Rs.%,.0f) | %d unmatched (Rs.%,.0f) | %d duplicates skipped",
                account_name, len(result.matched), result.matched_amount,
                len(result.unmatched), result.unmatched_amount, result.skipped_dup,
            )

            if result.unmatched:
                unmatched_dicts = [
                    {"amount": e.amount, "payer_name": e.payer_name, "vpa": e.payer_vpa}
                    for e in result.unmatched
                ]
                await _send_whatsapp_unmatched_alert(unmatched_dicts, account_name, period)

        except Exception:
            logger.exception("Reconciliation failed for %s — %s", account_name, filename)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(run_daily_reconciliation())
