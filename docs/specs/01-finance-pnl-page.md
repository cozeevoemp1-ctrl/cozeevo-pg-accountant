# Spec 01 — Finance page rework: one P&L engine, drill-down, reclassify, guardrails

> Status: **Phase 1 DONE 2026-08-14** (on development; verified vs July close ₹14,00,408 / 31.7%).
> Phases 2–6 pending. Layout note from Kiran: keep the P&L SHORT — collapsed top-level
> nodes, SAC-style hierarchy expansion (implemented in Phase 1's PnlMonthCard).
> Invocation per phase: "Read docs/specs/01-finance-pnl-page.md, implement Phase N exactly as specified."
> One phase = one build/test/commit cycle. Do not start Phase N+1 until Phase N is verified.

## Goal

The Finance page becomes the single place to: upload bank CSVs → regenerate the P&L →
view any month's P&L on screen → click any line to see the exact transactions behind it →
reclassify a wrong transaction → and (later phases) view a Balance Sheet and Cash Flow
built on the same numbers. **Every number on screen is produced by the same engine that
produces the SOP Excel — zero parallel math.**

## First principles (the whole design in 5 lines)

1. **One engine.** `_compute_dynamic_pnl_months()` (finance.py) + frozen figures in
   `pnl_builder.py` are THE P&L. Screen JSON, Excel download, drill-down — all read from it.
2. **Every displayed line is a query.** If a line can't list the transactions that sum to it,
   it doesn't go on screen. Drill-down is free when rule 1 holds.
3. **Corrections are data, not edits.** Reclassification writes a locked override + audit row;
   re-uploads and re-classification passes must never undo it.
4. **Guardrails at the door.** Bad input is rejected/flagged at upload time (already mostly
   built: statement self-reconciliation, row-hash dedup, frozen-month rejects).
5. **Parity is tested, not promised.** A parity check (screen JSON total == Excel cell) runs
   in the verification step of every phase.

## The deviation being fixed (audit result, 2026-08-14)

`src/reports/three_statement.py` (powers the current on-page P&L/BS/CF card) diverges from
the SOP (`memory/sop_pnl.md`) in at least 6 ways:

| # | three_statement.py does | SOP says |
|---|---|---|
| 1 | Income = only categories "Rent Income" + "Other Income" | ALL income categories except `Advance Deposit` + `Non-Operating` |
| 2 | Cash = rent-only cash payments | ALL cash by receipt date + `offline_cash` adjustment |
| 3 | No "Less: Security Deposits received" line | Gross Inflows − refundable deposits received that month = True Revenue |
| 4 | Ignores `pnl_monthly_adjustments` entirely (no rent_paid_cash / cash_expense / offline_cash) | The 3 manual cash figures are part of the month's P&L |
| 5 | Furniture & Fittings treated as CAPEX + depreciation | CAPEX abolished 2026-05-13 — furniture is OPEX |
| 6 | Cash & Bank = cumulative Σ(txns) since start | Closing balance = statement's chronologically-last balance (`_closing()`), reconciled at upload |

Also BS liability = `SUM(security_deposit)` where SOP refund-owed = `deposit − maintenance_fee`.

**Consequence: the P&L section of `three_statement.py` is retired.** Its BS and CF ideas
survive but get rebuilt (Phases 5–6) on top of SOP outputs. Until then the BS/CF sections
show a "being rebuilt" note or stay hidden — no wrong numbers on screen.

## Design decisions

- **New endpoint `GET /finance/pnl/month?month=YYYY-MM`** — returns ONE month's SOP-format
  P&L as JSON. Frozen month → served from `pnl_builder.MONTHS` verified data (read-only
  flag `is_frozen: true`). Dynamic month → the record from `_compute_dynamic_pnl_months()`.
  Response = list of typed lines: `{key, label, amount, drillable, section}` with sections
  `income / deposits / opex / excluded / result`. The engine already produces these values;
  this endpoint only reshapes — **no new math**.
- **New endpoint `GET /finance/pnl/line-items?month=&key=`** — the transactions behind one
  line. Each line key maps to exactly one deterministic query (same WHERE clauses the engine
  uses — factor the WHERE fragments into small shared helpers inside finance.py so engine
  and drill-down cannot drift). Returns rows + `sum` + `matches_line: bool`.
  - `income.bank.<ACCT>` → bank_transactions income, category NOT IN (Advance Deposit, Non-Operating), account
  - `income.cash` → payments cash by receipt date (+ `offline_cash` shown as a pseudo-row from adjustments)
  - `deposits.received` → the deposit query the engine uses for "Less: Security Deposits"
  - `opex.<Category>` → bank_transactions expense of that category (+ cash_expenses rows for the cash-expense category, + adjustment pseudo-rows for rent_paid_cash / cash_expense)
  - `excluded.refunds` / `excluded.nonop` → their categories
  - Frozen months: `drillable: false` (figures are hardcoded; nothing to list).
- **Reclassification** — `PATCH /finance/transactions/{id}` body `{category, sub_category?}`:
  - New columns on `bank_transactions`: `manual_category BOOLEAN server_default false`
    (migrate_all append-only; NULL-safe read per rules_server_default_nulls).
  - Sets category + `manual_category=true` + AuditLog (old→new, changed_by, source="app").
  - `classify_txn` re-runs (`_auto_reconcile`, upload passes, `_detect_tenant_refunds`)
    MUST skip rows with `manual_category=true`. Re-upload of the same file is a hash-dup →
    row untouched → override survives. Category must be one of `EXPENSE_CATS` (+ income cats) — 422 otherwise.
  - Keyword RULES stay in `src/rules/pnl_classify.py`, edited in a Claude session, not from the UI (keeps the UI simple; rules affect future imports, overrides fix the past).
- **Page layout (top→bottom):** UploadCard → Generate P&L (Excel) → Manual cash figures →
  **P&L (month picker, SOP lines, tap line = drill-down sheet, tap txn = reclassify)** →
  Balance Sheet (Phase 5) → Cash Flow (Phase 6) → Occupancy → Investment (unchanged).
- **Reuse, don't rebuild:** `Sheet`/`Modal` from `web/components/ui/modal.tsx`, `rupee*` from
  `lib/format.ts`, month picker pattern from three-statement-tab. Read `docs/UI_SYSTEM.md` first.
- **Parity check:** `tests/test_pnl_parity.py` — for the latest dynamic month: fetch
  `/finance/pnl/month`, rebuild the Excel via `build_pnl_workbook(dynamic_data)`, assert the
  month column's Gross Inflows / True Revenue / Total Opex / Net Operating equal the JSON
  (±1 rupee). Plus per-line: `line-items.sum == line.amount` for every drillable line.

## Guardrails (what exists vs what's added)

| Scenario | Today | Action |
|---|---|---|
| Same file / same rows uploaded twice | Row-hash `ON CONFLICT DO NOTHING`; response reports `duplicate_count` | Keep. UI must show "X new / Y duplicates skipped" prominently (US-4.1) |
| Truncated/misparsed CSV | Statement self-reconciliation rejects file (opening+dep−wd≠closing) | Keep. Never bypass |
| "Selected August, uploaded July file" | Upload has no month input — months come from txn dates; `months_affected` returned | Surface it: after upload show "Rows landed in: Jul 2026" and if that ≠ current adjustments-card month, show an explicit notice (US-4.2) |
| Upload contains frozen-month rows | Rows import but frozen P&L ignores them | Add notice: "N rows fall in verified months — frozen figures unchanged" (US-4.2) |
| THOR file uploaded as HULK | **Nothing** | Parse account number from statement header; keep a small map {account_no → THOR/HULK}; mismatch → 400 with clear message (US-4.3) |
| Manual cash figures saved twice / partial | Upsert; frozen months 400; partial-update fixed 2026-08-14 | Keep; audited since 2026-08-14 |
| Manual figures for a month with no bank data | Currently allowed silently | Allow (figures can precede the CSV) but show "no bank statement uploaded for this month yet" hint (US-4.2) |
| Reclassify then re-upload / re-run classifier | n/a today | `manual_category` lock (Phase 3) |

## Phases & user stories

### Phase 1 — SOP P&L on screen (replaces three-statement P&L section) — ✅ DONE 2026-08-14
Built: `GET /finance/pnl/month` (+ pure tree builders `_pnl_tree` / `_build_pnl_tree_dynamic`
/ `_build_pnl_tree_frozen` in finance.py), `web/components/finance/pnl-month-card.tsx`
(SAC-style expandable hierarchy, 5 collapsed top-level rows), page swap (ThreeStatementTab
removed from page; file kept for Phase 5–6 reference), `tests/test_pnl_tree.py` (5 parity
tests, wired into pre-push). Live check: Jun'26 net ₹8,95,323 / Jul'26 net ₹14,00,408 (31.7%)
== Kiran's verified July close. Node keys (income.bank.THOR, opex.<Category>, deposits.*)
are the Phase-2 drill-down contract.
- **US-1.1** As owner, I pick a month on the Finance page and see that month's P&L with the
  exact SOP lines (income rows per account, cash line, Gross Inflows, Less: deposits,
  True Revenue, OPEX by category, excluded items inline, Net Operating + margin) — the same
  numbers as the Excel column for that month.
  *Accept:* JSON from `/finance/pnl/month` renders; parity test passes; frozen month shows a "verified — frozen" badge; month with no data shows empty-state, not zeros.
- **US-1.2** As owner, after uploading a CSV the P&L card refreshes and reflects the new rows
  (existing `refreshKey` remount pattern).
- Backend: endpoint + reshape only. Frontend: new `pnl-month-card.tsx`; remove the P&L
  section from `three-statement-tab.tsx` and hide its BS/CF behind a "rebuilding" note.

### Phase 2 — Drill-down
- **US-2.1** As owner, I tap any drillable P&L line and a bottom Sheet lists the transactions
  behind it (date, description, account, amount) with a sum row.
  *Accept:* for every drillable line, `sum == line.amount` (`matches_line` true); mismatch renders a red warning instead of hiding it.
- **US-2.2** As owner, manual figures (offline cash, rent-paid-cash, cash-expense) appear in
  drill-downs as clearly-labelled "manual figure" rows so the sum still matches.
- Backend: `line-items` endpoint sharing WHERE-fragments with the engine.

### Phase 3 — Reclassification
- **US-3.1** As owner, from a drill-down I tap a transaction, pick the correct category from
  the fixed list, and save. The sheet and P&L refresh; the amount moved between lines.
  *Accept:* AuditLog row written; `manual_category=true`; P&L totals change by exactly the amount.
- **US-3.2** As owner, my corrections survive: re-uploading the same file and any future
  classifier pass leaves manually-set categories untouched.
  *Accept:* test — reclassify, re-upload same CSV, category unchanged; run `_auto_reconcile` + `_detect_tenant_refunds`, unchanged.
- Backend: migration (append-only) + PATCH endpoint + skip-locked in the 3 classifier passes.

### Phase 4 — Upload guardrails polish
- **US-4.1** As owner, after upload I see: rows imported, duplicates skipped, months affected,
  refunds auto-reclassified — as a persistent result card, not a vanishing toast.
- **US-4.2** As owner, I'm warned (not blocked) when: uploaded months ≠ the adjustments-card
  month; some rows fall in frozen months; adjustments exist for a month with no bank rows.
- **US-4.3** As owner, uploading a file whose statement account number doesn't match the
  selected THOR/HULK button is rejected with a message naming both accounts.
- Backend: account-number check in `read_statement_summary` + upload endpoint. Frontend: UploadCard result states.

### Phase 5 — Balance Sheet (rebuilt on SOP outputs)
- **US-5.1** As owner, I see a month-end Balance Sheet where: Cash & Bank = statement closing
  balances (`_closing()` per account) + cash-holding adjustment figure; Deposits liability =
  Σ(deposit − maintenance_fee) for active tenants (SOP formula); Retained earnings =
  cumulative SOP Net Operating (frozen months' verified values + dynamic engine months) −
  cumulative excluded outflows; Investor capital from `investment_expenses` (as today).
  *Accept:* balance check badge; every figure traceable to an engine value or a named query; depreciation only if Kiran confirms keeping it — else fixed assets shown at gross (DECIDE AT PHASE START, one question).
- **US-5.2** Drill-down works on BS lines that are transaction-backed (deposits held → tenancy list; capex → txn list).

### Phase 6 — Cash Flow (rebuilt, reconciles to bank)
- **US-6.1** As owner, I see the month's cash flow: start = prior month closing (statement),
  end = this month closing (statement); the movement explained by SOP Net Operating ± deposit
  flows ± excluded items ± financing; a reconciliation badge shows any unexplained gap
  explicitly (never hidden).
  *Accept:* for a fully-uploaded month the gap is < ₹1; gap card names the amount when not.

## Out of scope

- No new classifier-rule editor UI (rules live in `pnl_classify.py`).
- No editing/deleting bank transactions (only category override; amounts/dates immutable).
- No changes to `pnl_builder.py` verified frozen figures.
- No changes to the SOP itself — open SOP question (refund double-subtraction, sop_pnl.md
  rule 8) stays with Kiran; build follows current SOP until he rules.
- No multi-org, no export center, no revival of the orphaned cash-tab/upi-reconcile
  components (separate pending decision).
- No background jobs / queues for upload processing (current in-request flow stays; finding
  12's unbounded reclassification is bounded naturally once Phase 3 makes passes skip-locked
  and per-upload passes stay scoped — do NOT build a worker).

## Verification checklist (every phase)

- [ ] `tsc --noEmit` + `py -3 -m py_compile` on touched files; module import check
- [ ] `tests/test_pnl_parity.py` passes (from Phase 1 onward)
- [ ] Drill-down sums == line amounts for the latest dynamic month (Phase 2+)
- [ ] Do it twice: repeat the same upload/save/reclassify — idempotent, correct message
- [ ] Manual browser test on the live page with the real August data
- [ ] AuditLog rows written for every mutation (reclassify, adjustments)
- [ ] CHANGELOG + this spec's phase marked done; commit on `development`
