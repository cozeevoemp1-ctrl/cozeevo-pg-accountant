# Payment Flow Rework + Notes Architecture

**Date:** 2026-03-30
**Status:** Approved
**Scope:** Payment flow (both entry points), notes system, carry-over, import reclassification

---

## Problem

The current payment flow (`Raj paid 8000 cash`) shows a bare confirmation (name/amount/mode/month) with no context about what the tenant owes, across which months, or any notes/agreements. The receptionist confirms blind. Previous month dues and notes only surface *after* the payment is already logged — too late to redirect.

Notes are fragmented: `tenancy.notes` holds Excel comments (permanent), Sheet monthly Notes column holds parser artifacts, and `rent_schedule.notes` exists in the DB model but is never populated. There is no carry-over between months.

## Solution

Four connected pieces shipped together:

1. **Notes architecture** — two-tier notes with DB/Sheet sync
2. **Payment flow rework** — dues snapshot before confirmation, smart month allocation
3. **Carry-over logic** — monthly notes auto-copied to next month
4. **Import reclassification** — split Excel comments into permanent vs monthly at import time

---

## 1. Notes Architecture

### Two-tier system

| Field | DB Location | Sheet Location | Purpose | Editable by |
|-------|-------------|----------------|---------|-------------|
| `tenancy.notes` | `tenancies.notes` (existing) | TENANTS tab, Notes column | Permanent agreements — payment preferences, planned checkout, rent revisions, special terms | Admin + Receptionist |
| `rent_schedule.notes` | `rent_schedule.notes` (existing column, currently unused) | Monthly tab, Notes column | Monthly status — "will pay by 15th", "Chandra collected partial" | Admin + Receptionist |

### Sync rules

- Every note write updates **both DB and Sheet** in the same operation.
- Sheet write uses retry (up to 3 attempts) on failure. If all retries fail, DB write is kept, failure is logged, and flagged for manual reconciliation.
- This replaces the current fire-and-forget pattern for notes specifically. Payment logging itself remains fire-and-forget for Sheet.

### Display format

When both note types exist:

```
Raj Kumar (Room 203)

Tenant notes: Always cash. Checkout planned May 2026.

Dues:
  Feb 2026: Rs.6,000 (partial) — "will pay balance by 15th March"
  Mar 2026: Rs.14,000 (unpaid)
  Total outstanding: Rs.20,000
```

- `Tenant notes:` = `tenancy.notes` (permanent). Omitted if empty.
- Per-month inline notes = `rent_schedule.notes` for that month. Omitted if empty.
- No empty labels shown — sections only appear when there's content.

---

## 2. Payment Flow Rework

### Affected entry points

Both entry points get the same dues snapshot + smart allocation:

1. **Quick payment** — `Raj paid 8000 cash`, `Raj 8000 upi`, `Priya paid 8000 gpay`
2. **Step-by-step** — `collect rent`, `record payment`

### Quick payment flow (reworked)

```
Input: "Raj paid 8000 cash"

Step 1: Resolve tenant
  - Existing fuzzy search (name prefix → substring → broad contains)
  - 0 matches → suggest similar names (existing behavior)
  - 2+ matches → numbered disambiguation list (existing behavior)
  - 1 match → proceed to Step 2

Step 2: Fetch dues snapshot (NEW)
  - Query all rent_schedule rows where status IN (pending, partial) for this tenancy
  - For each: calculate effective_due - already_paid = remaining
  - Fetch tenancy.notes (permanent) and rent_schedule.notes (monthly) for each pending month
  - Order by period_month ascending (oldest first)

Step 3: Show snapshot + smart allocation + confirm (NEW)
  Bot response:

  Raj Kumar (Room 203)

  Tenant notes: Always cash. Checkout planned May 2026.

  Dues:
    Feb 2026: Rs.6,000 (partial) — "will pay balance by 15th March"
    Mar 2026: Rs.14,000 (unpaid)
    Total outstanding: Rs.20,000

  Suggested allocation for Rs.8,000 CASH:
    -> Feb 2026: Rs.6,000 (clears balance)
    -> Mar 2026: Rs.2,000 (partial)

  Reply *Yes* to confirm, or specify different allocation:
    e.g. "all to march" or "feb 3000 march 5000"

Step 4: Confirmation
  4a: "Yes" → log payments per the suggested split:
      - Payment 1: Rs.6,000 for Feb, update rent_schedule Feb → paid
      - Payment 2: Rs.2,000 for Mar, update rent_schedule Mar → partial
      - Sync both to Sheet
  4b: Override (e.g. "all to march") → recalculate, show updated confirmation
  4c: "No" → cancelled
```

### Step-by-step flow (reworked)

Same as today but dues snapshot inserted after tenant identification:

```
"collect rent" → "Who paid?" → "Raj" →

  Raj Kumar (Room 203)

  Tenant notes: Always cash. Checkout planned May 2026.

  Dues:
    Feb 2026: Rs.6,000 (partial) — "will pay balance by 15th March"
    Mar 2026: Rs.14,000 (unpaid)
    Total outstanding: Rs.20,000

  Cash amount? (number, or skip)

→ "8000" → "UPI amount?" → "skip" → "Notes?" →

  Suggested allocation for Rs.8,000 CASH:
    -> Feb 2026: Rs.6,000 (clears balance)
    -> Mar 2026: Rs.2,000 (partial)

  Reply *Yes* to confirm, or specify different allocation.
```

### Smart allocation rules

1. **Oldest-first** — fill oldest pending month first, then next, etc.
2. **Exact match shortcut** — if amount exactly matches one specific month's remaining due, suggest that month directly (still confirm).
3. **Single month only** — if only one month has dues, no allocation question — straight to confirm for that month.
4. **Overpayment** — if payment > total outstanding, oldest-first fills all dues, remainder triggers existing overpayment flow (advance for next month / add to deposit / ask tenant).

### Override parsing

Receptionist can override the suggested allocation:

| Override format | Meaning |
|----------------|---------|
| `all to march` | Entire amount to March |
| `feb 3000 march 5000` | Custom split |
| `all to feb` | Entire amount to Feb (even if it exceeds Feb dues — triggers overpayment for that month) |

If override doesn't parse cleanly, bot asks for clarification. Never assume.

### Edge cases

| Scenario | Behavior |
|----------|----------|
| No dues (all paid) | Snapshot shows "All paid up for [month]". Payment still allowed — triggers overpayment flow |
| Single month due | No allocation question — straight to confirm for that month |
| Payment > total outstanding | Oldest-first fills all, remainder → overpayment flow |
| Payment exactly matches one month | Smart suggest that month, still requires confirmation |
| No notes (permanent or monthly) | Notes sections omitted from snapshot |
| Name mismatch / ambiguity | Always ask for clarification — never assume (unchanged from today) |

---

## 3. Carry-over Logic

### Trigger points

Carry-over happens when a new `rent_schedule` row is created:

1. **`migrate_all.py`** — monthly migration generating next month's rent_schedule for all active tenants
2. **Bot auto-generation** — when a payment is logged for a month that doesn't have a rent_schedule row yet

### What carries over

```
Previous month rent_schedule.notes → New month rent_schedule.notes
```

- Copy verbatim. No transformation, no filtering, no "smart" detection.
- If previous month has no rent_schedule or notes is NULL/empty → new month starts with empty notes.
- `tenancy.notes` (permanent) is independent — never touched by carry-over.

### Sheet sync at carry-over

When a new monthly tab is created/populated, the Notes column for each tenant row is populated with the carried-over `rent_schedule.notes`.

### Modifying and clearing notes

| Action | Effect on current month | Effect on previous months |
|--------|------------------------|--------------------------|
| Receptionist types new note | Replaces `rent_schedule.notes` for current month. Syncs to Sheet. | Untouched — frozen history |
| Receptionist says "delete" / "clear" | Sets `rent_schedule.notes` to NULL for current month. Syncs to Sheet. | Untouched — frozen history |
| Receptionist says "skip" | Notes unchanged — carried-over value stays | Untouched |

### Carry-over timeline example

```
Feb: rent_schedule.notes = "will pay by 15th"
     ↓ (carry-over at month creation)
Mar: rent_schedule.notes = "will pay by 15th"   ← auto-copied
     → Receptionist updates: "paid Feb balance, March pending"
     ↓ (carry-over)
Apr: rent_schedule.notes = "paid Feb balance, March pending"  ← auto-copied
     → Receptionist deletes notes
     → rent_schedule.notes = NULL
     ↓ (carry-over)
May: rent_schedule.notes = NULL  ← nothing to carry
```

Feb's notes remain "will pay by 15th" forever — historical record.

---

## 4. Import Reclassification

### Default behavior

All Excel column 15 comments → `tenancy.notes` (permanent). This is the safe default because col 15 comments were written by Kiran as admin-level context at onboarding.

### Ambiguity detection

Keyword-based auto-classification:

**Permanent signals:** `always`, `agreed`, `checkout`, `planned`, `lease`, `contract`, `first.*months`, `from.*month`, `company`, `student`, `parent`

**Monthly signals:** `will pay`, `by \d+`, `next week`, `balance`, `partial`, `collected`, `pending`

**Neither → flagged as `???`** for manual review.

### Import workflow

```bash
# Step 1: Dry run — preview classification
python -m src.database.excel_import --preview-notes

# Output:
# ┌─────┬──────────────┬─────────────────────────────────────┬──────┐
# │ Row │ Tenant       │ Comment                             │ Type │
# ├─────┼──────────────┼─────────────────────────────────────┼──────┤
# │  12 │ Raj Kumar    │ always cash                         │ PERM │
# │  15 │ Priya S      │ checkout May                        │ PERM │
# │  23 │ Arun V       │ will pay by 15th                    │ ???  │
# │  31 │ Deepa R      │ shifted from room 201               │ ???  │
# │  44 │ Kumar M      │ partial - balance next week          │ ???  │
# └─────┴──────────────┴─────────────────────────────────────┴──────┘
#
# 3 ambiguous comments need classification.
# Edit data/notes_classification.json and re-run with --write

# Step 2: Edit classification file
# data/notes_classification.json:
# [
#   {"row": 23, "tenant": "Arun V", "comment": "will pay by 15th", "type": "monthly"},
#   {"row": 31, "tenant": "Deepa R", "comment": "shifted from room 201", "type": "permanent"},
#   {"row": 44, "tenant": "Kumar M", "comment": "partial - balance next week", "type": "monthly"}
# ]

# Step 3: Import with classifications applied
python -m src.database.excel_import --write
```

### Where monthly-classified comments go

Comments classified as `"monthly"` → `rent_schedule.notes` for the **most recent pending/partial month** for that tenant. If no pending month exists, the comment is kept in `tenancy.notes` as permanent (safe fallback).

---

## Files Affected

| File | Changes |
|------|---------|
| `src/whatsapp/handlers/account_handler.py` | `_payment_log()` reworked — dues snapshot, smart allocation, split payment logging |
| `src/whatsapp/handlers/owner_handler.py` | `COLLECT_RENT_STEP` reworked — dues snapshot after tenant ID, allocation at confirm. New `UPDATE_TENANT_NOTES` pending handler. |
| `src/whatsapp/intent_detector.py` | New `UPDATE_TENANT_NOTES` intent patterns |
| `src/whatsapp/gatekeeper.py` | Route `UPDATE_TENANT_NOTES` to owner_handler |
| `src/database/excel_import.py` | `--preview-notes` flag, classification JSON loading, split notes writing |
| `src/database/migrate_all.py` | Carry-over logic — copy previous month's `rent_schedule.notes` to new month |
| `src/integrations/gsheets.py` | Notes sync helpers — write `tenancy.notes` to TENANTS tab, `rent_schedule.notes` to monthly tab, retry logic |
| `src/whatsapp/handlers/_shared.py` | `build_dues_snapshot()` helper — reusable snapshot builder for both payment flows |
| `scripts/clean_and_load.py` | No changes — parser stays as-is, classification happens at import layer |

## 5. Permanent Notes Intent (UPDATE_TENANT_NOTES)

A separate intent for updating `tenancy.notes` (permanent agreements). Not part of the payment flow.

### Trigger messages

- `update agreement for Raj`
- `update tenant notes Raj`
- `change notes for room 203`
- `tenant agreement Priya`

### Flow

```
"update agreement for Raj"

→ Raj Kumar (Room 203)

  Current tenant agreement: Always cash. Checkout planned May 2026.

  Type new agreement notes, or "delete" to clear:

→ "Always UPI from now. Checkout planned June 2026."

  *Updated tenant agreement for Raj Kumar:*
  "Always UPI from now. Checkout planned June 2026."

  Reply *Yes* to save or *No* to cancel.

→ "yes" → saved to DB tenancy.notes + synced to Sheet TENANTS tab
```

Same tenant resolution as payment flow (fuzzy search, disambiguation if multiple matches).

### Intent registration

New intent `UPDATE_TENANT_NOTES` added to `intent_detector.py` owner rules. Routed to `owner_handler.py`. Available to admin + receptionist.

---

## Note Editing Contexts

| Context | Which notes field | How |
|---------|------------------|-----|
| Payment flow "Notes?" step | `rent_schedule.notes` (monthly) | Type text = replace, "delete" = clear, "skip" = keep |
| `UPDATE_TENANT_NOTES` intent | `tenancy.notes` (permanent) | Separate workflow — resolve tenant, show current, replace/delete, confirm |
| Excel import | Both — classified at import time | See Section 4 |
| Carry-over | `rent_schedule.notes` only | Auto-copy, see Section 3 |

## Dependencies

- No new packages required
- No DB schema changes — `tenancy.notes` and `rent_schedule.notes` columns already exist
- No new API endpoints
