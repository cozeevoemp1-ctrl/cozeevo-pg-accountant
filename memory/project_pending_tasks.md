---
name: Pending Tasks
description: Master to-do list for PG Accountant project — updated each session
type: project
---

## Active / Next Up

1. **Review `docs/DATA_ARCHITECTURE.md`** — Kiran to approve design doc before Step 1 refactor (create `src/data/schemas.py`).
2. **Sheet sync completion** — background job at session end was still running (`sync_sheet_from_db.py` for Dec/Jan/Feb/Mar/Apr). Verify monthly tabs match DB after wake. Also run `import_daywise.py` for DAY WISE tab.
3. **Chandra off-book cash** — Mar Rs.1.6L + Apr Rs.15.5K confirmed by Kiran. Documented in `RENT_RECONCILIATION.md`. Not yet added to DB — decide if we log as explicit entries with note "Off-book Chandra collection".
4. **Data architecture migration** (6 sessions) — after doc approval:
   - Step 1: Define schemas in `src/data/schemas.py`
   - Step 2: Refactor `import_april.py` (replace `COL_X = N` with header lookup)
   - Step 3: Refactor `clean_and_load.py::read_history`
   - Step 4: Unify bank statement readers
   - Step 5: Consolidate publishers
   - Step 6: CI check + docs
5. **70 unclassified bank txns** — generic UPI with no description. Kiran to fill yellow column in `data/reports/unclassified_review.xlsx`.
6. **WhatsApp template approval** — `cozeevo_checkin_form` still PENDING from Meta.
7. **VPS deploy** — v1.33.0 needs deploy after local test.
8. **PydanticAI integration** — 3-session plan (see `project_pydanticai_plan.md`).

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
