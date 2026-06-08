# PG Accountant Documentation

**All documentation organized into 4 folders + planning docs.**

---

## 📐 [architecture/](architecture/) — System Design

How the system is built.

- **[BRAIN.md](architecture/BRAIN.md)** — Master reference (read first every session)
- **[DATA_MODEL.md](architecture/DATA_MODEL.md)** — Complete DB schema (26 tables)
- **[SYSTEM_SPEC.md](architecture/SYSTEM_SPEC.md)** — Technical stack & APIs
- **[DATA_ARCHITECTURE.md](architecture/DATA_ARCHITECTURE.md)** — Data flow & relationships
- **[INTEGRATIONS.md](architecture/INTEGRATIONS.md)** — WhatsApp, Sheets, Supabase, Groq

---

## 💼 [business/](business/) — Business Rules

How money, occupancy, and rent work.

- **[REPORTING.md](business/REPORTING.md)** — Financial formulas (P&L, dues, proration)
- **[BUSINESS_LOGIC.md](business/BUSINESS_LOGIC.md)** — Calculation rules & access control
- **[SHEET_LOGIC.md](business/SHEET_LOGIC.md)** — Excel parsing rules
- **[EXCEL_IMPORT.md](business/EXCEL_IMPORT.md)** — Import workflow (Excel → Sheet → DB)
- **[RENT_RECONCILIATION.md](business/RENT_RECONCILIATION.md)** — Rent record reconciliation

---

## ⚙️ [operations/](operations/) — How to Use the System

Step-by-step guides for users.

- **[BOT_FLOWS.md](operations/BOT_FLOWS.md)** — All WhatsApp commands (40+)
- **[RECEPTIONIST_CHEAT_SHEET.md](operations/RECEPTIONIST_CHEAT_SHEET.md)** — Lokesh's quick reference
- **[DEPLOYMENT.md](operations/DEPLOYMENT.md)** — VPS setup & auto-deploy
- **[TESTING.md](operations/TESTING.md)** — Test SOP & golden suite
- **[CONVERSATION_FRAMEWORK.md](operations/CONVERSATION_FRAMEWORK.md)** — Multi-turn dialog flow

---

## 📚 [reference/](reference/) — Lookup Tables & Audit Trails

Configuration, master data, and records.

- **[MASTER_DATA.md](reference/MASTER_DATA.md)** — Room layouts, bed counts, building data
- **[WHATSAPP_TEMPLATES.md](reference/WHATSAPP_TEMPLATES.md)** — Meta template catalog
- **[BUG_TRACKER.md](reference/BUG_TRACKER.md)** — All 42 historical bugs (BUG-0001+)
- **[CHANGELOG.md](reference/CHANGELOG.md)** — Session-by-session changes
- **[DEPOSIT_REFUND_AUDIT.md](reference/DEPOSIT_REFUND_AUDIT.md)** — Bank CSV audit (deposits)
- **[SALARY_PAYMENT_AUDIT.md](reference/SALARY_PAYMENT_AUDIT.md)** — Bank CSV audit (salaries)
- **[CASH_EXPENSES_NOTEBOOKS.md](reference/CASH_EXPENSES_NOTEBOOKS.md)** — Expense tracking
- **[APPS_SCRIPT_SYNC.md](reference/APPS_SCRIPT_SYNC.md)** — Google Apps Script integration

---

## 🗺️ [planning/](planning/) — Product Strategy

Long-term vision (reference only).

- **[PRD.md](planning/PRD.md)** — Product requirements document
- **[ROADMAP.md](planning/ROADMAP.md)** — Feature priorities & timeline
- **[FINANCIAL_VISION.md](planning/FINANCIAL_VISION.md)** — Reconciliation engine design (future)

---

## 📋 [audits/](audits/) — Historical Audit Reports

Session A comprehensive analysis (reference only).

- **[2026-06-08-pwa-comprehensive/](audits/2026-06-08-pwa-comprehensive/)** — 5 domain audits, 87 business rules, 42 bugs (2,900 lines)

**Latest consolidated audit:** [COMPREHENSIVE_AUDIT.md](../COMPREHENSIVE_AUDIT.md) (Session C findings, root level)

---

## 🔍 How to Find Things

| Need to know... | Look in... |
|---|---|
| System architecture | architecture/BRAIN.md |
| Database schema | architecture/DATA_MODEL.md |
| How payments work | business/REPORTING.md |
| WhatsApp commands | operations/BOT_FLOWS.md |
| Room layouts | reference/MASTER_DATA.md |
| What bugs exist | reference/BUG_TRACKER.md |
| How to deploy | operations/DEPLOYMENT.md |
| What changed last session | reference/CHANGELOG.md |

---

**Last updated:** 2026-06-08 | **Status:** Clean — all docs organized into 4 folders + planning
