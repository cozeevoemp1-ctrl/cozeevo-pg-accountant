"""
src/services/sheet_audit.py
===========================
Core logic for the sheet↔DB drift audit. Read-only against the sheet and DB.

Audited fields
--------------
TENANTS tab (per phone match):
    Room, Agreed Rent, Deposit, Notice Date, Checkout Date

Current monthly tab (per phone match):
    Room, Rent, Cash, UPI, Total Paid

Balance / Prev Due / Event / Status involve proration and are deliberately
out of scope — `scripts/sync_sheet_from_db.py --write` heals those end-to-end
if needed. This audit is about catching accidental manual sheet edits, not
recomputing financial state.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

import gspread
from google.oauth2.service_account import Credentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from src.database.models import (
    Tenancy, Tenant, Room, TenancyStatus,
    Payment, PaymentFor,
)
from src.integrations.gsheets import (
    CREDENTIALS_PATH, SHEET_ID, _current_month_tab,
)


# ── Normalisation helpers ────────────────────────────────────────────────────

def _nph(p) -> str:
    d = re.sub(r"\D", "", str(p or ""))
    return d[-10:] if len(d) >= 10 else ""


def _norm_str(s) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip()).lower()


def _norm_num(s) -> float | None:
    if s is None:
        return 0.0
    s = str(s).replace(",", "").replace("₹", "").replace("Rs.", "").strip()
    if s == "" or s in ("-", "–", "—", "N/A", "NA"):
        return 0.0
    try:
        return float(s)
    except ValueError:
        return None


def _norm_date(s) -> date | None:
    if s is None or str(s).strip() == "":
        return None
    s = str(s).strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y", "%d %b %Y", "%d-%b-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _eq_num(a: float | None, b: float | None, tol: float = 0.51) -> bool:
    if a is None or b is None:
        return a == b
    return abs(float(a) - float(b)) <= tol


def _cell(row: list[str], i: int) -> str:
    return row[i].strip() if 0 <= i < len(row) else ""


def _col_idx(headers: list[str], name: str) -> int:
    target = _norm_str(name)
    for i, h in enumerate(headers):
        if _norm_str(h) == target:
            return i
    return -1


# ── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class Diff:
    tab: str
    row: int
    phone: str
    name: str
    field: str
    sheet: str
    db: str

    def as_line(self) -> str:
        return (f"[{self.tab} r{self.row}] {self.name or '?'} ({self.phone}) "
                f"{self.field}: sheet={self.sheet!r} db={self.db!r}")


@dataclass
class AuditResult:
    tenants_diffs: list[Diff] = field(default_factory=list)
    monthly_diffs: list[Diff] = field(default_factory=list)
    missing_in_db: list[tuple[str, int, str, str]] = field(default_factory=list)
    missing_in_sheet: list[tuple[str, str, str]] = field(default_factory=list)
    month_tab: str = ""

    @property
    def total_diffs(self) -> int:
        return (len(self.tenants_diffs) + len(self.monthly_diffs)
                + len(self.missing_in_db) + len(self.missing_in_sheet))


# ── Sheet reader ─────────────────────────────────────────────────────────────

def _read_sheets() -> tuple[list[list[str]], list[list[str]], str]:
    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    creds = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=scopes)
    gc = gspread.authorize(creds)
    ss = gc.open_by_key(SHEET_ID)
    tenants_ws = ss.worksheet("TENANTS")
    tenants_rows = tenants_ws.get_all_values()
    monthly_tab = _current_month_tab()
    try:
        monthly_ws = ss.worksheet(monthly_tab)
        monthly_rows = monthly_ws.get_all_values()
    except gspread.exceptions.WorksheetNotFound:
        monthly_rows = []
    return tenants_rows, monthly_rows, monthly_tab


# ── DB reader ────────────────────────────────────────────────────────────────

def _db_url() -> str:
    url = os.environ["DATABASE_URL"]
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


async def _fetch_db_state(period: date, next_period: date) -> dict:
    engine = create_async_engine(_db_url(), echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    by_phone_tenants: dict[str, dict] = {}
    by_phone_monthly: dict[str, dict] = {}

    async with Session() as s:
        rows = (await s.execute(
            select(Tenancy, Tenant, Room)
            .join(Tenant, Tenant.id == Tenancy.tenant_id)
            .join(Room, Room.id == Tenancy.room_id)
        )).all()

        by_tenancy: dict[int, tuple] = {}
        for tenancy, tenant, room in rows:
            ph = _nph(tenant.phone)
            if not ph:
                continue
            by_tenancy[tenancy.id] = (tenancy, tenant, room)
            existing = by_phone_tenants.get(ph)
            cand = {
                "tenancy_id": tenancy.id,
                "room": str(room.room_number),
                "name": tenant.name,
                "agreed_rent": float(tenancy.agreed_rent or 0),
                "security_deposit": float(tenancy.security_deposit or 0),
                "notice_date": tenancy.notice_date,
                "checkout_date": tenancy.checkout_date,
                "status": tenancy.status,
                "checkin_date": tenancy.checkin_date,
            }
            if existing is None or (
                cand["checkin_date"] and existing.get("checkin_date")
                and cand["checkin_date"] > existing["checkin_date"]
            ):
                by_phone_tenants[ph] = cand

        pay_rows = (await s.execute(
            select(Payment).where(
                Payment.period_month == period,
                Payment.is_void == False,
                Payment.for_type == PaymentFor.rent,
            )
        )).scalars().all()

        per_tenancy_pay: dict[int, dict] = {}
        for p in pay_rows:
            if not (p.payment_date and period <= p.payment_date < next_period):
                continue
            mode = (p.payment_mode.value if hasattr(p.payment_mode, "value")
                    else str(p.payment_mode or "cash")).lower()
            bucket = per_tenancy_pay.setdefault(
                p.tenancy_id, {"cash": Decimal("0"), "upi": Decimal("0")})
            if mode in ("upi", "bank", "online", "neft", "imps"):
                bucket["upi"] += p.amount
            else:
                bucket["cash"] += p.amount

        for tid, pay in per_tenancy_pay.items():
            tup = by_tenancy.get(tid)
            if not tup:
                continue
            tenancy, tenant, room = tup
            ph = _nph(tenant.phone)
            if not ph:
                continue
            by_phone_monthly[ph] = {
                "tenancy_id": tenancy.id,
                "room": str(room.room_number),
                "name": tenant.name,
                "rent": float(tenancy.agreed_rent or 0),
                "cash": float(pay["cash"]),
                "upi": float(pay["upi"]),
                "total": float(pay["cash"] + pay["upi"]),
            }

        # Seed active/no-show with zero payments (sheet shows them too).
        for ph, t in by_phone_tenants.items():
            if ph in by_phone_monthly:
                continue
            if t["status"] not in (TenancyStatus.active, TenancyStatus.no_show):
                continue
            by_phone_monthly[ph] = {
                "tenancy_id": t["tenancy_id"],
                "room": t["room"],
                "name": t["name"],
                "rent": t["agreed_rent"],
                "cash": 0.0, "upi": 0.0, "total": 0.0,
            }

    await engine.dispose()
    return {"tenants": by_phone_tenants, "monthly": by_phone_monthly}


# ── Diff engines ─────────────────────────────────────────────────────────────

def _diff_tenants(rows: list[list[str]], db_tenants: dict[str, dict]
                  ) -> tuple[list[Diff], list[tuple], set[str]]:
    diffs: list[Diff] = []
    missing: list[tuple] = []
    if not rows:
        return diffs, missing, set()

    headers = rows[0]
    c_room = _col_idx(headers, "Room")
    c_name = _col_idx(headers, "Name")
    c_phone = _col_idx(headers, "Phone")
    c_rent = _col_idx(headers, "Agreed Rent")
    c_dep = _col_idx(headers, "Deposit")
    c_notice = _col_idx(headers, "Notice Date")
    c_checkout = _col_idx(headers, "Checkout Date")

    seen: set[str] = set()
    for row_idx, row in enumerate(rows[1:], start=2):
        ph = _nph(_cell(row, c_phone))
        if not ph:
            continue
        seen.add(ph)
        db = db_tenants.get(ph)
        name_sheet = _cell(row, c_name)
        if not db:
            if any(_cell(row, i) for i in (c_rent, c_dep, c_notice, c_checkout) if i >= 0):
                missing.append(("TENANTS", row_idx, ph, name_sheet))
            continue

        if c_room >= 0:
            s_room = _cell(row, c_room)
            if _norm_str(s_room) != _norm_str(db["room"]):
                diffs.append(Diff("TENANTS", row_idx, ph, name_sheet,
                                  "Room", s_room, db["room"]))
        # Name deliberately skipped — spacing/middle-name noise.
        if c_rent >= 0:
            sv = _norm_num(_cell(row, c_rent))
            if not _eq_num(sv, db["agreed_rent"]):
                diffs.append(Diff("TENANTS", row_idx, ph, name_sheet,
                                  "Agreed Rent",
                                  _cell(row, c_rent), f"{db['agreed_rent']:.0f}"))
        if c_dep >= 0:
            sv = _norm_num(_cell(row, c_dep))
            if not _eq_num(sv, db["security_deposit"]):
                diffs.append(Diff("TENANTS", row_idx, ph, name_sheet,
                                  "Deposit",
                                  _cell(row, c_dep), f"{db['security_deposit']:.0f}"))
        for col, label, db_key in [
            (c_notice, "Notice Date", "notice_date"),
            (c_checkout, "Checkout Date", "checkout_date"),
        ]:
            if col < 0:
                continue
            s_raw = _cell(row, col)
            s_d = _norm_date(s_raw)
            d = db[db_key]
            if s_d is None and d is None:
                continue
            if s_d != d:
                diffs.append(Diff("TENANTS", row_idx, ph, name_sheet,
                                  label, s_raw,
                                  d.strftime("%d/%m/%Y") if d else ""))

    return diffs, missing, seen


def _diff_monthly(rows: list[list[str]], db_monthly: dict[str, dict], tab: str
                  ) -> tuple[list[Diff], list[tuple], set[str]]:
    diffs: list[Diff] = []
    missing: list[tuple] = []
    if not rows:
        return diffs, missing, set()

    # Monthly tabs have title + summary rows above the header row.
    header_idx = None
    for i, row in enumerate(rows[:15]):
        if row and _norm_str(row[0]) == "room":
            header_idx = i
            break
    if header_idx is None:
        return diffs, missing, set()

    headers = rows[header_idx]
    data_rows = rows[header_idx + 1:]

    c_room = _col_idx(headers, "Room")
    c_name = _col_idx(headers, "Name")
    c_phone = _col_idx(headers, "Phone")
    c_rent = _col_idx(headers, "Rent")
    c_cash = _col_idx(headers, "Cash")
    c_upi = _col_idx(headers, "UPI")
    c_total = _col_idx(headers, "Total Paid")

    seen: set[str] = set()
    for local_idx, row in enumerate(data_rows, start=header_idx + 2):
        ph = _nph(_cell(row, c_phone))
        if not ph:
            continue
        seen.add(ph)
        db = db_monthly.get(ph)
        name_sheet = _cell(row, c_name)
        if not db:
            if any(_cell(row, i) for i in (c_cash, c_upi, c_total) if i >= 0):
                missing.append((tab, local_idx, ph, name_sheet))
            continue

        if c_room >= 0:
            s_room = _cell(row, c_room)
            if _norm_str(s_room) != _norm_str(db["room"]):
                diffs.append(Diff(tab, local_idx, ph, name_sheet,
                                  "Room", s_room, db["room"]))
        if c_rent >= 0:
            sv = _norm_num(_cell(row, c_rent))
            if not _eq_num(sv, db["rent"]):
                diffs.append(Diff(tab, local_idx, ph, name_sheet,
                                  "Rent", _cell(row, c_rent), f"{db['rent']:.0f}"))
        if c_cash >= 0:
            sv = _norm_num(_cell(row, c_cash))
            if not _eq_num(sv, db["cash"]):
                diffs.append(Diff(tab, local_idx, ph, name_sheet,
                                  "Cash", _cell(row, c_cash), f"{db['cash']:.0f}"))
        if c_upi >= 0:
            sv = _norm_num(_cell(row, c_upi))
            if not _eq_num(sv, db["upi"]):
                diffs.append(Diff(tab, local_idx, ph, name_sheet,
                                  "UPI", _cell(row, c_upi), f"{db['upi']:.0f}"))
        if c_total >= 0:
            sv = _norm_num(_cell(row, c_total))
            if not _eq_num(sv, db["total"]):
                diffs.append(Diff(tab, local_idx, ph, name_sheet,
                                  "Total Paid",
                                  _cell(row, c_total), f"{db['total']:.0f}"))

    return diffs, missing, seen


# ── Public entry points ──────────────────────────────────────────────────────

async def run_audit() -> AuditResult:
    today = date.today()
    period = today.replace(day=1)
    next_period = (date(period.year + 1, 1, 1) if period.month == 12
                   else date(period.year, period.month + 1, 1))

    tenants_rows, monthly_rows, monthly_tab = _read_sheets()
    db_state = await _fetch_db_state(period, next_period)

    t_diffs, t_missing, t_seen = _diff_tenants(tenants_rows, db_state["tenants"])
    m_diffs, m_missing, m_seen = _diff_monthly(monthly_rows, db_state["monthly"], monthly_tab)

    missing_in_sheet: list[tuple[str, str, str]] = []
    for ph, t in db_state["tenants"].items():
        if ph not in t_seen and t["status"] in (TenancyStatus.active, TenancyStatus.no_show):
            missing_in_sheet.append(("TENANTS", ph, t["name"]))
    for ph, t in db_state["monthly"].items():
        if ph not in m_seen and t["total"] > 0:
            missing_in_sheet.append((monthly_tab, ph, t["name"]))

    return AuditResult(
        tenants_diffs=t_diffs,
        monthly_diffs=m_diffs,
        missing_in_db=t_missing + m_missing,
        missing_in_sheet=missing_in_sheet,
        month_tab=monthly_tab,
    )


def format_report(r: AuditResult, preview: int = 15) -> str:
    lines: list[str] = []
    lines.append(f"Sheet Audit — {datetime.now().strftime('%Y-%m-%d %H:%M IST')}")
    lines.append(f"Month tab: {r.month_tab}")
    lines.append("")
    lines.append(f"TENANTS diffs:  {len(r.tenants_diffs)}")
    lines.append(f"Monthly diffs:  {len(r.monthly_diffs)}")
    lines.append(f"In sheet, missing DB: {len(r.missing_in_db)}")
    lines.append(f"In DB, missing sheet: {len(r.missing_in_sheet)}")
    lines.append("")

    def dump(title, rows, fmt):
        if not rows:
            return
        lines.append(f"-- {title} (showing up to {preview}) --")
        for row in rows[:preview]:
            lines.append("  " + fmt(row))
        if len(rows) > preview:
            lines.append(f"  …and {len(rows) - preview} more")
        lines.append("")

    dump("TENANTS", r.tenants_diffs, lambda d: d.as_line())
    dump("Monthly", r.monthly_diffs, lambda d: d.as_line())
    dump("Sheet row present, DB missing", r.missing_in_db,
         lambda x: f"[{x[0]} r{x[1]}] {x[3] or '?'} ({x[2]})")
    dump("DB present, sheet missing", r.missing_in_sheet,
         lambda x: f"[{x[0]}] {x[2] or '?'} ({x[1]})")

    return "\n".join(lines).rstrip()


def whatsapp_message(r: AuditResult) -> str:
    header = (f"Sheet Audit — {r.month_tab}\n"
              f"Total issues: {r.total_diffs}\n"
              f"  TENANTS diffs: {len(r.tenants_diffs)}\n"
              f"  {r.month_tab} diffs: {len(r.monthly_diffs)}\n"
              f"  rows missing from DB: {len(r.missing_in_db)}\n"
              f"  rows missing from sheet: {len(r.missing_in_sheet)}\n")
    if r.total_diffs == 0:
        return header + "\nAll clean."
    preview: list[str] = []
    for d in (r.tenants_diffs + r.monthly_diffs)[:8]:
        preview.append(f"- {d.tab} r{d.row} {d.name or '?'} {d.field}: "
                       f"{d.sheet!r} -> {d.db!r}")
    for m in r.missing_in_db[:4]:
        preview.append(f"- {m[0]} r{m[1]} {m[3] or '?'} not in DB")
    for m in r.missing_in_sheet[:4]:
        preview.append(f"- {m[0]} {m[2] or '?'} not in sheet")
    shown = min(len(r.tenants_diffs) + len(r.monthly_diffs), 8) \
        + min(len(r.missing_in_db), 4) + min(len(r.missing_in_sheet), 4)
    extra = r.total_diffs - shown
    if extra > 0:
        preview.append(f"(+{extra} more)")
    fix = "\nTo heal monthly tab: python scripts/sync_sheet_from_db.py --write"
    return header + "\n" + "\n".join(preview) + fix
