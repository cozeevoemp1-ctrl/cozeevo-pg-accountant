"""Chit / hand-loan instalment register — single source for the `chit_payments`
table. Used by scripts/chit_payments.py (CLI) and the WhatsApp chit handler.

Balance-sheet only: never an expense, never in the P&L (REPORTING.md 1.2).
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import ChitPayment

# ── HARD BOUNDARY (Kiran 2026-09-11): only these two numbers may log, query or
# void chit payments over WhatsApp. Not owners, not receptionist, not env-configurable.
CHIT_PHONES: frozenset[str] = frozenset({
    "7845952289",   # Kiran
    "9444296681",   # Prabhakaran
})


def phone_allowed(phone: str) -> bool:
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    return digits in CHIT_PHONES


# ── Reads ─────────────────────────────────────────────────────────────────────

async def list_payments(session: AsyncSession, *, month: str | None = None,
                        name: str | None = None, limit: int | None = None) -> list[ChitPayment]:
    q = select(ChitPayment).where(ChitPayment.is_void.is_(False))
    if month:
        y, m = (int(x) for x in month.split("-"))
        start = date(y, m, 1)
        end = date(y + (m == 12), (m % 12) + 1, 1)
        q = q.where(ChitPayment.payment_date >= start, ChitPayment.payment_date < end)
    if name:
        q = q.where(ChitPayment.name.ilike(f"%{name}%"))
    q = q.order_by(ChitPayment.payment_date.desc(), ChitPayment.id.desc())
    if limit:
        q = q.limit(limit)
    rows = list((await session.execute(q)).scalars().all())
    rows.reverse()  # chronological
    return rows


async def totals_by_name(session: AsyncSession) -> list[tuple[str, int, Decimal]]:
    q = (select(ChitPayment.name, func.count(), func.sum(ChitPayment.amount))
         .where(ChitPayment.is_void.is_(False)).group_by(ChitPayment.name).order_by(ChitPayment.name))
    return [(n, c, Decimal(s)) for n, c, s in (await session.execute(q)).all()]


async def known_names(session: AsyncSession) -> list[str]:
    q = select(ChitPayment.name).where(ChitPayment.is_void.is_(False)).distinct()
    return [r[0] for r in (await session.execute(q)).all()]


async def canonical_name(session: AsyncSession, typed: str) -> str:
    """'boobalan' → 'Boobalan', 'belandur' → 'Belandur Balaji'. Unknown → title-cased input."""
    t = typed.strip().lower()
    for n in await known_names(session):
        nl = n.lower()
        if t == nl or nl.startswith(t) or t in nl.split() or any(w.startswith(t) for w in nl.split()):
            return n
    return typed.strip().title()


# ── Writes ────────────────────────────────────────────────────────────────────

async def add_payment(session: AsyncSession, *, payment_date: date, name: str, amount: Decimal,
                      category: str = "Chit", payment_mode: str = "cash", notes: str | None = None,
                      created_by: str | None = None) -> ChitPayment:
    row = ChitPayment(payment_date=payment_date, name=name, category=category, amount=amount,
                      payment_mode=payment_mode, notes=notes, created_by=created_by)
    session.add(row)
    await session.flush()
    return row


async def void_payment(session: AsyncSession, row_id: int) -> ChitPayment | None:
    row = await session.get(ChitPayment, row_id)
    if not row or row.is_void:
        return None
    row.is_void = True
    await session.flush()
    return row


# ── Natural-language parsing (shared so CLI and bot agree) ────────────────────

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_MONTH_RE = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"

AMOUNT_RE = re.compile(
    r"(?:rs\.?|inr|₹)?\s*(\d+(?:,\d+)*(?:\.\d+)?)\s*(lakhs?|lacs?|lakh|lac|l\b|k\b|thousand)?", re.I)


def parse_amount(text: str) -> Decimal | None:
    """'5.5L' / '5,50,000' / '3.5 lakh' / '50k' → Decimal. Ignores day numbers like '9 sep'."""
    best = None
    for m in AMOUNT_RE.finditer(text):
        num = Decimal(m.group(1).replace(",", ""))
        unit = (m.group(2) or "").lower()
        if unit.startswith("l"):
            num *= 100000
        elif unit.startswith("k") or unit == "thousand":
            num *= 1000
        elif num < 1000:
            continue  # a day-of-month or S.No, not money
        if best is None or num > best:
            best = num
    return best


def parse_date(text: str, today: date | None = None) -> tuple[date, str]:
    """Returns (date, matched_text). Defaults to today when nothing matches."""
    today = today or date.today()
    t = text.lower()
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", t)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3))), m.group(0)
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", t)
    if m:
        y = int(m.group(3)) if m.group(3) else today.year
        y = y + 2000 if y < 100 else y
        return date(y, int(m.group(2)), int(m.group(1))), m.group(0)
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+" + _MONTH_RE + r"(?:\s+(\d{4}))?\b", t)
    if m:
        y = int(m.group(3)) if m.group(3) else today.year
        return date(y, _MONTHS[m.group(2)[:3]], int(m.group(1))), m.group(0)
    m = re.search(r"\b" + _MONTH_RE + r"\s+(\d{1,2})(?:st|nd|rd|th)?(?:\s+(\d{4}))?\b", t)
    if m:
        y = int(m.group(3)) if m.group(3) else today.year
        return date(y, _MONTHS[m.group(1)[:3]], int(m.group(2))), m.group(0)
    if "yesterday" in t:
        return today - timedelta(days=1), "yesterday"
    if "today" in t:
        return today, "today"
    return today, ""


def parse_month(text: str, today: date | None = None) -> str | None:
    """'sep' / 'september 2026' / 'this month' / 'last month' → 'YYYY-MM' or None."""
    today = today or date.today()
    t = text.lower()
    if "this month" in t:
        return today.strftime("%Y-%m")
    if "last month" in t:
        first = today.replace(day=1) - timedelta(days=1)
        return first.strftime("%Y-%m")
    m = re.search(r"\b" + _MONTH_RE + r"(?:\s+(\d{4}))?\b", t)
    if m:
        y = int(m.group(2)) if m.group(2) else today.year
        return f"{y}-{_MONTHS[m.group(1)[:3]]:02d}"
    m = re.search(r"\b(\d{4})-(\d{2})\b", t)
    if m:
        return m.group(0)
    return None


_NOISE = re.compile(
    r"\b(?:paid|pay|payment|gave|given|give|log|logged|add|added|record|recorded|enter|entered|"
    r"chit|chits|loan|instal?lment|installment|to|for|on|of|the|a|an|by|via|in|and|"
    r"cash|bank|upi|neft|imps|rtgs|today|yesterday|rs|inr|lakhs?|lacs?|lakh|lac|thousand|"
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|"
    r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b", re.I)


def parse_name(text: str, date_text: str = "") -> str:
    """Whatever is left after stripping verbs, amounts, dates and chit words."""
    t = text
    if date_text:
        t = t.replace(date_text, " ")
    t = AMOUNT_RE.sub(" ", t)
    t = re.sub(r"\d+(?:st|nd|rd|th)?", " ", t)
    t = _NOISE.sub(" ", t)
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()
