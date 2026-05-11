"""
src/services/upi_reconciliation.py
===================================
Auto-reconcile UPI collection bank exports against active tenants.

Supports Lakshmi merchant UPI app exports (XLSX or CSV):
  Columns: RRN, Date, Time, TXN_AMOUNT, ..., Payer_VPA, Payer_Name, ..., Settlement_Status

Flow per file:
  1. Parse rows — keep only Settlement_Status == SUCCESS
  2. Load all active tenants once (name + phone)
  3. For each transaction (by RRN — safe to re-upload same file):
     a. Skip if RRN already in upi_collection_entries
     b. Match tenant: phone from VPA → exact name → fuzzy name (>=2 tokens, score>=0.6)
     c. If matched: create Payment record (payment_mode=upi, unique_hash=rrn:{RRN})
     d. Insert UpiCollectionEntry (matched or unmatched)
  4. Return ReconciliationResult

Called from:
  - POST /api/v2/app/finance/upi-reconcile  (manual PWA upload)
  - src/workers/gmail_poller.py             (daily auto-run)
"""
from __future__ import annotations

import csv
import io
import re
import datetime
from dataclasses import dataclass, field
from typing import Optional

import openpyxl
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import Payment, PaymentFor, PaymentMode, UpiCollectionEntry


# ── Matching helpers ──────────────────────────────────────────────────────────

def _extract_phone(vpa: Optional[str]) -> Optional[str]:
    if not vpa: return None
    m = re.match(r'^(\d{10})(?:-\d+)?@', str(vpa))
    return m.group(1) if m else None

def _normalize_phone(ph: Optional[str]) -> Optional[str]:
    if not ph: return None
    ph = re.sub(r'\D', '', str(ph))
    if ph.startswith('91') and len(ph) == 12: ph = ph[2:]
    return ph if len(ph) == 10 else None

def _tokens(s: str) -> list[str]:
    return [p for p in re.sub(r'[^A-Z0-9 ]', ' ', s.upper()).split() if len(p) > 1]


# ── File parsing ──────────────────────────────────────────────────────────────

@dataclass
class RawEntry:
    rrn:    str
    date:   datetime.date
    amount: float
    vpa:    Optional[str]
    phone:  Optional[str]
    name:   str

def _parse_xlsx(data: bytes) -> list[RawEntry]:
    wb = openpyxl.load_workbook(io.BytesIO(data))
    ws = wb.worksheets[0]
    entries: list[RawEntry] = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[11] != 'SUCCESS' or not row[3]: continue
        rrn = str(int(row[0])) if row[0] else None
        if not rrn: continue
        txn_date = row[1].date() if isinstance(row[1], datetime.datetime) else row[1]
        if not txn_date: continue
        vpa   = str(row[7]).strip() if row[7] else None
        phone = _extract_phone(vpa)
        name  = str(row[8]).strip().upper() if row[8] else ''
        entries.append(RawEntry(rrn=rrn, date=txn_date, amount=float(row[3]),
                                vpa=vpa, phone=phone, name=name))
    return entries

def _parse_csv(data: bytes) -> list[RawEntry]:
    entries: list[RawEntry] = []
    text_data = data.decode('utf-8-sig', errors='replace')
    reader = csv.DictReader(io.StringIO(text_data))
    for row in reader:
        if row.get('Settlement_Status') != 'SUCCESS': continue
        amt_str = row.get('TXN_AMOUNT', '').strip()
        if not amt_str: continue
        rrn = row.get('RRN', '').strip()
        if not rrn: continue
        date_str = row.get('Date', '').strip()
        txn_date = None
        for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y'):
            try: txn_date = datetime.datetime.strptime(date_str, fmt).date(); break
            except: pass
        if not txn_date: continue
        vpa   = row.get('Payer_VPA', '').strip() or None
        phone = _extract_phone(vpa)
        name  = row.get('Payer_Name', '').strip().upper()
        entries.append(RawEntry(rrn=rrn, date=txn_date, amount=float(amt_str),
                                vpa=vpa, phone=phone, name=name))
    return entries

def parse_bank_file(file_bytes: bytes, filename: str) -> list[RawEntry]:
    if filename.lower().endswith('.csv'):
        return _parse_csv(file_bytes)
    return _parse_xlsx(file_bytes)


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class MatchedEntry:
    rrn:          str
    amount:       float
    payer_name:   str
    tenant_name:  str
    room:         str
    matched_by:   str
    payment_id:   int

@dataclass
class UnmatchedEntry:
    rrn:        str
    amount:     float
    payer_name: str
    payer_vpa:  Optional[str]

@dataclass
class ReconciliationResult:
    account_name:  str
    period_month:  datetime.date
    total_rows:    int
    matched:       list[MatchedEntry]   = field(default_factory=list)
    unmatched:     list[UnmatchedEntry] = field(default_factory=list)
    skipped_dup:   int = 0

    @property
    def matched_amount(self) -> float:
        return sum(e.amount for e in self.matched)

    @property
    def unmatched_amount(self) -> float:
        return sum(e.amount for e in self.unmatched)


# ── Core reconciliation ───────────────────────────────────────────────────────

async def reconcile_upi_file(
    session:      AsyncSession,
    file_bytes:   bytes,
    filename:     str,
    account_name: str,       # 'HULK' | 'THOR'
    period_month: Optional[datetime.date] = None,  # defaults to txn date's month
) -> ReconciliationResult:
    entries = parse_bank_file(file_bytes, filename)

    # Load existing RRNs to skip duplicates
    existing_rrns_result = await session.execute(
        select(UpiCollectionEntry.rrn)
    )
    existing_rrns = {r[0] for r in existing_rrns_result}

    # Load all active tenants (name, phone, tenancy_id, room)
    rows = await session.execute(text("""
        SELECT tn.id, t.name, t.phone, r.room_number
        FROM tenancies tn
        JOIN tenants t ON t.id = tn.tenant_id
        JOIN rooms   r ON r.id = tn.room_id
        WHERE tn.status = 'active'
    """))
    tenants = [
        {'tenancy_id': r[0], 'name': r[1].strip().upper(), 'phone': _normalize_phone(r[2]), 'room': r[3]}
        for r in rows
    ]

    result = ReconciliationResult(
        account_name=account_name,
        period_month=period_month or datetime.date.today().replace(day=1),
        total_rows=len(entries),
    )

    for entry in entries:
        if entry.rrn in existing_rrns:
            result.skipped_dup += 1
            continue

        mon = datetime.date(entry.date.year, entry.date.month, 1)
        eff_period = period_month or mon

        matched_tenant, match_method = _match_tenant(entry, tenants)

        if matched_tenant:
            pay = Payment(
                tenancy_id   = matched_tenant['tenancy_id'],
                amount       = entry.amount,
                payment_date = entry.date,
                payment_mode = PaymentMode.upi,
                upi_reference= entry.rrn,
                for_type     = PaymentFor.rent,
                period_month = eff_period,
                notes        = f"Auto-reconciled {account_name} bank — {entry.name}",
                unique_hash  = f"rrn:{entry.rrn}",
            )
            session.add(pay)
            await session.flush()  # get pay.id

            upi_entry = UpiCollectionEntry(
                rrn=entry.rrn, account_name=account_name, txn_date=entry.date,
                amount=entry.amount, payer_vpa=entry.vpa, payer_phone=entry.phone,
                payer_name=entry.name, tenancy_id=matched_tenant['tenancy_id'],
                payment_id=pay.id, matched_by=match_method, period_month=eff_period,
                source_file=filename,
            )
            session.add(upi_entry)
            existing_rrns.add(entry.rrn)

            result.matched.append(MatchedEntry(
                rrn=entry.rrn, amount=entry.amount, payer_name=entry.name,
                tenant_name=matched_tenant['name'], room=matched_tenant['room'],
                matched_by=match_method, payment_id=pay.id,
            ))
        else:
            upi_entry = UpiCollectionEntry(
                rrn=entry.rrn, account_name=account_name, txn_date=entry.date,
                amount=entry.amount, payer_vpa=entry.vpa, payer_phone=entry.phone,
                payer_name=entry.name, tenancy_id=None, payment_id=None,
                matched_by='unmatched', period_month=eff_period, source_file=filename,
            )
            session.add(upi_entry)
            existing_rrns.add(entry.rrn)

            result.unmatched.append(UnmatchedEntry(
                rrn=entry.rrn, amount=entry.amount,
                payer_name=entry.name, payer_vpa=entry.vpa,
            ))

    await session.commit()
    return result


def _match_tenant(entry: RawEntry, tenants: list[dict]) -> tuple[Optional[dict], str]:
    """3-tier matching: phone → exact name → fuzzy name."""
    norm_phone = _normalize_phone(entry.phone)

    # Tier 1: phone
    if norm_phone:
        for t in tenants:
            if t['phone'] == norm_phone:
                return t, 'phone'

    # Tier 2: exact name
    for t in tenants:
        if t['name'] == entry.name:
            return t, 'name'

    # Tier 3: fuzzy (>=2 token hits, score >=0.6)
    entry_parts = _tokens(entry.name)
    if len(entry_parts) >= 2:
        best_score, best_tenant = 0.0, None
        for t in tenants:
            t_parts = _tokens(t['name'])
            hits = sum(1 for ep in entry_parts if any(ep in tp or tp in ep for tp in t_parts))
            score = hits / len(entry_parts)
            if hits >= 2 and score >= 0.6 and score > best_score:
                best_score, best_tenant = score, t
        if best_tenant:
            return best_tenant, 'fuzzy'

    return None, 'unmatched'


# ── Manual assignment ─────────────────────────────────────────────────────────

async def assign_upi_entry(
    session:    AsyncSession,
    rrn:        str,
    tenancy_id: int,
    period_month: datetime.date,
) -> int:
    """Manually link an unmatched entry to a tenant; creates the Payment record."""
    result = await session.execute(
        select(UpiCollectionEntry).where(UpiCollectionEntry.rrn == rrn)
    )
    entry = result.scalar_one_or_none()
    if not entry:
        raise ValueError(f"RRN {rrn} not found")
    if entry.tenancy_id:
        raise ValueError(f"RRN {rrn} already matched to tenancy {entry.tenancy_id}")

    pay = Payment(
        tenancy_id   = tenancy_id,
        amount       = float(entry.amount),
        payment_date = entry.txn_date,
        payment_mode = PaymentMode.upi,
        upi_reference= entry.rrn,
        for_type     = PaymentFor.rent,
        period_month = period_month,
        notes        = f"Manually assigned from {entry.account_name} bank — {entry.payer_name}",
        unique_hash  = f"rrn:{entry.rrn}",
    )
    session.add(pay)
    await session.flush()

    entry.tenancy_id  = tenancy_id
    entry.payment_id  = pay.id
    entry.matched_by  = 'manual'
    entry.period_month= period_month

    await session.commit()
    return pay.id
