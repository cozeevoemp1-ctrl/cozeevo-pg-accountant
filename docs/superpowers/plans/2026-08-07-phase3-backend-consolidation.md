# Phase 3 Backend Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse the 7+3 duplicated monthly-dues implementations into one shared `src/services/dues.py`, retire the legacy PIN checkout stack (D-1 refund hole), delete dead routers, add missing write-dedup guards, serve NOTICE_BY_DAY/TOTAL_BEDS from a config endpoint, and fix the P&L Bank-Charges catch-all — the approved prerequisites (WEB_REBUILD_SPEC.md §3, audit 2026-08-06) before any Web v2 screen is built.

**Architecture:** Mirror the `services/daily_dues.py` consolidation: pure math functions + one canonical SQLAlchemy "paid toward period" clause in `src/services/dues.py`; every API and bot call-site imports from it. Everything else is subtractive (tombstones, deletions) or small additive guards. No schema changes except none — guards use SELECT-before-insert and the existing `uq_payment_unique_hash` partial index.

**Tech Stack:** FastAPI + SQLAlchemy async + Supabase Postgres; Next.js PWA (`web/`); pytest for unit tests; `tests/eval_golden.py` for bot regression.

## Global Constraints

- Never hard-delete financial records; `is_void` only (CLAUDE.md).
- `migrate_all.py` append-only; this plan adds NO migration.
- Frozen months (Dec 2025–Mar 2026) untouched; no data writes in this plan.
- Never reference Sheet columns by index (not touched here).
- Canonical dues formula: `effective_due = rent_due + adjustment`; paid = rent@period + deposit/booking dated-in-month (rules_financial.md §1). First-month RS.rent_due = prorated + deposit − booking_amount field (`first_month_rent_due`).
- KEEP: blacklist REST (Web v2 needs it), `regen-pdf` (pending Kiran task for 10 agreement PDFs), `/api/reconcile` router, reminders GET /overdue.
- Bot behaviour: reminders/tenant messaging stays disabled (rules_no_tenant_comms).

---

### Task 1: `src/services/dues.py` — shared monthly-dues service + unit tests

**Files:**
- Create: `src/services/dues.py`
- Test: `tests/test_dues_logic.py`

**Interfaces (Produces):**
- `period_bounds(period: date) -> tuple[date, date]`
- `paid_toward_period_clause(period_start, period_end)` — SQLAlchemy boolean clause (Formula A paid filter, rent@period OR deposit/booking dated in month)
- `period_remaining(rent_due, adjustment, paid) -> Decimal`
- `first_month_due(agreed_rent, security_deposit, booking_amount, checkin) -> float` — prorated + deposit − booking (pure)
- `monthly_dues(*, period, as_of, checkin_date, agreed_rent, security_deposit, rent_due, adjustment, rent_paid, deposit_paid, booking_paid_rows, booking_amount_field) -> MonthlyDues` — exact port of `get_tenant_dues` split math (first-month proration, rent→deposit overflow, booking_credit, not-yet-checked-in guard)
- `MonthlyDues` dataclass: `rent_dues, deposit_due, credit, is_first_month, not_yet_checked_in, prorated_rent, effective_due, booking_credit_amt` + `.total`
- `outstanding_months(session, tenancy_id) -> list[MonthOutstanding]` — per pending/partial RS row: `period, effective_due, paid, remaining, maintenance_due, maintenance_paid, maintenance_remaining, status, notes`
- Re-exports: `booking_credit`, `daily_dues` from `src.services.daily_dues`

Steps: write failing unit tests (normal month credit, first-month overflow→deposit, booking rows vs field fallback, adjustment waiver, future check-in ⇒ 0, Dec→Jan bounds, `first_month_due` netting), run red, implement, run green, commit.

### Task 2: Wire PWA API call-sites

**Files (modify):**
- `src/api/v2/tenants.py` — `get_tenant_dues` monthly branch (:380-404 math → `monthly_dues`); `list_tenants` (:50-110): replace bundled paid_subq with rent-only/deposit/booking subqueries + `monthly_dues`; dues value = `.total` (fixes D-3, list now matches dues page)
- `src/api/v2/kpi.py` — tile (:262-285) and panel (:632-651) per-row math → `monthly_dues`; recent-checkins fallback (:1340-1343) → `first_month_due`
- `src/api/v2/reminders.py` — `_build_paid_subq` (:37-54) → `paid_toward_period_clause` (adds booking to paid — aligns with canonical rule)
- `src/services/reporting.py` — `_paid_sq` (:258-273) → `paid_toward_period_clause`

Response shapes unchanged. Verify with pytest + manual endpoint smoke.

### Task 3: Wire bot call-sites

**Files (modify):**
- `src/whatsapp/handlers/account_handler.py` — `_calc_outstanding_dues` (:985-1037) → sum over `outstanding_months`; `_query_dues` `_paid_sq` (:1074-1089) → `paid_toward_period_clause`
- `src/whatsapp/handlers/_shared.py` — `build_dues_snapshot` loop (:429-472) → `outstanding_months` (text formatting stays local)
- `src/whatsapp/handlers/tenant_handler.py` — `_my_balance` paid query (:104-117) → shared clause
- `src/services/monthly_rollover.py` — `_prev_outstanding` (:38-72) → shared clause + `period_remaining`

### Task 4: Retire legacy PIN checkout stack

**Files:**
- Modify: `src/api/checkout_router.py` — replace all 6 routes with a single 410 catch-all (pattern: `onboarding_router.py:354-357`)
- Modify: `main.py` — remove `/admin/checkout` (:369) and `/checkout/confirm/{token}` (:375-377) serve routes
- Delete: `static/checkout_admin.html`, `static/checkout_confirm.html`

Safety: v2 (`src/api/v2/checkout.py`) re-validates refund/forfeiture; checkout-confirmation template sends no link → static pages unreachable from live flows.

### Task 5: Delete dead routers + docstring fix

**Files:**
- Delete: `src/api/sync_router.py` (unmounted), `src/api/v2/voice.py`
- Modify: `main.py` — remove ingest block (:193-264), report shell (:295-297), entities block (:384-412) + their includes
- Modify: `src/api/v2/app_router.py` — drop voice import/include (:20, :38)
- Modify: `src/api/onboarding_router.py` — remove `GET /admin/stats` (:362-364); KEEP `regen-pdf`
- Modify: `src/api/v2/auth_hooks.py` — docstring `/api/v2/auth/send-otp` → `/api/v2/app/auth/send-otp` (:6, :11)
- Pre-check: grep web/ + src/ for `/api/ingest`, `/api/entities`, `voice/transcribe`, `admin/stats` consumers before deleting.

### Task 6: Write-dedup guards

**Files (modify):**
- `src/api/v2/finance.py` — `POST /finance/cash/expenses` (:419): before insert, SELECT non-void CashExpense with same `(date, amount, description, paid_by)` → 409 "Duplicate expense"; `POST /finance/cash/counts` (:530): same `(date, amount, counted_by)` → 409
- `src/api/v2/bookings.py` (:264-277) — set `unique_hash` on the advance Payment using the exact `log_payment` recipe (`src/services/payments.py:250-252`, md5 of `tenancy:today:amount:mode::booking`); catch IntegrityError on flush → 409 "Advance already recorded"

### Task 7: `/config` endpoint + web NOTICE_BY_DAY hardcode removal

**Files:**
- Modify: `src/api/v2/app_router.py` — add `GET /config` returning `{notice_by_day: NOTICE_BY_DAY, total_beds: await get_total_revenue_beds(session)}`
- Create: `web/lib/config.ts` — cached `getAppConfig()` + `useAppConfig()` hook (fallback `notice_by_day=5` only until fetch resolves, documented as fallback)
- Modify: `web/app/checkout/new/page.tsx` (:18), `web/app/notices/page.tsx` (:9) — const → hook; `web/app/tenants/[tenancy_id]/edit/page.tsx` (:287-288, :758, :773-775) — literal `5`s → hook value

### Task 8: Classifier Bank-Charges catch-all fix

**Files:**
- Modify: `src/rules/pnl_classify.py:267` — replace `("Bank Charges","Bank Transfer / IMPS / NEFT",["imps","rtgs","neft","yib-neft","net-neft"])` with genuine-fee-narration keywords only (`"neft chg","neft charge","imps chg","imps charge","rtgs chg","rtgs charge"`); add `("Other Expenses","Unclassified Bank Transfer",["imps","rtgs","neft"])` immediately before the catch-all so unmatched transfer principals surface for review instead of booking as opex.
- Verify: existing classified rows untouched (rule applies at import time only); check `scripts/export_unknowns_for_review.py` picks up the new subcategory.

### Task 9: Strip Reminders send UI (keep overdue list)

**Files (modify):**
- `web/app/reminders/page.tsx` — remove `handleSendSingle` (:33-52), `handleSendAll` (:54-70), result banner (:106-121), send-all modal (:208-231), per-row send buttons; retitle page "Overdue dues"
- `web/app/tenants/page.tsx` (:37-38) — tile label "Send Reminders" → "Overdue dues" (href stays)
- `web/lib/api.ts` (:508-509) — remove `sendReminder`
- Backend `/reminders/send*` 410 tombstones stay.

### Task 10: Verification

- `venv/Scripts/python -m pytest tests/test_dues_logic.py tests/test_cash_logic.py tests/test_notice_comprehensive.py -q`
- Start API locally (`venv/Scripts/python main.py`, TEST_MODE=1) → `python tests/eval_golden.py`
- `cd web && npx tsc --noEmit` (or `npm run build`) for the frontend edits
- Manual smoke: `/tenants/list` vs `/tenants/{id}/dues` same tenant same number; `/api/checkout/create` returns 410; `/config` returns `{notice_by_day:5, total_beds:298}`
