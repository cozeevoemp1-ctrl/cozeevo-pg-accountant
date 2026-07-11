# Changelog

## Session R — 2026-07-09→11 — June'26 P&L reclassification + investor buyout + day-stay deposit fix

### Summary
- 🔴 **June'26 P&L was badly misclassified — 23 bank rows reclassified (committed to DB, revert log saved).** Root causes in `pnl_classify.py`: (1) the `Bank Charges → "Bank Transfer / IMPS / NEFT"` catch-all swallows the **full principal** of any unmatched NEFT/RTGS/IMPS (not just a fee); (2) the `vakkal`/`sravani` Property-Rent keyword matches investor **Jitendranath Guptha Vakkalagadda**. Fixes to June DATA (rules still need patching — see pending):
  - Property Rent ₹13.5L → **₹6.0L** (Raghu ₹3L + Suma ₹3L only). Bank Charges ₹9.2L → **₹0**. Food ₹3.68L → **₹3.83L** (chicken vendor `9739392035` ₹15,330 moved in from Other). Other ₹1.47L → ₹0.33L.
  - Investor money OUT of OPEX → Non-Operating: Ashokan ₹5L + Jitendra ₹5L + Sri Lakshmi Chandrasekhar ₹5L. Fencing (M M Industries ₹1.7L + UPI ₹80K = ₹2.5L) → Non-Operating (capital, Kiran: not opex).
  - Tenant cross-check on "Other Expenses" (per [[rules_audit_logs]] SOP-E): `629939585`=**Naitik Raj** (₹8K) + `manideep163031`=**Manideep** t#566 (₹9.5K) → Tenant Deposit Refund. Unmatched: ₹11,352 "ylg", ₹10,500 "dranbukmb" (left in Other, flagged).
  - Set `pnl_monthly_adjustments` June: rent_paid_cash=₹15,32,000, cash_holding=₹2,35,059. Regenerated `data/reports/PnL_Cozeevo_June2026.xlsx`. **June NET OPERATING PROFIT ₹6,22,309** (True Rev ₹36.23L − OPEX ₹30.01L).
- 💰 **Investor buyout — Ashokan & Jitendra fully exited (18 Jun 2026); Prabhakaran absorbed their remaining stake.** Settlement ₹75L total = ₹10L UPI (₹5L each, in bank) + ₹30L PG cash + ₹35L Prabhakaran personal. **Invested capital recalculated ₹2.59Cr → ₹2.31Cr** (₹63.17L exited out, ₹35L Prabhakaran in). Ledger records NOT yet written — pending Kiran's go (see pending).
- 🐛 **Day-stay tenants were wrongly forfeiting deposit under the monthly notice rule.** Fixed 4 surfaces: `checkout.py:135` (API validation), `web/app/checkout/new/page.tsx:122` (modal), `owner_handler.py:365` + `:4413` (bot). Day-stays now excluded from notice-forfeiture entirely — deposit refundable (minus dues/deductions). Monthly unchanged. Both .py compile. **Needs deploy.**
- 🔧 **Data fix: Mukund Jalan (tenancy 1160, room 209) sharing_type double→premium.** Was clobbered on Lokesh's 413→209 room move (07-05 15:40) — the non-premium re-derive fired because he was stored as `single` (not premium) at move time, so the Session-P premium-preservation guard didn't catch him. Data corrected; premium guard gap noted in pending.

## Session Q — 2026-07-05 — ROOT CAUSE of recurring auto-checkin found + killed (main.py startup hook)

### Summary
- 🔴 **Root cause of the long-recurring "auto-checkin without a form" bug — found and removed.** A startup hook in [main.py](../main.py) (~line 98) ran, on **every app start**, one bulk statement: `UPDATE tenancies SET status=active WHERE status=no_show AND checkin_date<=today` — no onboarding form, no admin approval, no audit log. `bb4bbab` (13 Jun) only removed the date-based flip from `bookings.py`; this hook was never touched. That's why it "recurred after every deploy" — **every deploy restarts the app, re-running the hook.** The prior "deploy-lag / stale VPS commit" diagnosis was wrong. **Fix: hook deleted** (single-UPDATE culprit; Depthi/210 + K.Ramesh/320 flipped in the same txn at `09:00:15.726547` after a ~09:00 restart today).
- 🔁 **Data repair — 5 erroneously auto-activated tenants reverted to `no_show`** (form never filled: `pending_tenant`, no signature): Depthi/210 (t1246), Shreyas Shetty/416 (t1253), K.Ramesh Chandra/320 (t1275), Aryan Sharma/208 (t1247), Swadesh Yadav/221 (t1271). Advances retained, RS rows already `na`, each change `audit_log`ged.
- 🔎 **Full audit of every `status=active` path.** Only `main.py` was automatic. Approve is form-gated (`onboarding_router` requires `pending_review`); `bookings.py` always creates `no_show`. Remaining active-setters are deliberate staff actions: PWA check-in (`checkin.py:291`, blocks if a pending form-session exists), bot add_tenant (`owner_handler.py:6068`, still active-by-date, no form), bot assign-room (`:2639`), bot door check-in (`resolvers/onboarding.py:275`).
- ⚠️ **Needs commit + DEPLOY** — until the main.py fix is live, the next restart on old code re-flips the 5 reverted `no_show`s back to active.
- 🟠 **Open (Kiran's call):** whether to also lock down bot `add_tenant` (`owner_handler.py:6068`) so it never sets active without a form. Group B (10 tenants who DID fill+sign but were auto-activated without formal approval) left active — cleanup = run proper approve to generate their agreement PDFs.

## Session P — 2026-07-05 — Premium clobber-on-room-change fix + rollover moved to 1st + all reminders killed

### Summary
- 🐛 **Premium (whole-room) tenants silently downgraded to "double" on every room change.** Root cause: PWA Edit-Tenant `PATCH /tenancies/{id}` ran `tenancy.sharing_type = SharingType(new_room.room_type.value)` on room reassignment ([tenants.py](../src/api/v2/tenants.py)). Since no room is ever `room_type=premium`, this could only produce single/double/triple — wiping premium, with **no audit entry**. That's why it "kept repeating": every manual premium fix was re-clobbered by the next room move. The shared `execute_room_transfer()` (bot + transfer-room endpoint) was already clean.
  - **Fix:** extracted `resolve_sharing_on_room_change(current_sharing, new_room_type)` into `services/room_transfer.py` (single source of truth) — preserves premium, only re-derives for non-premium (e.g. triple→double), and audits the change. `tenants.py` now uses it. 7 regression tests in `tests/test_sharing_on_room_change.py` (all pass).
  - **Data repair:** restored `premium` on 3 clobbered tenants (audited): Nitya Dangarh/503, Chandra Sagar/604, Tanya Rishikesh/311 (all single-occupant whole-room ₹26–28k). Final scan: 0 victims remaining.
- 🗓️ **Monthly rent generation moved from the 2nd-last day (23:00) to the 1st of the month (00:00 IST).** `_monthly_tab_rollover` now targets the current month (the one that just started) with a 12h misfire catch-up. A tenant properly exited on the prior month's last day is now already `exited` before generation runs → no phantom next-month rent. (Krish Kumar/512 got a full July ₹25k on 29 Jun because it pre-generated while he was still active with a 30 Jun flagged checkout; the skip rule was left as-is per Kiran.)
- 🔕 **All automated outbound messaging switched off.** Removed/disabled: prep reminders (today/tomorrow), checkout-deposit alerts, nightly sheet-drift audit — job registrations removed AND added to the startup DB-jobstore purge list. Stripped admin WhatsApp notifications from rollover (success/failure), daily reconciliation, and weekly backup (now log-only). Manual PWA reminder endpoints (`POST /reminders/send`, `/reminders/trigger-prep`) hard-disabled (410). Only 3 scheduler jobs remain — reconciliation, backup, rollover — none send messages.
- ⚠️ **Needs VPS restart** to take effect (and to purge the persisted reminder jobs from the DB job store).

## Session O — 2026-07-02 — Dynamic SOP-format P&L (any future month) + Occupied day-wise filter

### Summary
- 🚀 **"Generate P&L" is now dynamic for every future month** — no longer hardcoded to Oct'25→May'26. Verified months stay frozen/hardcoded (byte-identical output — regression-checked: NET OP ₹14.97L, ADJ ₹11.17L unchanged); every newer month present in `bank_transactions` is computed **live from the DB** (classifier income THOR/HULK, OPEX by category, deposit refunds, security deposits, bank closing = last txn running balance) and **appended as a new column in the same SOP layout**. Upload dedup (`unique_hash`) already skips re-uploaded past lines, so re-uploading overlapping statements is safe.
  - `pnl_builder.py` parameterized: `_write_pnl_tab` + `build_pnl_workbook(dynamic_data=None)` + `build_pnl_bytes(dynamic_data=None)`. No-arg call = canonical verified report unchanged. DB→SOP key maps (`_DB_CAT_TO_OPEX_KEY`, income/excluded/deposit keys) co-located with the dicts; F&F+Capital Investment merge to "Furniture & Supplies"; unmapped categories fold to "Other Expenses".
  - `finance.py`: `_compute_dynamic_pnl_months()` builds one SOP record per non-verified month from the DB; `GET /finance/pnl/excel` now serves verified + dynamic; new `GET/POST /finance/pnl/adjustments` for the manual cash figures. Frozen verified months reject writes (400).
- 📝 **Manual cash form (Finance page)** — the 3 figures never in a bank CSV: **cash holding** (balance-sheet), **rent paid in cash** (OPEX), **cash expense** (OPEX). New `pnl_monthly_adjustments` table (unique on month) + `PnlAdjustmentsCard` component + `getPnlAdjustments`/`savePnlAdjustments` API. Verified months shown as locked.
- ✅ Verified end-to-end against live DB (fake June injected + rolled back → Jun'26 column renders correctly): builder unchanged, dynamic append, `_compute_dynamic_pnl_months`, HTTP handlers (download xlsx 20,901 B, adjustments round-trip, frozen 400, admin 403), app routes registered, PWA production build.
- ✅ **Occupied beds panel** now has the All/Regular/Day-wise stay filter (was only on check-ins/check-outs) — `kpi-grid.tsx`.
- ⚠️ Today only Oct'25–May'26 exist in DB (all frozen) → Generate gives verified-only until a June+ bank statement is uploaded, then the column appears automatically.
- Migration `run_pnl_adjustments_2026_07_02` (append-only) — run on DB.

## Session N — 2026-06-28 — Duplicate-booking prevention (DB constraint) + stay history + day-wise display

### Summary
- 🐛 **Manual bookings created duplicate tenancies** (same person/room/dates shown 2–3×). Built a 3-layer permanent fix:
  1. **DB exclusion constraint `no_overlap_active_tenancy`** (EXCLUDE USING gist + btree_gist) — physically blocks two active/no_show tenancies for the same tenant+room with overlapping dates, on ANY code path. Scoped to active/no_show so historical exited stays are untouched. Live + added to `migrate_all`.
  2. **App guard** in quick-book (`find_overlapping_tenancy` in room_occupancy) → 409 before insert.
  3. **App-wide handler** in `main.py` catches the constraint violation → 409 popup ("already has a booking in this room for overlapping dates") instead of a 500.
  - Repeat guest on DIFFERENT dates still allowed (new tenancy id, same tenant id).
- ✅ **Cleaned existing duplicates:** Udhayabharathi/115 (1264), Arun/608 (1259), Raja/618 (1167), Rama/G09 (1080) cancelled (0-payment side). Ajit/510 (kept 1158, re-linked ₹750 waiver, cancelled 1159), Jagan/G03 (kept 1252, voided duplicate ₹3,900 rent, cancelled 1263).
- ✅ **Tenant model = repeat-guest correct:** one Tenant id (the person) → many Tenancy ids (each stay). Confirmed/documented.
- ✅ **Tenant-search dropdown now shows each stay's dates + status** ("Room 115 · 10 Jun → 12 Jun · exited") so repeat stays are distinct, not identical rows. Search endpoint returns checkin/checkout/stay_type.
- 🐛 **Day-wise stays showed "/mo"** → fixed to "/day" on checkouts, bookings list, tenant-search. Backfilled 16 historical day-stay tenancies that had `agreed_rent=0` (8 from booking sessions, 8 from prepaid÷nights); Ajit/1158 set to ₹750/day (Kiran-confirmed). 3 ancient March/April records left at 0 (no rate data).
- Commits: `f154f4d` (dedup constraint+guard), `4361bd0` (dropdown dates), `39ee820` (popup handler + /day labels).

## Session M — 2026-06-28 — Day-stay rate lost on quick-book + capacity check dead since 3a6c5bb + VPS deploy-lag

### Summary
- 🐛 **Day-stay quick-book lost the per-night rate** — Lokesh booked Room 608 at ₹800/night, edit page showed ₹0. Root cause: when an advance is paid, quick-book creates the tenancy immediately, but `bookings.py:241` hardcoded `agreed_rent=0` for day-stays — the rate was saved only on the OnboardingSession (`daily_rate`), never on the Tenancy. Every reader (tenant detail, checkin, preview) reads the per-day rate from `Tenancy.agreed_rent` (canonical convention — see `onboarding_router.py:1662`; `Tenancy` has no `daily_rate` column). **Fix (`0bae69f`):** quick-book writes `daily_rate` into `agreed_rent` for day-stays. Repaired live records: Tenancy 1267 (Lokesh) 0→₹800; Tenancy 1226 (Sujal Jaiswal) 0→₹1,450 (inferred 14,500÷10 nights — confirm). Both audit-logged.
- 🐛 **Quick-book capacity check has been DEAD CODE since `3a6c5bb`** — that commit removed the `if room.room_number != "000":` guard but left its body indented one level deeper, so the entire bed-limit check silently nested under `if room.room_number == "000": raise` → unreachable for every room. **Bed limits were never enforced; any room could be overbooked past max_occupancy.** `ast.parse` passed (valid syntax, wrong logic) so it went unnoticed. **Fix (`81846de`):** dedented the block to run for every real room.
- 🐛 **VPS running stale pre-`bb4bbab` code (deploy-lag).** Lokesh's booking (check-in today) auto-jumped to `active`/"currently staying", skipping Bookings approval — the date-based auto-checkin behavior `bb4bbab` removed on **13 Jun**, still live on the VPS 15 days later. The deploy webhook is silently failing. Pushed redeploy trigger (`8b096d4`); **Kiran must verify VPS is at `81846de` via Hostinger console** — if older, every booking keeps auto-checking-in and new day-stays keep losing their rate.
- ✅ **Cleaned 7 stale onboarding sessions** (active tenant + pending session, all from the old auto-checkin path): Lokesh, Rajramani/G15, Nishant/116, Rajveer/108, Abhishek/G03, Sheenad/116, Santosh/507 → set `approved`. Removes orphaned "pending bookings" that double-count in occupancy/KPIs.
- ✅ **Room 608 confirmed legit double** (max_occ 2): Vaibhav (monthly) + Lokesh (day-stay) = 2/2 full, not a double-book.

## Session L — 2026-06-28 — Vacant-beds badge missing for expired-link bookings

### Summary
- 🐛 **Room with a real future booking showed as plainly free** in the home "Vacant beds" widget — no "Until \<date\>" badge — so the bed looked open and could be double-booked. Repro: Room 416 had a booking (Shreyas Shetty, check-in 1 Jul 2026) but showed only "1 bed free · Male". Root cause: the vacant-tile upcoming-checkin query (`src/api/v2/kpi.py` ~L526) gated onboarding sessions on `expires_at > now`. Shreyas's session is stored `status='pending_tenant'` with `expires_at=25 Jun` (link expired) — the "Link expired" UI label is a *lazily-computed display status*, the DB status is still `pending_tenant`. The expired-link session failed the `or_(...)` expires_at gate and was dropped, so no badge.
- ✅ **Fix (`22e4395`):** dropped the `expires_at` gate and added `"expired"` to the status set, so any non-cancelled future booking surfaces as an upcoming check-in. An expired link only means the tenant didn't finish their self-service form — the **room hold is NOT released**. Verified against live Supabase DB: new query returns `(416, 2026-07-01)` → "Until 30 Jun". Cancelled bookings still excluded (Cancel on Bookings page clears the badge); a held bed drops its badge once check-in date passes.
- General fix (query logic, not a 416 data patch) — applies to every room with an expired-link future booking.

## Session K — 2026-06-27 — Premium phantom-bed root cause + occupancy point-in-time + Generate P&L

### Summary
- 🐛 **Premium/whole-room tenants showed a phantom free bed** (Chandra/503, Abhishek/G03, Tanya/311, Soham/105). Root cause: the **`/bookings/quick-book` endpoint dropped `sharing_type` for MONTHLY bookings** — it only persisted it on the daily path, so the OnboardingSession AND no_show Tenancy were created NULL even when "Premium" was picked on the form. (The forms — kpi-grid "Pre-book Room" modal + pre-register — were always correct.) Fix (`5c49401`): quick-book resolves sharing_type for both paths and defaults to the room's master type when unspecified; onboarding-approve + bot add_tenant also default from room. **sharing_type is never NULL now.** Backfilled all 17 existing NULLs (sole whole-room → premium, rest → room type); set Chandra/G03/Soham → premium. 0 NULLs remain.
- 🐛 **Occupancy chart showed identical numbers for May & June (both 291/97.7%)** — `get_occupied_beds()` filters only `status='active'` with no date bound, so it returns *today's* count for any month. Added `get_occupied_beds_asof()` (point-in-time: present on date, incl. since-exited, capped per room); analytics live months now use it. May 287/96.3%, June 290/97.3%. (`c95810c`)
- ✅ **Generate P&L button** on Finance page → `/finance/pnl/excel` (same `pnl_builder`, byte-identical to offline export). Error handling surfaces the real status (`d65afc6`).
- ✅ **REPORTING.md** updated: P&L gross-includes-everything + deposit-flow-summed; occupancy point-in-time rule (`c1c51fd`).
- 📊 May unit economics confirmed: avg 282 occupied beds (96.3% month-end); rent ₹7,572/bed + non-rent ₹3,056/bed = ₹10,627/occupied bed.

### Open
- Tanya/311 (₹26K, tagged double + 2 no-shows) — premium mistag? Needs Kiran's call.
- Live P&L generator + adjustments table (new months self-serve). May 31 cash-in-hand → roll balance sheet.

## Session J — 2026-06-27 — May P&L build, HULK parser fix, reclassification, occupancy point-in-time

### Summary
- 🐛 **HULK bank parser booked all collections as expense.** HULK's CSV header starts with `Transaction Date` (same as THOR) but has only a **Deposits** column. The position-based parser read it as THOR layout → Deposits became Withdrawals → ₹14.18L of May collections misfiled as expense (May Rent Income showed ₹12.99L vs real ₹25.13L). Fixed `read_yes_bank_csv` to map columns by **header name**; regression tests added. Re-imported HULK May (reconciles exactly to statement: +₹12,11,100).
- ✅ **Full P&L built Oct'25 → May'26** in `pnl_builder.py` (canonical). May figures Kiran-confirmed: cash rent paid ₹15,32,000, staff ₹76,258 (bank only, no accrual), internet ₹0 (prepaid bulk), water ₹62,900, cash income ₹20,99,079 (app ₹20.36L + Bala uncle ₹63K). True Rent Revenue ₹40,04,315, **Net Operating Profit ₹10,11,846**.
- ✅ **P&L structure changes (Kiran):** Gross Inflows = everything (rent + deposit + booking); deposit subtracted below ("everything in, subtract what we owe"). "Less: Security Deposits" is a monthly flow — **TOTAL now SUMS** (was showing only last month — bug). Removed opening/closing bank-balance rows from the P&L tab. THOR+HULK combined per category (no HULK lump).
- ✅ **Reclassification:** ₹91,600 of deposit refunds were hiding in "Other Expenses" (paid to tenants' personal UPI). Cross-referenced payees vs tenants table → reclassified to Deposit Refunds (now ₹2,75,800, matches expectation). BESCOM→Electricity, diesel vendor→Fuel, fans→Furniture, stabilizer→Maintenance. Other Expenses ₹1,22,551 → ₹34,687. Classifier rules added to `pnl_classify.py`; DB transactions reclassified.
- ✅ **App: "Generate P&L" button** → `/finance/pnl/excel` (same `pnl_builder` = byte-identical to offline export). **Upload now auto-detects tenant refunds** (`_detect_tenant_refunds`: payee phone matches a tenant → Deposit Refund). UploadCard wired back into Finance page.
- ✅ **Occupancy point-in-time fix:** `get_occupied_beds()` filters only `status='active'` with no date bound → every live month showed today's count (May & June both 291/97.7%). Added `get_occupied_beds_asof()` (counts who was present on the date, incl. since-exited, capped per room). Now May 287/96.3%, June 290/97.3%.
- ✅ **Chandra Sagar (Room 503)** premium tenant mistagged `double` → showed phantom free bed. Set `sharing_type='premium'`; vacant count 8→7. Root cause: no sharing-type field in booking/edit forms.
- 📊 **May unit economics:** rent ₹7,572/occupied bed, non-rent OPEX ₹3,056/bed, total ₹10,627/bed (avg 282 occupied beds, 96.3% at month-end).
- Commits: `5a5be3a` (upload card), `78d7369` (parser), `0d05855` (May column), `c45e34f` (structure), `c3bb3a1` (reclassify), `d124524` (generate button + refund detect), `c95810c` (occupancy). SOP updated with all P&L rules.

### Open (optional next builds)
- Sharing-type selector in booking/edit forms (root-cause fix for premium phantom beds).
- Live P&L generator + `pnl_monthly_adjustments` table so new months self-serve (only 3 manual cash figures needed).
- Roll P&L balance-sheet section to May 31 (needs Kiran's May 31 cash-in-hand count).
- Identify remaining ₹23K "Other Expenses" payees (vinod ₹14.4K, acme ₹5K, charasmatic ₹3.75K).

## Session I — 2026-06-27 — Late-notice deposit forfeiture (policy regression fix)

### Summary
- 🐛 **Notices page showed "Refundable" for a notice given today (Adarsh, Room G01, notice 26 Jun — late).** Root cause: `is_deposit_eligible()` in `services/property_logic.py` had been regressed to `return True` ("any notice → refundable; only zero-notice forfeits"), diverging from both the original 2026-04-28 spec AND the existing `test_notice_comprehensive.py` tests (which encode day≤5 = eligible, day>5 = forfeited — they were silently failing). Docs also contradicted each other (REPORTING.md said late=refunded; spec said late=forfeited).
- ✅ **Kiran's decision: late notice (after 5th) = deposit FORFEITED** (revert to original spec). On-time notice (≤5th) → refundable; late notice OR no notice → forfeited.
- ✅ **Fixed the single source of truth** `is_deposit_eligible(notice_date)` → `notice_date is not None and notice_date.day <= NOTICE_BY_DAY`; now handles `None`. Updated `NOTICE_BY_DAY` docstring.
- ✅ **All consumers wired to the central rule**: `notices.py` (deposit_eligible), `checkout.py` (refund-must-be-0 validation now covers late notice, with reason), `kpi.py` (notices detail no longer hardcodes True). PWA: `checkout/new` (forfeiture derivation + late banner flipped to orange "Deposit Forfeited"), `notices` legend, `tenants/[id]/edit` badge + helper text. Bot: `owner_handler` (5 sites: pre-checkout summary, disambiguation summary, settlement net calc + line, notice-given note, exits list), `tenant_handler` (late-notice reply), agreement PDF `HOUSE_RULES`.
- ✅ **Docs merged/aligned** — REPORTING.md §6.5 + §7.1 (now points to `property_logic` as canonical, supersedes spec), BUSINESS_LOGIC.md §6.3, rental agreement text. Added `None`→forfeited test. 17/17 deposit tests pass (4 unrelated `test_future_month_extracted` failures are pre-existing).
- ⚠️ **Flag**: the rental-agreement PDF text was changed to "deposit forfeited" for late notice. Tenants who signed the *old* agreement ("still refundable") may be legally entitled to a refund — apply the new rule only to agreements signed after this change.
- 📝 **Secondary (not fixed)**: Adarsh's stored `expected_checkout` (29 Jun) violates the late-notice rule (should be 31 Jul end-of-next-month). The PATCH endpoint lets a manual `expected_checkout` override the auto-calc. Moot now that his deposit is forfeited, but the override path can still drop the notice period silently.

## Session H — 2026-06-17 — Vacant-bed KPI vs room-list off-by-one

### Summary
- ✅ **"Vacant beds 10" tile ≠ "11 beds free" room list** (same home screen): the two numbers used different definitions of "occupied". KPI tile uses `get_occupied_beds()` = active **+ no-show whose checkin_date ≤ today** (held beds); the vacant room-search panel counted only **active** tenants, so a no-show booked to arrive **today** (Room 116, Rajveer Khanna) was held by the tile but advertised as a free bed in the list → 11 vs 10. Aligned the vacant-detail occupancy subquery (`kpi.py` L438-462) with `get_occupied_beds`: no-shows with `checkin_date ≤ today` now count as occupying the bed. Future no-shows (checkin > today) stay free with their "Until X" tag. Verified against live DB: both read 10. Commit `52c90ca`.

### Notes (environment, not project code)
- Installed **UI/UX Pro Max** skill bundle (7 skills incl. flagship `ui-ux-pro-max`) globally to `~/.claude/skills/` — universal, auto-invoked for any UI design/build/review task. Scanned all scripts before install (clean). 21st.dev Magic MCP was set up then removed at Kiran's request (no project footprint).

## Session G — 2026-06-15 — Day-stay dues model: advance/deposit + waivers + 307 forensics

### Summary
- ✅ **Day-stay advance double-count** (room 208 showed ₹800, real ₹5,800): the booking advance is already a `booking` Payment row, but the daily dues formula also added `tenancy.booking_amount` → counted twice. Removed the field add. Commits `99fe814`, `befc0a3`.
- ✅ **Single source of truth**: collapsed the 4 copied day-stay dues formulas into `src/services/daily_dues.py` (`daily_dues()`, `booking_credit()`). Commit `a5ed503`.
- ✅ **Deposit due ignored the advance** (424 showed ₹5,000, 614 ₹2,000; real ₹0): monthly deposit-due credited the stale `booking_amount` field (0 for onboarding-flow tenants) instead of the `booking` Payment rows. Fixed via shared `booking_credit()` across kpi.py (×2), tenants.py, tenant_handler.py. Commit `c96b8a7`.
- ✅ **Day-stay advance/deposit now held separately** (not netted against stay): per Kiran, advance/deposit go toward the security deposit, excluded from stay dues. 208 → ₹10,800 + ₹5,000 held. Added editable Security Deposit field to Edit Tenant for day stays. Commits `cb6bd46`, `e436040`.
- ✅ **KPI tile ≠ list (₹1,05,416 vs ₹84,250)**: "Dues pending" tile counted `no_show` (G03 Abhishek Jain, ₹21,166 pre-booked) while the dues list is active-only. Tile now active-only to match. Commit `b979808`.
- ✅ **Waived day-stay dues**: 115 Udhayabharathi ₹1,800 + 510 Ajit ₹750 (no payment records — advance only in legacy field) via non-revenue `other` entries (audit-logged, void-able). 618 SHASHANK already ₹0 (₹1,800 collected since).
- 🔎 **Room 307 forensics** (tenancy 1218): (1) name shows "Lokesh" not "kiran" — booking matches tenant by **phone** (7680814628 = Lokesh's own number, reused in test bookings) and reuses the existing "Lokesh" record, **ignoring the typed name**. (2) Auto-"checked in" (active, no audit, session never approved) — behaves like the **pre-`bb4bbab` date-based auto-checkin** code; the 13-Jun fix that requires explicit approval wasn't live on the server when Lokesh booked (deploy lag).

### Pending (open decisions)
- **Day-stay deposit-overflow model NOT implemented**: the unified rule (advance fills `security_deposit` first, overflow → stay; mirrors monthly) was designed but Kiran pivoted to manual waivers. Revisit if per-tenant deposit control is wanted.
- **Room 307 / tenancy 1218 cleanup**: erroneous active day-stay under "Lokesh"/his own number — awaiting decision (cancel / revert to no_show / fix tenant).
- **Booking name-vs-phone bug**: when typed name ≠ matched tenant's name, booking should flag or create a new tenant — not fixed. Also: block staff booking under their own number.

## Session F — 2026-06-15 — Connectivity audit + premium/booking/checkout dedup

### Summary
- ✅ **Connectivity audit** delivered: `docs/audits/2026-06-15-connectivity/` (README + PWA→endpoint map + logic-divergence). Headline: "what does this tenant owe?" is computed by **8 independent implementations**; occupancy/collection/P&L have canonical services that some callers bypass.
- ✅ **Premium-shows-free-bed (data)**: rooms 208, 607, 503, 507, 511 had whole-room tenants with `sharing_type` NULL → counted as 1 bed. Set `sharing_type=premium` (audited). Swept whole property; the 6 remaining single-in-double rooms are genuine free beds (normal rent) — left alone.
- ✅ **Checked-in stuck in Bookings**: 5 sessions (208,309,503,607,617) were `pending` while their tenancy was active → marked `approved`. Code fix: `/admin/pending` now excludes sessions whose tenancy is active/cancelled/exited.
- ✅ **checkouts_today counted dead tenancies**: tile (kpi.py L191) + detail (L381) filtered `checkout_date==today` with no status filter → cancelled dup (Muthu G15) showed twice. Both fixed in one edit to require `status IN (active, exited)`.
- ✅ **Dues panel ≠ collect modal (D3)**: kpi.py overdue tile + dues detail dropped first-month `adjustment` (waiver); Nikhil 224 showed ₹5,700 on panel vs ₹2,500 in modal (−₹3,200 waiver). Both kpi copies now apply `max(0, prorated+adjustment)` to match `get_tenant_dues`. Commit `b87cee1`.
- ✅ **Booking/payment duplicates (current period)**: Santosh 507 old ₹1000 voided; SHASHANK 618 ₹3800 re-linked to live 1217 + dup cancelled; Muthu G15 consolidated onto 1205; room-000 trio (Niranjan/Nikita/S Narendh) ₹2000 advances re-linked to live tenancies; Adithya ₹500 maintenance dup voided.
- ✅ **Split-payment false alarm caught**: 7 of 10 flagged "duplicate payments" were legit half-cash/half-UPI splits by premium tenants (~₹85k) — NOT voided. Rule saved.
- ⛔ **Frozen left untouched** (per Kiran): 871 G.D.Abhishek April ₹11,750 dup + 11 Dec-era cancelled tenancies holding ~₹2.4L deposits/rent — flagged for review, not modified.
- ✅ Deployed: commit `eca335d` (kpi.py + onboarding_router.py); 52 tests pass.

### Root causes
- **No `sharing_type` field in PWA edit/booking forms** → premiums can't be set/corrected in-app; they default unmarked and rooms show phantom free beds. (Phase-2 fix.)
- **Disconnected duplicate queries** → updating data in one place (cancel/premium) doesn't reflect in tiles/panels that re-query independently without status filters. (Audit thesis; Phase-2 = centralize.)

### Pending (Phase 2 — not started)
- Centralize `compute_tenant_dues()`; wire all 8 call-sites.
- Add `sharing_type` to tenant edit + booking forms (root cause of premium mismatch).
- Re-book: reuse existing booking for same phone+room instead of spawning a 2nd tenancy+payment.

## Session E — 2026-06-14 — Payment NULL-column bugs: history/dues/sheet not connected

### Summary
- ✅ Root-caused why payments existed in DB but vanished from the app: raw-SQL insert paths leave columns NULL because they had only Python-side ORM defaults (no `server_default`)
- ✅ `is_void = NULL` (8 rows, ₹85,750) excluded by every `WHERE is_void = false` filter → invisible in history/dues/P&L/sheet
- ✅ `created_at = NULL` (21 rows) crashed `sync_sheet_from_db` (`can't compare datetime to date`) → edits never tallied to Sheet (April/May)
- ✅ Hardened both columns (backfill + `server_default` + migration); made list endpoint + sync NULL-safe
- ✅ Sachin Kumar Yadav (Rm 409) March deposit 21397 reduced ₹5,250→₹4,750 → deposit_due now ₹500
- ✅ Resynced April/May/June sheet tabs; ruled out "failed to fetch" (was the deploy restart window — all endpoints healthy, CORS correct)
- ✅ 52 tests pass; commits 72e3345, a7ff027 (auto-deployed)
- ⏳ Live Playwright verification still pending (blocked on PWA login password)

### Bugs Fixed
**Bug 1: Payments with `is_void = NULL` invisible everywhere**
- Root cause: `payments.is_void = Column(Boolean, default=False)` — Python-only default, no `server_default`. Raw inserts → NULL. `is_void = false` filter drops NULL under SQL 3-valued logic.
- Fix: backfill NULL→false; `ALTER ... SET DEFAULT false NOT NULL`; `models.py` updated; migration `run_payments_void_not_null_2026_06_14`; `list_payments` filter → `is_void IS NOT TRUE`; restored dropped `limit` param + all-tenants default view + cross-tenancy expansion (regressed by the 5 "simplify" rewrites de41adf…fe3eaf0).

**Bug 2: `created_at = NULL` crashed the Sheet sync**
- Root cause: same pattern — `created_at` had only `default=datetime.utcnow`. NULL fell back to `payment_date` (a `date`) and was compared against another row's `datetime`.
- Fix: `sync_sheet_from_db` latest-payment key normalized to `(datetime, id)`; backfill 21 NULL→`payment_date`; `created_at SET DEFAULT now()`; migration extended.

### Data Changes
- Payment 21397 (Sachin Rm 409): amount ₹5,250 → ₹4,750, audit-logged (reason: ₹500 deposit pending)
- April/May/June 2026 sheet tabs resynced from DB

## Session D — 2026-06-13 — Bug Fixes: Data Consistency + Day-stay Enhancement + Payment Records

### Summary
- ✅ 6 critical bugs fixed from earlier in session (auto-checkin, pending bookings, day-stay fields, refund logic, cancel endpoint, home page perf)
- ✅ Day-stay daily_rate now fully editable in tenant edit page
- ✅ Advance payments voided for cancelled Room 108 bookings
- ✅ Jitendra Kochale deposit payment recorded (₹10,500, settled with booking advance)
- ✅ All 52 unit tests passing, PWA builds successfully
- ✅ Deployed to VPS

### Bugs Fixed (6 Critical Issues)

**Bug 1: Auto-checkin by Date Removed**
- **Problem:** Bookings with today's check-in date auto-checked-in without admin approval (Room 208 example)
- **Root Cause:** Two endpoints had logic: `if checkin_date <= today() then status=active`
- **Files:** `src/api/v2/bookings.py:227`, `src/api/onboarding_router.py:1766`
- **Fix:** Removed date-based auto-checkin; now requires explicit `instant_checkin=true` flag
- **Verification:** Manual check-in now required; no auto-transitions
- **Commit:** bb4bbab

**Bug 2: Pending Tenant Bookings Hidden**
- **Problem:** Bookings page showed 24 of 32 bookings (missing pre-booked tenants)
- **Root Cause:** Filter on line 86-88 excluded `pending_tenant` status
- **Files:** `web/app/onboarding/bookings/page.tsx`
- **Fix:** Show all three statuses (pending_tenant + pending_review + expired) in UI
- **Verification:** 8 pre-booked bookings now visible
- **Commit:** 835708e

**Bug 3: Day-stay Bookings Show Monthly Fields**
- **Problem:** Room 208 (day-stay) showed "Agreed Rent (₹/mo): 0" instead of "Daily Rate (₹/night): 1200"
- **Root Cause:** editRent initialized from agreed_rent (0) instead of daily_rate
- **Files:** `web/app/onboarding/bookings/page.tsx`, `web/app/tenants/[tenancy_id]/edit/page.tsx`
- **Fix:** Initialize from correct field based on stay_type; hide monthly fields for day-stays in tenant edit
- **Verification:** Correct daily rate displays in edit form
- **Commits:** 6431c15, fa13731

**Bug 4: Checkout Form Refund Calculation Wrong**
- **Problem:** Shows ₹1,000 refund for forfeited deposits (no notice) when should be ₹0
- **Root Cause:** `depositForfeited` logic didn't account for day-stays having no deposits
- **Files:** `web/app/checkout/new/page.tsx`
- **Fix:** Set `depositForfeited=true` for all day-stays (no deposits to refund)
- **Verification:** Checkout shows correct refund amounts
- **Commit:** dd3dd27

**Bug 5: Cancel Booking Endpoint Crashes**
- **Problem:** "Failed to fetch" when clicking Cancel; API crashes with `NameError: name 'text' is not defined`
- **Root Cause:** `src/api/onboarding_router.py:761` used `text()` but never imported it
- **Files:** `src/api/onboarding_router.py:18`
- **Fix:** Added `text` to import: `from sqlalchemy import select, update, text`
- **Prevention:** Created `feedback_import_management.md` (SQLAlchemy import checklist)
- **Commit:** 4a66830

**Bug 6: Home Page 6-Second Load Time**
- **Problem:** Home page took 6+ seconds due to KPI endpoint doing 7+ sequential DB queries
- **Status:** Identified but not fully fixed (architectural issue)
- **Attempted:** Parallelized with `asyncio.gather()` → broke other endpoints (async session limitations)
- **Current:** REVERTED (commit 081547b); marked as deferred
- **Next:** Needs query caching, database indexes, or optimization (not parallelization)

### Features Added

**Day-stay Daily Rate Now Editable in Tenant Edit Page**
- **Before:** Could only edit daily_rate via Bookings page; tenant edit showed warning + hid fields
- **After:** Shows editable "Daily Rate (₹/night)" field; same save flow as monthly rent
- **Implementation:**
  - Added explicit `daily_rate` field to `TenantDues` API response (both day-stay and monthly)
  - Updated `web/lib/api.ts:TenantDues` interface
  - Frontend: conditional rendering based on `stay_type` (daily vs monthly)
  - Backend: daily_rate updates go through `agreed_rent` field (stores per-night rate for day-stays)
  - Changes logged as RentRevision + AuditLog entries
- **Scope:** Day-stays can now be fully edited from either Bookings or Tenants pages
- **Files:** `src/api/v2/tenants.py`, `web/lib/api.ts`, `web/app/tenants/[tenancy_id]/edit/page.tsx`
- **Commits:** 3247945, 9816eef

### Data Cleanup
**Advance Payments Voided**
- **Reason:** Cancelled bookings for Room 108 (Lokesh + Kiran) after manual cancellation
- **Voided:** 2 advance payments totalling ₹4,000
  - Payment 21359 (Lokesh): ₹2,000 booking advance → voided with audit log
  - Payment 21358 (Kiran Kumar): ₹2,000 booking advance → voided with audit log
- **Method:** Used void_payment logic with AuditLog entry (source=admin, note="Cancelled booking advance voided")
- **Verification:** Both payments marked `is_void=true` in database

### Payment Records Added
**Jitendra Kochale - Deposit Payment Recorded**
- **When:** April 2026 (₹10,500 UPI)
- **Record:** Payment ID 21361 (deposit for_type)
- **Settlement:** Booking advance (₹2,000) covers remaining shortfall
  - Deposit owed: ₹12,500
  - Paid: ₹10,500
  - Advance applied: ₹2,000
  - **Due: ₹0 (SETTLED)**

### Features Added
**Day-stay Daily Rate Now Editable in Tenant Edit Page**
- **Problem:** Day-stay bookings could only edit daily_rate via Bookings page; tenant edit page showed warning + hid fields
- **Solution:** 
  - Added explicit `daily_rate` field to `TenantDues` API response
  - Tenant edit page now shows editable Daily Rate field for day-stays
  - Same form logic as monthly rent: changes create RentRevision + AuditLog entries
  - Accepts same validation (must be > 0) and workflows
- **Scope:** Day-stays can now be fully edited from either Bookings or Tenants pages
- **Backwards compat:** Monthly bookings unchanged; daily_rate=0 for monthly (explicit in response)

### Issues Fixed

**1. PWA Build Failure (TypeScript Schema Mismatch)**
- **Problem:** KPI endpoint returned `notices_incoming` field but TypeScript schema didn't define it
- **Impact:** PWA build failed on VPS; pages (Notices, Bookings, Pre-Register) crashed with "client-side exception"
- **Root Cause:** Session C audit fix added field to backend but forgot to update schema
- **Fix:** Added `notices_incoming: number;` to `KpiResponse` interface in `web/lib/api.ts`
- **Commit:** c7b4e21

**2. Occupancy Calculation Divergence (Data Consistency)**
- **Problem:** KPI tile and Finance chart showed different occupancy % for the same date
  - KPI: 276 beds occupied → 92.6%
  - Chart: 279 beds occupied → different %
- **Root Cause:** Two separate endpoint implementations calculating occupied beds differently
  - KPI endpoint: counted active + no_shows (checkin_date <= today)
  - Analytics endpoint: counted active only (no no_shows)
- **Temporary Fix:** Updated analytics.py to match KPI logic (added no_show calculation)
- **Permanent Fix:** Extracted canonical occupancy service (`src/services/occupancy.py`)
  - `get_total_revenue_beds()` — single calculation, both endpoints use it
  - `get_occupied_beds(session, target_date)` — active + no_shows, both endpoints use it
  - `get_occupancy_pct(session, target_date)` — percentage, both endpoints use it
  - Both `kpi.py` and `analytics.py` now call the service instead of duplicating code
  - Removes 154 lines of duplicated calculation code
  - Guarantees no future divergence (one source of truth)
- **Commits:** 5e57c44, 5d3acff, baa2d97

### Verification
- ✅ All 52 unit tests passing
- ✅ KPI tile occupancy matches Finance chart occupancy
- ✅ Notices/Bookings/Pre-Register pages load without errors
- ✅ No divergence possible going forward (canonical service)

### Key Lesson
**Schema Sync:** When backend returns a new field, always update TypeScript schema in the same commit. Use a canonical service for calculations that appear in multiple endpoints.

---

## Session C — 2026-06-08 — Comprehensive Audit + Bug Fixes

(See earlier sessions for full details)

---
