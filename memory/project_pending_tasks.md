---
name: Pending Tasks
description: Master to-do list for PG Accountant project — updated each session
type: project
---

## Active / Next Up

1. **WhatsApp smoke test** — send these to the live bot to verify day-wise parity:
   - "how many guests today" → should count day-stay guests
   - "[DayWise GuestName] balance" → should return balance (dues − paid)
   - "change [DayWise GuestName] rent 600" → should update Tenancy.agreed_rent
   - "move [DayWise GuestName] to room 305" → should use regular ROOM_TRANSFER flow
2. **`test_activity_log.py` broken** — pre-existing failure (`sys.exit()` at module level). Investigate separately; not caused by day-wise work.
3. **Review `docs/DATA_ARCHITECTURE.md`** — Kiran to approve design doc before Step 1 refactor.
4. **Chandra off-book cash** — Mar Rs.1.6L + Apr Rs.15.5K. Decide if we log as explicit entries.
5. **70 unclassified bank txns** — Kiran to fill yellow column in `data/reports/unclassified_review.xlsx`.
6. **WhatsApp template approval** — `cozeevo_checkin_form` still PENDING from Meta.
7. **PydanticAI integration** — 3-session plan (see `project_pydanticai_plan.md`).

## Paused

- **Cozeevo website (getkozzy.com)** — landing page paused, waiting for Canva assets.

## Recently Completed (v1.33.0)

- Full DB wipe + reload (Jan-Mar from master Excel, Apr from April Collection)
- DB ↔ Excel reconciliation (matches exactly for Cash + UPI)
- Fixed shared-phone partner import bug
- Wrote `RENT_RECONCILIATION.md` (7-step monthly process)
- Wrote `DATA_ARCHITECTURE.md` (canonical data model + migration plan)
- Built `cash_report.py` (proper for_type filtering)
- Saved feedback memory: no false alarms on data integrity
