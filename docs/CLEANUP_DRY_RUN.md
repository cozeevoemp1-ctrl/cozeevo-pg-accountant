# CLEANUP DRY RUN — Production Data Audit (2026-08-06)

> **Status: DRY RUN — nothing below has been executed.** Read-only audit of the live DB.
> Execution rule: each item needs Kiran's per-item approval. All voids go through `is_void=true` + `audit_log` — never DELETE. FROZEN window (Dec 2025–Mar 2026) is never touched.

## A. Duplicate non-void payments — 12 groups (₹1.2L+ potential double-count)

### A1. Near-certain duplicates (recommend void — 3 rows)
| Keep | Void | Tenancy | Who | Amount | Evidence |
|---|---|---|---|---|---|
| 21866 | **21867** | 684 Ashmit | rent 26 Jul | ₹16,000 | both UPI, 38s apart (bot double-tap) |
| 21449 | **21450** | 1222 Sheenad Bhattad | rent 19 Jun | ₹7,000 | both cash, 2.4min apart |
| 21676 | **21829** | 1246 Depthi | deposit 5 Jul | ₹12,000 | real-time log vs backdated check-in log; tenancy shows ₹24,000 deposit |

```sql
-- AFTER APPROVAL, per row:
UPDATE payments SET is_void=true,
  notes=coalesce(notes,'')||' | voided: duplicate of <kept_id> (dry-run audit 2026-08-06)'
WHERE id IN (21867, 21450, 21829);
-- + one audit_log INSERT per void (project rule)
```

### A2. Sheet-reload cash+UPI mirror pairs — 7 groups (NEED KIRAN CONFIRMATION)
Same amount logged once as cash and once as UPI, all created in batch `2026-05-16 17:07:02` ("Apr/May sheet reload"). Either genuine half-cash-half-UPI splits or the reload wrote one cell into both mode columns.

| Tenancy | Who | Amount | Month | Payment ids |
|---|---|---|---|---|
| 638 | Jeewan Kant Oberoi | ₹14,000 | Apr | 20228 / 20229 |
| 703 | Namit Mehta | ₹6,500 | May | 20395 / 20396 |
| 762 | Adarsh Venugopal | ₹13,000 | May | 20432 / 20433 |
| 764 | Chaitanya Phad | ₹8,000 | Apr | 20436 / 20437 |
| 792 | Tarun | ₹6,500 | Apr | 20598 / 20599 |
| 855 | Sparsh Gupta | ₹6,000 | May | 20650 / 20651 |
| 866 | Arpit Mathur | ₹12,000 | May | 20698 / 20699 |

Check against Kiran's offline Excel (cash vs UPI columns) before touching. April is LOCKED — voids on April rows also need the freeze-trigger escape hatch.

### A3. Reload vs manual-import overlap — 2 groups
- **871 G.D.Abhishek** ₹11,750 Apr rent (20713 reload vs 21018 manual). NOTE: pending tasks list says this tenancy's reload-cash dup is **FROZEN per Kiran 2026-06-15** — leave unless he unfreezes. Extra: deposits total ₹57,250 on one tenancy (20714 ₹11,750 + 20715 ₹22,000 + 21017 ₹23,500) — review.
- **1246 Depthi** — covered in A1.
- 762 Adarsh also has a second ambiguous pair 21240/21241 (cash+UPI 6s apart, 6 Jun).

## B. Overlapping tenancies (cross-room) — 2
1. **Sujal Jaiswal** t617: tenancy 1226 (room 205, exited) still carries a **pending Jul'26 RS ₹1,450** = phantom due. Fix: `UPDATE rent_schedule SET status='na' WHERE tenancy_id=1226 AND period_month='2026-07-01';`
2. **Chinmay Pagey** t821: tenancies 818/835 overlap Apr (both exited) — historical import artifact, low priority.

## C. Room 402 over-capacity (premium conflict) — 1
Anukriti Dubey (t676, `premium`, ₹16,000) + Manu Bansal (t1162, `double`, ₹16,000) both active in a max-2 room. Both at ₹16K suggests Anukriti is no longer whole-room premium. **Ask Kiran**: downgrade t676 to `double` (+ audit + Sheet mirror) or was Manu double-booked?

## D. Cancelled-tenancy leftovers (mostly FROZEN window — flag only)
- 33 non-void payments on cancelled tenancies (₹2.35L, Dec'25–Jan'26) — no action; verify reporting filters exclude cancelled.
- 53 rent_schedule rows on cancelled tenancies (₹7.78L). **5 rows are pending/partial = dues-leak risk.** Structural gap: `rentstatus` enum has **no void value**. Post-April fix candidate: set those pending/partial to `na`.

## E. Stale onboarding sessions — 10 (PWA Bookings noise)
`pending_review` sessions whose tenancy is already **active** (approved via another path, session never flipped): ids **214, 223, 226, 227, 229, 230, 235, 249, 253, 254** (Vedant Merai, Sourabh Lande, Rajanala, Lohitaksh, S Krishna Rakesh, Sushil Pandey, Ankush, G. Bharath, Lenin, Madhu Preetha). Overlaps the Session Q "Group B" list — approving them properly would also generate their agreement PDFs (preferred over raw UPDATE).

## F. Misc hygiene
| Item | Action (after confirm) |
|---|---|
| t1143 Devamsh room 514 — `active` but checkout_date 7 Jun | set `exited` if he left, else clear checkout_date |
| t845 Satish Wagehla room 621 — `exited`, checkout_date NULL (live window) | fill true date from checkout_records/sheet |
| t1301 Harshit room 621 — no_show 32 days old, session 279 pending | cancel session 279 |
| 8 orphan tenants (no tenancy) + 10 SPLIT identity pairs | run `scripts/_merge_duplicate_tenants_415_615.py` pattern per pair; integrity script now exists |
| 56 rent payments with NULL period_month | mostly day-stay (OK by design); check t1282 ₹12,000 (15 Jul) |
| 89 pending refunds | business review, not data fix |

## Execution order (once approved)
1. A1 voids (3 rows) + audit_log entries.
2. B1 phantom RS na.
3. E via proper approve flow (generates PDFs).
4. C after Kiran's answer.
5. A2/A3 only with Kiran's Excel cross-check (April = locked, needs freeze escape).
6. F items individually.
