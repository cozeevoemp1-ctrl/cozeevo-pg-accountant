# Financial Reconciliation Engine — Vision & Design

> Future feature for Cozeevo PG Accountant.
> Status: **Phase 0 complete** (bank_statement_extractor + pnl_report scripts built).
> Full engine planned as `finance/` package integrated into the WhatsApp AI bot.

---

## 1. The Problem

A single UPI payment appears in **multiple places simultaneously**:

| Source | What it shows |
|---|---|
| Bank statement | Raw debit — minimal description |
| UPI app (Paytm / PhonePe / GPay) | Rich metadata — merchant name, category, order ID |
| Merchant gateway (Razorpay / BharatPe) | Settlement batch — multiple payments merged |

**Result:** 2–3 duplicate records per transaction, each with partial information.

**Goal:** Merge duplicates → keep one canonical record → enrich with metadata from all sources.

---

## 2. Source of Truth Strategy

| Source | Role |
|---|---|
| Bank statement | **Financial truth** — amount, date, direction |
| UPI apps | **Metadata enrichment** — merchant name, category |
| Merchant gateways | **Settlement reconciliation** — batch → individual |

Bank statement is always primary. UPI/gateway data enriches it.

---

## 3. System Architecture

```
User Upload (PDF / CSV)
        │
        ▼
File Type Detection
        │
        ▼
Raw Extraction
  pdf_extractor.py  ←── word-coordinate layout (not table parsing)
  csv_extractor.py  ←── Paytm / PhonePe / GPay / Razorpay / BharatPe
        │
        ▼
Transaction Reconstruction
  transaction_builder.py  ←── groups multi-line PDF rows into single records
        │
        ▼
Column Mapping  (config/column_mappings.yaml)
  Paytm: "UPI Ref No." → utr, "Transaction Details" → description
  PhonePe: "Type" → direction, "Amount" → amount
  GPay: "UTR" → utr, "UPI ID" → payee_upi
  Razorpay: "Payment ID" → transaction_id, "Created At" → datetime
        │
        ▼
Normalization → Canonical Master Schema (20 fields)
        │
        ▼
Matching Engine
  1. UTR exact match
  2. Fingerprint: hash(date + amount + utr)
  3. Amount + time window (±2 min)
  4. Fuzzy merchant name (rapidfuzz)
        │
        ▼
Deduplication
  Bank row = canonical
  UPI row = metadata source
        │
        ▼
Categorization  (config/category_rules.yaml)
  Keyword rules → 15 expense categories
  (ported from pnl_report.py EXPENSE_RULES)
        │
        ▼
Reports (output/excel_exporter.py)
  Sheets: Transactions | Reconciled | Unmatched | Category Summary | Income vs Expense
```

---

## 4. Canonical Master Schema

All sources normalize to this format:

| Field | Description |
|---|---|
| `transaction_id` | Unique ID (UTR or generated) |
| `date` | Transaction date |
| `time` | Transaction time |
| `datetime` | Combined datetime |
| `amount` | Absolute amount |
| `direction` | `debit` or `credit` |
| `merchant` | Cleaned merchant name |
| `description` | Raw + parsed description |
| `category` | Classified category |
| `payment_method` | UPI / NEFT / RTGS / IMPS / CASH |
| `utr` | UTR / reference number |
| `order_id` | Order ID (if available) |
| `payer_upi` | Sender UPI ID |
| `payee_upi` | Receiver UPI ID |
| `bank_account` | Source bank account |
| `source_type` | `bank` / `upi_app` / `gateway` |
| `source_name` | YES Bank / Paytm / PhonePe / HDFC |
| `source_file` | Original uploaded filename |
| `confidence_score` | Extraction quality (0–1) |
| `raw_text` | Original line before parsing |

---

## 5. What's Already Built (Phase 0)

| Script | Capability | Reuse in `finance/` |
|---|---|---|
| `scripts/bank_statement_extractor.py` | YES Bank PDF extraction — word-coordinate layout, multi-line fix, UPI metadata parsing | → `finance/extractors/pdf_extractor.py` |
| `scripts/pnl_report.py` EXPENSE_RULES | 15-category keyword classifier | → `finance/categorization/categorizer.py` + `config/category_rules.yaml` |
| `scripts/check_others.py` | Diagnostic for unclassified rows | → debugging utility |

---

## 6. Planned Folder Structure

```
finance/                          ← completely self-contained package
  __init__.py
  main.py                         ← CLI entry: python -m finance.main <file>

  extractors/
    __init__.py
    pdf_extractor.py              ← extends bank_statement_extractor.py logic
    csv_extractor.py              ← Paytm, PhonePe, GPay, Razorpay, BharatPe

  parsers/
    __init__.py
    paytm_parser.py
    phonepe_parser.py
    bank_parser.py                ← YES Bank, HDFC

  matching/
    __init__.py
    fingerprint.py                ← hash(date + amount + utr)
    transaction_matcher.py        ← UTR → fingerprint → amount+time → fuzzy

  categorization/
    __init__.py
    categorizer.py                ← keyword rules from YAML config

  output/
    __init__.py
    excel_exporter.py             ← 5-sheet workbook

  config/
    column_mappings.yaml          ← source column → canonical field mappings
    category_rules.yaml           ← expense/income classification rules

src/whatsapp/handlers/
  ledger_handler.py             ← THIN ADAPTER ONLY: WhatsApp intent → finance.main
```

**Rule: `finance/` has zero imports from `src/`.** It works standalone (CLI) and via WhatsApp.

---

## 7. WhatsApp Integration (LedgerWorker)

Three workers, one Gatekeeper, one WhatsApp number:
- **AccountWorker** (`account_handler.py`) — existing, DB queries (dues, payments, reports)
- **OwnerWorker** (`owner_handler.py`) — existing, operational (onboarding, checkout, occupancy)
- **LedgerWorker** (`ledger_handler.py`) — planned, bank statement ingestion + reconciliation

LedgerWorker examples:

```
WhatsApp: "upload bank statement" → LedgerWorker → finance.main(file) → reply with summary
WhatsApp: "show march P&L"       → LedgerWorker → finance.main(query) → P&L table
WhatsApp: "what's unreconciled?" → LedgerWorker → unmatched sheet → reply
```

**Access:** admin + power_user only (financial reports are sensitive — same policy as existing report intents).

---

## 8. Sources Supported

| Source | Format | Parser |
|---|---|---|
| YES Bank | PDF | `pdf_extractor.py` (word-coordinate) |
| HDFC Bank | PDF / CSV | `pdf_extractor.py` / `csv_extractor.py` |
| Paytm | CSV export | `paytm_parser.py` |
| PhonePe | CSV export | `phonepe_parser.py` |
| Google Pay | CSV export | `csv_extractor.py` |
| Razorpay | CSV export | `csv_extractor.py` |
| BharatPe | CSV export | `csv_extractor.py` |

---

## 9. Matching Engine Detail

Priority order:

1. **UTR exact match** — 100% confidence, direct link
2. **Fingerprint match** — `hash(date + amount + utr)` — catches format variations
3. **Amount + time window** — same amount within ±2 minutes
4. **Fuzzy merchant match** — `rapidfuzz` token_sort_ratio ≥ 85

Merge rule: bank row is canonical, UPI row provides merchant/description enrichment.

---

## 10. PDF Extraction Strategy

Problem: `pdfplumber.extract_table()` merges multi-line description cells and drops amounts.

Solution (already implemented in `bank_statement_extractor.py`):
- Extract all words with (x, y) coordinates
- Group words by y-coordinate → rows
- Assign each word to a column by x-coordinate range (detected from header)
- Multi-line descriptions naturally group to one transaction

Accuracy: ~70% (table parsing) → ~98% (coordinate-based).

---

## 11. Libraries

```
pdfplumber    ← PDF word extraction with coordinates
pandas        ← DataFrame operations
rapidfuzz     ← fuzzy merchant name matching
regex         ← UPI ID, UTR, amount extraction
dateparser    ← flexible date parsing across formats
openpyxl      ← Excel output with formatting
PyYAML        ← config/column_mappings.yaml, config/category_rules.yaml
```

---

## 12. Build Phases

| Phase | Scope | Depends on |
|---|---|---|
| Phase 0 | `scripts/bank_statement_extractor.py` + `pnl_report.py` | DONE |
| Phase 1 | `finance/extractors/` — extend PDF + add CSV parsers | Phase 0 |
| Phase 2 | `finance/matching/` — fingerprint + UTR deduplication | Phase 1 |
| Phase 3 | `finance/categorization/` — port EXPENSE_RULES to YAML | Phase 0 |
| Phase 4 | `finance/output/` — 5-sheet Excel export | Phase 1–3 |
| Phase 5 | `src/whatsapp/handlers/ledger_handler.py` | Phase 1–4 |
| Phase 6 | Gatekeeper routing — add financial intents | Phase 5 |
