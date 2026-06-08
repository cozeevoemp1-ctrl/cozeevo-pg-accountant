# PG Accountant Documentation Index

**Master documentation organized into 5 categories. Each file is canonical for its topic — no duplicates.**

---

## 1. ARCHITECTURE & DESIGN (System-level overview)

Understand how the system is built and how components interact.

| File | Purpose |
|------|---------|
| **[BRAIN.md](BRAIN.md)** | Master reference — architecture, schema overview, workers, intents, master data, revenue calculations |
| **[DATA_MODEL.md](DATA_MODEL.md)** | Complete DB schema — 26 tables, ERD, enums, constraints, relationships |
| **[SYSTEM_SPEC.md](SYSTEM_SPEC.md)** | Technical architecture — stack, APIs, data flow, deployment |
| **[INTEGRATIONS.md](INTEGRATIONS.md)** | External APIs — WhatsApp, Sheets, Supabase, Groq, storage |

---

## 2. BUSINESS LOGIC & RULES (Operational rules & calculations)

How money, occupancy, rent, and payments work.

| File | Purpose |
|------|---------|
| **[REPORTING.md](REPORTING.md)** | Financial formulas — P&L, dues, occupancy, proration, notice logic, deposit handling |
| **[BUSINESS_LOGIC.md](BUSINESS_LOGIC.md)** | Calculation rules — occupancy, rent, expenses, billing, role-based access |
| **[SHEET_LOGIC.md](SHEET_LOGIC.md)** | Parsing rules for Excel → Sheet sync — Chandra, exits, balance, messy cells |
| **[EXCEL_IMPORT.md](EXCEL_IMPORT.md)** | Import workflow — Excel → Sheet → DB, single parser, migration strategy |
| **[RENT_RECONCILIATION.md](RENT_RECONCILIATION.md)** | Reconciling rent records across sources |

---

## 3. OPERATIONS & PROCEDURES (How to use the system)

Step-by-step guides, command references, deployment.

| File | Purpose |
|------|---------|
| **[BOT_FLOWS.md](BOT_FLOWS.md)** | Intent catalog — all 40+ WhatsApp commands, role flows, pending state machine |
| **[RECEPTIONIST_CHEAT_SHEET.md](RECEPTIONIST_CHEAT_SHEET.md)** | Quick command reference for Lokesh (staff) — show master data, bookings, payments, notices |
| **[DEPLOYMENT.md](DEPLOYMENT.md)** | VPS setup & deployment — nginx, systemd, SSL, git auto-deploy |
| **[TESTING.md](TESTING.md)** | Test SOP — golden suite execution, thresholds, pre-production checklist |
| **[CONVERSATION_FRAMEWORK.md](CONVERSATION_FRAMEWORK.md)** | Multi-turn WhatsApp dialog flow — context, state, disambiguation |

---

## 4. REFERENCE DATA & AUDIT TRAILS (Lookup tables, constants, historical records)

Configuration, master data, audit logs, bug tracking, change history.

| File | Purpose |
|------|---------|
| **[MASTER_DATA.md](MASTER_DATA.md)** | Floor-by-floor room layouts, bed counts, staff rooms, building constants |
| **[WHATSAPP_TEMPLATES.md](WHATSAPP_TEMPLATES.md)** | Meta WhatsApp template catalog — approval status, parameters, scheduling |
| **[CHANGELOG.md](CHANGELOG.md)** | Session-by-session change history — what was fixed, when, by whom |
| **[BUG_TRACKER.md](BUG_TRACKER.md)** | All historical bugs (BUG-0001 through BUG-0042) with root causes & prevention |
| **[DEPOSIT_REFUND_AUDIT.md](DEPOSIT_REFUND_AUDIT.md)** | Bank CSV import audit — deposit/refund classification per transaction |
| **[SALARY_PAYMENT_AUDIT.md](SALARY_PAYMENT_AUDIT.md)** | Bank CSV import audit — salary/staff payment classification per transaction |

---

## 5. TECHNICAL INTEGRATIONS (Specific tool integrations & helpers)

Tools, scripts, integrations that don't fit other categories.

| File | Purpose |
|------|---------|
| **[APPS_SCRIPT_SYNC.md](APPS_SCRIPT_SYNC.md)** | Google Apps Script — auto-refresh dashboard, report generation |
| **[CASH_EXPENSES_NOTEBOOKS.md](CASH_EXPENSES_NOTEBOOKS.md)** | Expense tracking methodology — notebook ledgers, reconciliation |

---

## 6. PLANNING & STRATEGY (Product direction, not active)

Long-term planning documents — refer for context, don't edit unless planning a new feature.

| File | Purpose |
|------|---------|
| **[planning/PRD.md](planning/PRD.md)** | Product requirements document — vision, scope, success metrics |
| **[planning/FINANCIAL_VISION.md](planning/FINANCIAL_VISION.md)** | Reconciliation engine design (future) |

---

## 7. ARCHIVED AUDITS (Historical analysis — for reference only)

Session A comprehensive audits. Don't edit — kept for historical record.

| Folder | Purpose |
|--------|---------|
| **[audits/2026-06-08-pwa-comprehensive/](audits/2026-06-08-pwa-comprehensive/)** | Session A: 5 domain audits, 87 business rules, 42 historical bugs (2,900 lines) |

**Latest consolidated audit:** [COMPREHENSIVE_AUDIT.md](../COMPREHENSIVE_AUDIT.md) (Session C findings)

---

## How to Use This Index

- **Looking for:** "How does deposit refund work?" → See REPORTING.md §3
- **Looking for:** "What's the bot command for X?" → See BOT_FLOWS.md
- **Looking for:** "How is occupancy calculated?" → See BUSINESS_LOGIC.md
- **Looking for:** "What's in the database?" → See DATA_MODEL.md
- **Looking for:** "How do I deploy to VPS?" → See DEPLOYMENT.md
- **Looking for:** "What are all the bugs?" → See BUG_TRACKER.md

**Rule:** Every topic has ONE canonical file. If you need to add info, find the right file and edit it.

---

## Files to Delete (Redundant)

- `CHEAT_SHEET_PRINTABLE.md` — identical to RECEPTIONIST_CHEAT_SHEET.md
- `audit_premium_2026-04-21.md` — superseded by audits/2026-06-08-pwa-comprehensive/
- `audit_room_anomalies_2026-04-21.md` — superseded by audits/2026-06-08-pwa-comprehensive/
- `audit_missing_fields_2026-04-21.md` — superseded by audits/2026-06-08-pwa-comprehensive/

**Last updated:** 2026-06-08 (Session C)
