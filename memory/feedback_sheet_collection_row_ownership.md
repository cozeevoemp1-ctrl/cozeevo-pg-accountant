---
name: Sheet COLLECTION row ownership and dues formula
description: Hard rules about who writes the Google Sheet COLLECTION row and how Total Dues must be computed — established after April dues showed Rs.4L instead of Rs.88k
type: feedback
---

These rules were burned in during a painful 2026-04-28 debugging session. Violating any one of them will silently corrupt Total Dues on the Google Sheet.

**Rule 1: `_refresh_summary_sync` must NEVER write the COLLECTION row.**
It owns ONLY per-row Balance/Status/TotalPaid cells. The old code wrote a full 5-row summary block (r2_occ through r6_notice) with `ws.update()` — this was removed entirely.

**Rule 2: `sync_sheet_from_db.py` is the SOLE owner of the COLLECTION row (rows 2-6).**
No other function may write Total Dues, Total Cash, Total UPI, or Collected to the Sheet.
`trigger_monthly_sheet_sync()` fires this as a background subprocess.

**Rule 3: Total Dues = `collection_summary().pending` — NEVER a per-row clamped sum.**
Per-row sum: `sum(max(0, balance) for row in rows)` overstates dues (overpaying tenants show 0, not negative).
The DB aggregate `max(0, expected - collected)` is correct and matches PWA/bot.
Code: `from src.services.reporting import collection_summary; result.pending`.

**Rule 4: Booking payments must NOT be written to Sheet Cash/UPI.**
`first_month_rent_due = prorated + deposit - booking`. Booking already pre-subtracted from rent_due. Writing booking payment to Cash subtracts it again.
Code: `if body.for_type != "booking": gsheets_update(...)`.

**Rule 5: gsheets write-back must use `payment_date` when `period_month is None`.**
Deposit/booking payments have `period_month=None`. `datetime.strptime(None, "%Y-%m")` raises `TypeError`.
Code: `period = datetime.strptime(body.period_month, "%Y-%m") if body.period_month else date.today()`.

**Rule 6: April first-month balance must subtract `deposit_credit`.**
`rent_due` for first-month tenants bundles deposit: `rent_due = prorated + deposit - booking`.
Balance formula: `max(0, rent_due - total_paid - prepaid_credit - deposit_credit)`.
Without `- deposit_credit`, tenants who paid their deposit show balance = rent_due (fully unpaid) → inflated dues.

**Rule 7: `trigger_monthly_sheet_sync` must be called after every PWA payment.**
Without this, the COLLECTION row stays stale after payments are logged via the PWA.

**Why:** Three simultaneous failures all pointed at the same number (Total Dues). Each fix revealed the next layer. The root cause was unclear ownership of the COLLECTION row — multiple writers each computing a different formula.

**How to apply:** Before touching any gsheets write path, grep for `_refresh_summary_sync`, `ws.update`, `trigger_monthly_sheet_sync`, `collection_summary`. Verify each function only touches what it owns.
