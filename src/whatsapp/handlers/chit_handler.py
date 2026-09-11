"""
src/whatsapp/handlers/chit_handler.py
=====================================
Chit / hand-loan instalment register over WhatsApp.

HARD BOUNDARY: only `services.chit_payments.CHIT_PHONES` (Kiran + Prabhakaran)
reach these handlers. gatekeeper.py checks the phone BEFORE routing here and
`_guard()` checks again — anyone else gets the generic "didn't understand" reply
and nothing about chits is revealed.

Intents:
  CHIT_LOG    "paid boobalan chit 5.5L on 11 sep", "chit belandur 5,00,000 today"
  CHIT_QUERY  "chit payments", "chit sep", "chit boobalan", "chit summary"
  CHIT_VOID   "void chit 6", "delete chit 6", "cancel chit 6"
  CHIT_EDIT   "chit 6 amount 5L", "chit 6 date 10 sep", "chit 6 name boobalan", "change chit 6 to 5.5L"
"""
from __future__ import annotations

import re
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from src.services import chit_payments as svc
from src.utils.inr_format import inr
from src.whatsapp.role_service import CallerContext

CHIT_INTENTS: frozenset[str] = frozenset({"CHIT_LOG", "CHIT_QUERY", "CHIT_VOID", "CHIT_EDIT"})

_DENIED = "Sorry, I didn't understand that. Type *help* for commands."


def _guard(ctx: CallerContext) -> str | None:
    return None if svc.phone_allowed(ctx.phone) else _DENIED


async def handle_chit(intent: str, entities: dict, ctx: CallerContext, session: AsyncSession) -> str:
    if (denied := _guard(ctx)):
        return denied
    raw = (entities.get("_raw_message") or "").strip()
    if intent == "CHIT_LOG":
        return await _log(raw, ctx, session)
    if intent == "CHIT_VOID":
        return await _void(raw, session)
    if intent == "CHIT_EDIT":
        return await _edit(raw, ctx, session)
    return await _query(raw, session, ctx.phone)


# ── CHIT_LOG ──────────────────────────────────────────────────────────────────

async def _log(raw: str, ctx: CallerContext, session: AsyncSession) -> str:
    amount = svc.parse_amount(raw)
    if not amount:
        return ("Usage: *chit <name> <amount> [date]*\n"
                "Example: paid boobalan chit 5.5L on 11 sep")
    when, date_text = svc.parse_date(raw)
    typed_name = svc.parse_name(raw, date_text)
    if not typed_name:
        return "Whose chit is this? Example: *chit belandur 5L today*"
    name = await svc.canonical_name(session, typed_name)
    category = "Loan" if re.search(r"\bloan\b", raw, re.I) else "Chit"
    mode = "bank" if re.search(r"\b(?:bank|upi|neft|imps|rtgs)\b", raw, re.I) else "cash"

    row = await svc.add_payment(session, payment_date=when, name=name, amount=Decimal(amount),
                                category=category, payment_mode=mode, created_by=ctx.phone)
    await session.commit()
    total = sum((r.amount for r in await svc.list_payments(session, name=name)), Decimal(0))
    return (f"Recorded {category} #{row.id}\n"
            f"{name} — {inr(row.amount)} ({mode})\n"
            f"Date: {when.strftime('%d %b %Y')}\n"
            f"Total to {name} so far: {inr(total)}\n"
            f"_Wrong? Reply: void chit {row.id}_")


# ── CHIT_QUERY ────────────────────────────────────────────────────────────────

async def _query(raw: str, session: AsyncSession, ctx_phone: str | None = None) -> str:
    month = svc.parse_month(raw)
    name_hint = svc.parse_name(raw) if not month else svc.parse_name(raw)
    for w in ("summary", "total", "totals", "list", "all", "show", "history", "payments", "payment", "so far", "much", "how", "what", "have", "we", "is", "i", "me"):
        name_hint = re.sub(rf"\b{w}\b", " ", name_hint, flags=re.I)
    name_hint = re.sub(r"\s+", " ", name_hint).strip()
    name = await svc.canonical_name(session, name_hint) if name_hint else None
    if name and name not in await svc.known_names(session):
        name = None  # unrecognised word — don't filter on it

    rows = await svc.list_payments(session, month=month, name=name)
    scope = " ".join(x for x in [name or "", _month_label(month) if month else ""] if x)
    if not rows:
        return f"No chit payments found{(' for ' + scope) if scope else ''}."

    total = sum((r.amount for r in rows), Decimal(0))
    by_name = await svc.totals_by_name(session) if not (name or month) else []
    title = f"Chit payments{(' — ' + scope) if scope else ''}"

    # Preferred: a spreadsheet-style PNG (WhatsApp text can't hold a real grid).
    # Sent directly from here; "" tells chat_api there is no text reply to send.
    png = _render_png(title, rows, total, by_name)
    if png and ctx_phone and await _send_png(ctx_phone, png, f"{title} · Total {inr(total)}"):
        return ""

    # Fallback: ASCII grid in a ``` block (≤ 30 chars wide so it doesn't wrap).
    body = []
    for r in rows:
        nm = _short(r.name, 8) + ("" if r.category == "Chit" else "*")
        body.append([str(r.id), r.payment_date.strftime("%d %b"), nm, inr(r.amount)])
    tbl = _grid(["#", "Date", "Name", "Amount"], body, [2, 6, 8, 9], align="rllr",
                footer=["", "Total", "", inr(total)])
    out = [f"*{title}*", "```", *tbl, "```"]
    if any(r.category != "Chit" for r in rows):
        out.append("_* = Loan_")
    if by_name:
        by = [[_short(n, 15), inr(s), str(c)] for n, c, s in by_name]
        out += ["", "*By name*", "```", *_grid(["Name", "Amount", "n"], by, [15, 9, 2], align="lrr"), "```"]
    return "\n".join(out)


def _render_png(title: str, rows, total: Decimal, by_name) -> bytes | None:
    try:
        from src.services.table_image import Sheet, Table, render_png
        from datetime import date as _date
        main = Table(
            headers=["S.No", "Date", "Name", "Category", "Amount", "Mode"],
            rows=[[str(r.id), r.payment_date.strftime("%d %b %Y"), r.name, r.category,
                   inr(r.amount), (r.payment_mode or "-")] for r in rows],
            align="rlllrl",
            footer=["", "", "Total", "", inr(total), ""],
        )
        tables = [main]
        if by_name:
            tables.append(Table(title="By name",
                                headers=["Name", "Payments", "Total"],
                                rows=[[n, str(c), inr(s)] for n, c, s in by_name],
                                align="lrr"))
        return render_png(Sheet(title=title, subtitle=f"as of {_date.today().strftime('%d %b %Y')}", tables=tables))
    except Exception:
        return None


async def _send_png(phone: str, png: bytes, caption: str) -> bool:
    try:
        from src.whatsapp.webhook_handler import send_whatsapp_image_bytes
        return await send_whatsapp_image_bytes(phone, png, caption=caption, filename="chit_payments.png")
    except Exception:
        return False


def _grid(headers: list[str], rows: list[list[str]], widths: list[int], align: str,
          footer: list[str] | None = None) -> list[str]:
    """ASCII box grid (+--+ / |..|) — box-drawing glyphs aren't monospace on every phone.
    Total width = sum(widths) + len(widths) + 1; keep ≤ 30 so it doesn't wrap."""
    def line(cells):
        return "|" + "|".join(
            (c.rjust(w) if a == "r" else c.ljust(w))[:w] for c, w, a in zip(cells, widths, align)
        ) + "|"
    sep = "+" + "+".join("-" * w for w in widths) + "+"
    out = [sep, line(headers), sep, *[line(r) for r in rows], sep]
    if footer:
        out += [line(footer), sep]
    return out


def _short(name: str, width: int = 10) -> str:
    """First word if the full name won't fit the column ('Belandur Balaji' → 'Belandur')."""
    if len(name) <= width:
        return name
    first = name.split()[0]
    return first if len(first) <= width else first[:width - 1] + "."


def _month_label(ym: str) -> str:
    y, m = ym.split("-")
    return f"{['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][int(m)-1]} {y}"


# ── CHIT_VOID ─────────────────────────────────────────────────────────────────

async def _void(raw: str, session: AsyncSession) -> str:
    m = re.search(r"#?\s*(\d+)\s*$", raw) or re.search(r"\b(\d+)\b", raw)
    if not m:
        return "Which one? Example: *void chit 6* (the # from the chit list)"
    row = await svc.void_payment(session, int(m.group(1)))
    if not row:
        return f"No active chit payment #{m.group(1)}."
    await session.commit()
    return f"Voided #{row.id}: {row.name} {inr(row.amount)} on {row.payment_date.strftime('%d %b %Y')}."


# ── CHIT_EDIT ─────────────────────────────────────────────────────────────────

async def _edit(raw: str, ctx: CallerContext, session: AsyncSession) -> str:
    """'chit 6 date 10 sep' · 'chit 6 amount 5L' · 'chit 6 name boobalan' ·
    'change chit 6 to 5.5L' · 'chit 6 date 10 sep amount 5L' (several at once)."""
    m = re.search(r"\bchit\s*#?\s*(\d+)\b", raw, re.I)
    if not m:
        return "Which one? Example: *chit 6 amount 5L* or *chit 6 date 10 sep*"
    row_id = int(m.group(1))
    rest = raw[m.end():]  # only what follows the S.No — keeps the S.No out of amount/date parsing
    kw: dict = {}
    if re.search(r"\b(?:date|dated|on)\b", rest, re.I) or svc.parse_date(rest)[1]:
        d, dt = svc.parse_date(rest)
        if dt:
            kw["payment_date"] = d
            rest = rest.replace(dt, " ")
    amt = svc.parse_amount(rest)
    if amt is not None:
        kw["amount"] = amt
    nm = re.search(r"\b(?:name|to|for)\s+([A-Za-z][A-Za-z ]*?)(?:\s+(?:date|amount|on|dated|cash|bank|loan|chit)\b|\s*$)", rest, re.I)
    if nm and not re.fullmatch(r"(?:cash|bank|loan|chit)", nm.group(1).strip(), re.I):
        kw["name"] = await svc.canonical_name(session, nm.group(1).strip())
    if re.search(r"\b(?:bank|upi|neft|imps|rtgs)\b", rest, re.I):
        kw["payment_mode"] = "bank"
    elif re.search(r"\bcash\b", rest, re.I):
        kw["payment_mode"] = "cash"
    if re.search(r"\bloan\b", rest, re.I):
        kw["category"] = "Loan"
    if not kw:
        return ("Nothing to change. Examples:\n*chit 6 amount 5L*\n*chit 6 date 10 sep*\n"
                "*chit 6 name boobalan*\n*chit 6 bank*")
    row, changes = await svc.edit_payment(session, row_id, edited_by=ctx.phone, **kw)
    if row is None:
        return f"No active chit payment #{row_id}."
    if not changes:
        return f"#{row_id} already has those values — nothing changed."
    await session.commit()
    return (f"Updated #{row.id}: " + ", ".join(changes) + "\n"
            f"Now: {row.payment_date.strftime('%d %b %Y')} {row.name} — {inr(row.amount)} ({row.payment_mode})")
