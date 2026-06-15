# Connectivity & Logic-Duplication Audit — 2026-06-15

**Goal (Kiran):** Verify every PWA page / KPI tile / endpoint is *connected* to the
canonical logic for its concept — not silently reimplementing the same calculation
with its own endpoint, which causes the same number to differ across screens.

**Method:** Static read of `src/api/v2/*`, `src/services/*`, `src/whatsapp/handlers/*`,
`web/lib/api.ts`, `web/app/**`, `web/components/**`. No code was changed — this is Phase 1
(audit + map). Phase 2 (the fixes) is scoped at the bottom.

> Note: the parallel-agent sweep was blocked by API 529 overload, so this was done
> single-threaded in the main session. Coverage is complete for the financial domains
> (dues, collection, P&L, occupancy, checkout) and the PWA→endpoint map. Three bot-only
> dues helpers (`build_dues_snapshot`, `_my_balance`, `_prev_outstanding`) were located
> but not byte-compared — flagged below as "verify in Phase 2".

---

## The headline

**There is no single `compute_dues()`.** "How much does this tenant owe?" is answered by
**8 confirmed independent implementations** (+3 bot/rollover helpers not yet byte-compared),
each with its own endpoint and its own SQL. They have been hand-synced over many sessions,
but they have **already drifted** — and every future edit risks drifting them again.

This is the exact failure mode from Session E (same payment data filtered differently across
history/dues/P&L) generalised across the whole app.

The same pattern (weaker) exists for **collection**, **occupancy**, and **P&L/revenue**, where
good canonical services *exist* but are bypassed by some callers.

---

## Severity-ranked findings

| # | Sev | Finding | Where | Effect |
|---|-----|---------|-------|--------|
| D1 | 🔴 HIGH | **Manage-Tenants list** dues bundles rent+deposit, subtracts deposit payments from rent, never subtracts `booking_amount` | [tenants.py:100-104](../../../src/api/v2/tenants.py#L100) vs [tenants.py:374-389](../../../src/api/v2/tenants.py#L374) | Same tenant shows different dues in the list vs their dues page; a deposit-only payer looks "rent paid" |
| D2 | 🔴 HIGH | **Dues tile count ≠ its own expansion panel**: tile counts `active+no_show`, panel counts `active` only | [kpi.py:240](../../../src/api/v2/kpi.py#L240) vs [kpi.py:581](../../../src/api/v2/kpi.py#L581) | Tile says N overdue, tapping it lists fewer |
| D3 | 🟠 MED | Both kpi dues copies drop the **waiver/adjustment** on first-month tenants | [kpi.py:255](../../../src/api/v2/kpi.py#L255), [kpi.py:595](../../../src/api/v2/kpi.py#L595) vs [tenants.py:377](../../../src/api/v2/tenants.py#L377) | First-month tenant with a rent waiver shows wrong dues on home tile/panel |
| D4 | 🟠 MED | **8 distinct "owed" implementations**, mostly bundled vs split, no shared function | see [02_LOGIC_DIVERGENCE.md](02_LOGIC_DIVERGENCE.md#dues) | Structural — every screen can drift independently |
| O1 | 🟠 MED | **Unit-Economics occupancy omits no_show**; canonical includes it | [unit_economics.py:71](../../../src/services/unit_economics.py#L71) vs [occupancy.py:51-71](../../../src/services/occupancy.py#L51) | On the *same Finance page*, Occupancy tab and Unit-Economics card show different occupancy % |
| P1 | 🟠 MED | **Live P&L vs verified Excel P&L** computed independently; reconcile only by manual DB patching | [finance.py:454](../../../src/api/v2/finance.py#L454) vs `pnl_builder.py` | Finance P&L tab ≠ downloaded P&L Excel for verified months |
| P2 | 🟠 MED | **3 `true_revenue` definitions** (live P&L, unit-economics, pnl_builder) with different deposit/gross basis | [finance.py:556](../../../src/api/v2/finance.py#L556), [unit_economics.py:181](../../../src/services/unit_economics.py#L181) | KPIs on the Finance page don't reconcile to the P&L |
| C1 | 🟡 LOW | Bot **Yearly Report** reimplements cash/UPI inline and skips the verified-month sheet override | [account_handler.py:2253](../../../src/whatsapp/handlers/account_handler.py#L2253) vs [reporting.py:261](../../../src/services/reporting.py#L261) | Bot yearly vs monthly report disagree on Feb/Mar/Apr cash/UPI |
| C2 | 🟡 LOW | Finance **Cash tab** "collected" = cash-rent-only (excludes maintenance/deposit cash) | [finance.py:125](../../../src/api/v2/finance.py#L125) | Cash-drawer reconciliation can undercount actual cash in hand |
| K1 | 🟡 LOW | `checkouts_today` tile missing `is_staff_room`/`room!=000` filter that every other tile has | [kpi.py:191](../../../src/api/v2/kpi.py#L191) | Staff/placeholder checkouts leak into the count |
| B1 | 🟡 LOW | `TOTAL_BEDS` stale in reporting scripts (291/293/297 vs live 298) | [02_LOGIC_DIVERGENCE.md](02_LOGIC_DIVERGENCE.md#total_beds) | Any report from those scripts has wrong occupancy (live PWA is fine — derives dynamically) |

### What's actually healthy (don't touch)
- **Collection** has a clean canonical service `collection_summary` — used by the PWA collection
  pages *and* the bot's monthly report. [reporting.py](../../../src/services/reporting.py)
- **Occupancy** has a clean canonical service `occupancy.py` — used by kpi.py and (for occupied/pct)
  analytics.py. Only `unit_economics` and one inline `total_beds` bypass it.
- **Checkout refund formula** itself (`max(deposit − maintenance − dues − deductions, 0)`, forfeit if
  no notice) is consistent across PWA, backend, and bot. Only its *dues input* varies.
- The week-old `2026-06-08-pwa-comprehensive` audit's two CRITICALs (`deposit_eligible` always True;
  missing `recalc_checkin_month_rs` on PATCH) appear **already fixed** per the pending-tasks log.

---

## Phase 2 — the fix plan (no code changed yet)

The fix is the same shape that already worked for `first_month_rent_due()` and `occupancy.py`:
**one function per concept, everyone calls it.**

1. **`src/services/dues.py` → `compute_tenant_dues(tenancy, period, session) -> {rent_dues, deposit_due, credit}`**
   - Port the most-complete logic (`get_tenant_dues`: first-month split, prorated+adjustment,
     overflow→deposit, day-wise, booking subtraction).
   - Add a `scope="current_month" | "all_outstanding"` flag so checkout (all arrears) and the
     dashboard (current month) share one function.
   - Rewire all 8 call-sites: `get_tenant_dues`, `list_tenants`, kpi overdue tile, kpi dues panel,
     kpi recent-checkins, `collection_summary.pending`, `reminders/overdue`, `_calc_outstanding_dues`.
   - Then verify+fold the 3 bot helpers (`build_dues_snapshot`, `_my_balance`, `_prev_outstanding`).
   - Golden tests: first-month + waiver, deposit-only payer, multi-month arrears, day-wise, no_show.
2. **Occupancy:** make `unit_economics` and analytics' inline `total_beds` call `occupancy.py`
   (`get_total_revenue_beds` / `get_occupied_beds`). Decide one rule: does Unit-Economics count no_show?
3. **P&L:** make live `GET /finance/pnl` and `unit_economics` share one `true_revenue` definition;
   decide whether the Finance P&L tab should show live or verified (pnl_builder) for frozen months.
4. **Collection:** route the bot Yearly Report through `collection_summary` per month (kills C1).
   Decide if Cash-tab "collected" should include maintenance/deposit cash (C2).
5. **Tile fixes:** D2 (align no_show filter tile↔panel), D3 (add adjustment), K1 (add staff/000 filter).
6. **Scripts:** bump stale `TOTAL_BEDS` to dynamic or 298 (B1).

See [01_PWA_ENDPOINT_MAP.md](01_PWA_ENDPOINT_MAP.md) for the full page→endpoint map and
[02_LOGIC_DIVERGENCE.md](02_LOGIC_DIVERGENCE.md) for exact formulas per implementation.
