# Business-Logic Divergence — exact formulas per implementation (2026-06-15)

For each concept: every place it's computed, the exact formula, and where they disagree.
Phase-2 fix is in [README.md](README.md#phase-2--the-fix-plan-no-code-changed-yet).

---

## DUES {#dues}

"What does this tenant owe this month?" — **8 confirmed implementations** (+3 bot/rollover
helpers located but not byte-compared: `_shared.build_dues_snapshot:406`,
`tenant_handler._my_balance:54`, `monthly_rollover._prev_outstanding:38`).

Two families:
- **SPLIT** — handles first-month by separating prorated rent from deposit, applies
  rent-overflow→deposit, returns `rent_dues` + `deposit_due` separately.
- **BUNDLED** — treats `RentSchedule.rent_due` (which already bundles prorated+deposit−booking
  in the check-in month) as one number and subtracts payments.

| # | Impl | File:line | Family | First-month adj | Subtracts booking | Day-wise | no_show | Scope |
|---|------|-----------|--------|-----------------|-------------------|----------|---------|-------|
| 1 | `get_tenant_dues` | [tenants.py:374](../../../src/api/v2/tenants.py#L374) | SPLIT | ✅ `prorated+adj` | ✅ | ✅ | n/a (single) | current month |
| 2 | `list_tenants` | [tenants.py:100](../../../src/api/v2/tenants.py#L100) | BUNDLED | ❌ no split | ❌ **(monthly)** | ✅ | shows | current month |
| 3 | kpi overdue tile | [kpi.py:245](../../../src/api/v2/kpi.py#L245) | SPLIT | ❌ **drops adj** | ✅ | ✅ | **included** | current month |
| 4 | kpi dues panel | [kpi.py:585](../../../src/api/v2/kpi.py#L585) | SPLIT | ❌ **drops adj** | ✅ | ✅ | **excluded** | current month |
| 5 | recent-checkins balance | [kpi.py:1287](../../../src/api/v2/kpi.py#L1287) | BUNDLED | n/a (RS) | via RS only | counts rent pmts only | active | first month |
| 6 | `collection_summary.pending` | [reporting.py:242](../../../src/services/reporting.py#L242) | BUNDLED | n/a | ✅ via paid | ❌ monthly only | active | current month |
| 7 | `reminders/overdue` | [reminders.py:123](../../../src/api/v2/reminders.py#L123) | BUNDLED | ❌ no split | ✅ via paid | ❌ monthly only | active | current month |
| 8 | `_calc_outstanding_dues` | [account_handler.py:985](../../../src/whatsapp/handlers/account_handler.py#L985) | BUNDLED | ❌ no split | ✅ via paid | per RS rows | active | **all unpaid months** |

### Canonical formula (impl #1, the target to standardise on)
```
# First month (checkin month == period):
prorated            = prorated_first_month_rent(agreed_rent, checkin)
effective_prorated  = max(0, prorated + adjustment)             # ← applies waiver
rent_overflow       = max(0, rent_paid_this_period - effective_prorated)
effective_dep_paid  = deposit_paid_alltime + rent_overflow
rent_dues           = max(0, effective_prorated - rent_paid_this_period)
deposit_due         = max(0, deposit_agreed - effective_dep_paid - booking_amount)

# Normal month:
rent_dues   = max(0, (RS.rent_due + adjustment) - rent_paid_this_period)
deposit_due = max(0, deposit_agreed - deposit_paid_alltime - booking_amount)

# Day-wise:
rent_dues   = max(0, nights*daily_rate - (all_payments + booking_amount))
```
where `rent_paid_this_period` = `SUM(amount) WHERE for_type=rent AND period_month=period AND is_void=False`.

### Confirmed divergences
- **D1 (HIGH)** — #2 `list_tenants` monthly branch: `dues = max(rd + adj − paid, 0)` where
  `paid` lumps **rent + deposit** payments and `rd` is bundled. A tenant who paid only a
  *deposit* this month has it subtracted from *rent* dues → shows as rent-paid in the Manage list
  while #1 (their dues page) still shows rent owing. Also never subtracts `booking_amount` for
  monthly. → list ≠ dues page.
- **D2 (HIGH)** — #3 (tile) filters `status IN (active, no_show)` ([kpi.py:240](../../../src/api/v2/kpi.py#L240));
  #4 (panel) filters `status == active` ([kpi.py:581](../../../src/api/v2/kpi.py#L581)). Tile count
  includes pre-checked-in no_show tenants the panel omits → **tile number ≠ panel list length**.
- **D3 (MED)** — #3 and #4 first-month branch use bare `prorated` (no `+ adjustment`), while #1
  uses `prorated + adjustment`. First-month tenant with a waiver shows wrong dues on the home
  tile/panel. (#3/#4 normal-month branch *does* include adjustment via `eff_due` — only the
  first-month branch drops it.)
- **D4 (structural)** — bundled vs split families produce different numbers wherever an
  overpayment on rent should overflow to deposit, or a deposit/booking interacts with first-month
  rent. They've been hand-synced but cannot stay in sync without a shared function.
- **#8 scope difference (by design, undocumented)** — checkout deducts **all** unpaid months;
  the dashboard shows only the current month. Correct for checkout, but the number a receptionist
  sees at checkout won't match the dues tile for a tenant with arrears. Document it.

---

## OCCUPANCY / BEDS {#occupancy}

**Canonical:** [src/services/occupancy.py](../../../src/services/occupancy.py)
- `total_beds = SUM(Room.max_occupancy) WHERE is_staff_room=False AND room_number!='000'`
- `occupied = active (capped per-room at max_occupancy; premium=max_occ else 1) + no_show (checkin<=today)`

| Impl | File:line | total_beds | occupied_beds | Matches canonical? |
|---|---|---|---|---|
| `occupancy.py` | [occupancy.py:9](../../../src/services/occupancy.py#L9) | canonical | canonical | — |
| kpi.py | [kpi.py:34](../../../src/api/v2/kpi.py#L34) | calls service | calls service | ✅ |
| analytics.py | [analytics.py:154](../../../src/api/v2/analytics.py#L154) | **inline** (same filter) | calls service | ✅ (inline total matches) |
| unit_economics.py | [unit_economics.py:43](../../../src/services/unit_economics.py#L43) | inline (same filter) | **inline, active-only** | ❌ **O1 — omits no_show** |

- **O1 (MED)** — `unit_economics.occupied_beds` ([unit_economics.py:71](../../../src/services/unit_economics.py#L71))
  counts active only; canonical adds no_show with `checkin<=today`. With any pre-checked-in
  no_show, the Finance **Unit-Economics card** shows lower occupancy than the Finance
  **Occupancy tab** and home tile — on the same page.
- `total_beds` is consistent everywhere (good).

### TOTAL_BEDS constant {#total_beds}
Live value = **298**. Live app derives beds dynamically (fine). Stale literals in scripts:

| File:line | Value | Live-app? |
|---|---|---|
| [scripts/full_report.py:9](../../../scripts/full_report.py#L9) | 291 | script |
| [scripts/import_april.py:670](../../../scripts/import_april.py#L670) | 291 | script |
| [scripts/pg_charts.py:23](../../../scripts/pg_charts.py#L23) | 293 | script |
| [scripts/ebitda_matrix_jun2026.py:23](../../../scripts/ebitda_matrix_jun2026.py#L23) | 297 | script |
| [scripts/export_opex_comparison.py:27](../../../scripts/export_opex_comparison.py#L27) | 297 | script |
| gsheets.py / clean_and_load.py / apps_script.js / dashboard_webapp.js | 298 | ✅ correct |

→ **B1 (LOW):** reports generated by the 291/293/297 scripts compute wrong occupancy.

---

## COLLECTION / CASH {#collection}

**Canonical:** `collection_summary` ([reporting.py:71](../../../src/services/reporting.py#L71)).
`Total Collection = rent_collected + maintenance_collected` (period-scoped); deposits/bookings
tracked separately; frozen months Feb/Mar/Apr use a verified sheet override.

| Impl | File:line | What it sums | Used by |
|---|---|---|---|
| `collection_summary` | reporting.py:71 | rent+maint, period-scoped; verified override | PWA collection pages + bot monthly report |
| Cash tab | [finance.py:125](../../../src/api/v2/finance.py#L125) | **cash + rent only**, date-scoped | Finance ▸ Cash tab |
| Bot Yearly Report | [account_handler.py:2253](../../../src/whatsapp/handlers/account_handler.py#L2253) | cash+upi+maint inline, **no verified override** | bot `yearly report` |
| unit_economics `total_collected` | [unit_economics.py:126](../../../src/services/unit_economics.py#L126) | own sum | Finance ▸ Unit-Economics |

- **C1 (LOW)** — Bot Yearly Report sums Feb/Mar/Apr from DB; the monthly report (via
  `collection_summary`) shows verified sheet totals → bot yearly ≠ monthly for frozen months.
- **C2 (LOW)** — Cash tab "collected" excludes maintenance-cash and deposit-cash; it's a
  cash-drawer figure, but labelled "collected" like the canonical one → confusing and can
  undercount physical cash.

---

## P&L / REVENUE {#pnl}

| Impl | File:line | Source | true_revenue definition |
|---|---|---|---|
| Live P&L | [finance.py:454](../../../src/api/v2/finance.py#L454) | `bank_transactions` + cash payments (real-time) | `gross(upi_batch+direct_neft+cash_db) − security_deposits(checkin-month agreement value)` |
| Verified P&L | `pnl_builder.py` (via `/finance/pnl/excel`) | hardcoded verified Oct'25–Apr'26 | verified figures |
| Unit-Economics | [unit_economics.py:181](../../../src/services/unit_economics.py#L181) | `bank` + cash_rent | `gross_bank_income + cash_rent − deposits_held` |

- **P1 (MED)** — Live P&L computes from DB; verified P&L is hardcoded. They reconcile only when
  someone manually patches `bank_transactions` (the pending-tasks log carries standing
  "UPDATE … so live /finance/pnl matches pnl_builder" items). → Finance P&L tab ≠ downloaded Excel.
- **P2 (MED)** — Live P&L and Unit-Economics each define `true_revenue` with a *different deposit
  basis* (`security_deposits` = agreement value for tenants checking in that month, vs
  `deposits_held`). On the same Finance page the P&L total and the per-bed revenue KPI won't
  reconcile.

---

## CHECKOUT / REFUND {#checkout}

**Refund formula is consistent** across PWA, backend, and bot:
```
forfeited if notice_date is None (or manual emergency forfeit; day-wise = no deposit)
refund = max(security_deposit − maintenance_fee − pending_dues − deductions, 0)
```
- Frontend: `web/app/checkout/new/page.tsx` (client calc; backend re-validates ±100).
- Backend validate+persist: [checkout.py:138-159](../../../src/api/v2/checkout.py#L138).
- Bot: `owner_handler._build_checkout_summary` (maintenance_fee subtraction confirmed fixed
  in the 2026-05-28 changelog entry).

**The variable input is `pending_dues`:** the checkout prefetch sources it from
`_calc_outstanding_dues` ([checkout.py:45](../../../src/api/v2/checkout.py#L45)) = dues impl #8
(all unpaid months, bundled) — not `get_tenant_dues`. So the deduction at checkout can differ
from what the tenant's dues page shows. Folding #8 into the shared `compute_tenant_dues(scope="all_outstanding")`
in Phase 2 fixes this while preserving the (correct) all-arrears behaviour.

Notices page `deposit_eligible`/`autoRefund` — the 2026-06-08 audit flagged `deposit_eligible`
always-True; pending-tasks log records it fixed (`now checks notice_date`). **Re-confirm in Phase 2.**
