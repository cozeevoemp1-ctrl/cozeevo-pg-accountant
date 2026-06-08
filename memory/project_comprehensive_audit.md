---
name: PWA Comprehensive Business Logic Audit
description: End-to-end audit plan for all 19 PWA pages + consolidation of business logic docs
type: project
---

# Comprehensive PWA Business Logic Audit — APPROVED PLAN

**Date Approved:** 2026-06-08
**Status:** In Progress (Session A executing Tasks 1-8)
**Execution Model:** Subagent-driven development (two-stage review per task)
**Context Budget Strategy:** Split across 2 sessions to stay under 1M tokens

---

## Goal

Audit all 19 PWA pages for business logic consistency, endpoint connectivity, and bugs. Consolidate scattered rules into existing docs with code locations, test cases, and audit dates. Create permanent bug tracker with historical tickets.

---

## What We're Doing

### Phase 1: Audit Execution (Tasks 1-8) — This Session

**Parallel Batch 1 (6 agents):**
- Task 1: Financial domain audit (6 pages: notices, checkout, payment, checkouts, payments/history, finance)
- Task 2: Occupancy domain audit (4 pages: home, tenants, operations, onboarding/bookings)
- Task 3: Data sync domain audit (3 pages: tenants/edit, finance upload, checkouts)
- Task 4: Bookings/onboarding domain audit (4 pages: bookings, pre-register, checkin, checkout)
- Task 5: Auth/admin domain audit (6 pages: login, auth/update-password, activity, reminders, collection/*, operations)
- Task 6: Historical bug collection (scan CHANGELOG.md, assign BUG-0001 onwards)

**Parallel Batch 2 (2 agents):**
- Task 7: Scan existing docs & extract all rules (REPORTING.md, BUSINESS_LOGIC.md, BRAIN.md, SHEET_LOGIC.md, BOT_FLOWS.md, MASTER_DATA.md)
- Task 8: Identify linked rules & verify sync (occupancy, deposit eligibility, expected checkout)

**Output:** 5 domain audit reports + rules extraction working docs, all committed to git

### Phase 2: Integration (Tasks 9-13) — Next Session (Session B)

- Task 9: Merge audit findings into consolidated docs (REPORTING.md, BUSINESS_LOGIC.md, BRAIN.md, SHEET_LOGIC.md, BOT_FLOWS.md, MASTER_DATA.md)
- Task 10: Create navigation indexes (docs/INDEX.md, docs/RULES_BY_CODE_LOCATION.md)
- Task 11: Build complete BUG_TRACKER.md from Phase 1 findings + historical bugs
- Task 12: Generate audit synthesis report (findings summary, recommendations, checklist)
- Task 13: Final cleanup & commit

**Output:** Consolidated docs with code locations/test cases/audit dates, indexes, BUG_TRACKER.md with ticket IDs, recurring_issues.md

---

## Key Decisions Made

1. **Use Git + MD files only** — No Notion, everything version-controlled
2. **Consolidate into EXISTING docs** — No new files, reuse: REPORTING.md, BUSINESS_LOGIC.md, BRAIN.md, SHEET_LOGIC.md, BOT_FLOWS.md, MASTER_DATA.md
3. **Sheet column rule:** SHEET_LOGIC.md = anything with Google Sheets or Excel
4. **Occupancy rule location:** BUSINESS_LOGIC.md (primary) + REPORTING.md (linked/mirrored)
5. **Replacement booking logic:** BRAIN.md (architecture)
6. **Bidirectional rules must sync:** Audit verifies they stay in sync, link them with last_audit_date
7. **Bug tickets:** Assign IDs BUG-0001 onwards, include root causes + prevention checklists in every fix
8. **Fix protocol:** Every bug fix must follow: Understand → Root Cause → Check All Endpoints → Deploy → Document

---

## Scope: What Gets Audited

**19 PWA Pages:**
- /notices, /checkout/new, /payment/new, /checkouts, /payments/history, /finance
- /, /tenants, /operations, /onboarding/bookings
- /tenants/[id]/edit, /finance (upload)
- /login, /auth/update-password, /activity, /reminders, /collection/*, /operations
- /tenants/pre-register, /checkin/new

**Business Logic Categories:**
- Financial (dues, deposits, checkout, refunds, payments)
- Occupancy (bed counts, room occupancy %, replacements, premium rooms)
- Data Sync (DB-first policy, sheet mirrors, import idempotency, payment sync)
- Bookings (onboarding flow, status transitions, quick-book, no-show)
- Auth (access gates, roles, audit logs, password reset)

---

## Execution Constraints

**Context Budget:**
- Session A (this): Tasks 1-8 (audit + consolidation) — ~1.5M tokens max
- Session B (next): Tasks 9-13 (integration) — fresh context, reads from git
- **Checkpoints:** All git commits between sessions, no data loss

**Subagent-Driven Approach:**
- One fresh subagent per task (isolated context)
- Two-stage review: spec compliance → code quality
- No context pollution between tasks
- Questions allowed mid-task (pause, answer, resume)

---

## Success Criteria

✅ All 19 pages analyzed
✅ Each endpoint mapped to business logic
✅ All rules consolidated into existing docs
✅ Bidirectional rules verified in sync
✅ 3+ inconsistencies found and consolidated
✅ 8+ bugs identified with root causes
✅ Test coverage gaps identified
✅ Historical bugs assigned ticket IDs (BUG-0001 onwards)
✅ Documentation gaps filled (premium rooms, staff rooms, room 000 flow)
✅ Navigation indexes created
✅ Recurring patterns identified with prevention checklists

---

## Deliverables (Session A)

Location: `docs/audits/2026-06-08-pwa-comprehensive/`

1. **01_FINANCIAL_AUDIT.md** — 6 pages analyzed, endpoints mapped, inconsistencies found, bugs prioritized
2. **02_OCCUPANCY_AUDIT.md** — Replacement logic inconsistency found, bed counts verified, premium room gap identified
3. **03_DATA_SYNC_AUDIT.md** — DB-first policy verified, sheet columns checked, import idempotency confirmed
4. **04_BOOKINGS_AUDIT.md** — State machine verified, room validation confirmed, quick-book logic tested
5. **05_AUTH_AUDIT.md** — Access gates verified, role checks confirmed, audit logging gaps found
6. **RULES_EXTRACTION.md** — All rules extracted from 6 main docs, duplicates and conflicts identified
7. **LINKED_RULES_AUDIT.md** — Bidirectional rules verified: occupancy, deposit, expected_checkout all synced

Plus: BUG_TRACKER.md (structure created), git commits after each batch

---

## Deliverables (Session B)

Location: `docs/` + `memory/`

1. **Updated REPORTING.md** — Financial rules enhanced with code locations, test cases, last audit date
2. **Updated BUSINESS_LOGIC.md** — Calculation rules enhanced, linked to REPORTING.md where bidirectional
3. **Updated BRAIN.md** — Replacement booking logic consolidated, conflicts resolved
4. **Updated SHEET_LOGIC.md** — Column rules enhanced with code locations
5. **Updated BOT_FLOWS.md** — Linked to BUSINESS_LOGIC.md for state machines
6. **Updated MASTER_DATA.md** — Linked code locations for TOTAL_BEDS constant
7. **docs/INDEX.md** — Navigation by topic + by file + linked rules status
8. **docs/RULES_BY_CODE_LOCATION.md** — Reverse lookup (code file → rules implemented)
9. **docs/BUG_TRACKER.md** — Complete history BUG-0001 onwards with root causes
10. **memory/recurring_issues.md** — Bug patterns + prevention checklists for code review

---

## If Work Extends

- Tasks 1-8 can be paused/resumed (all progress in git)
- Session A can close anytime, Session B picks up fresh from committed audit data
- No token context needed from Session A in Session B (all reads from git)

---

## When This Is Done

1. All business logic is consolidated in ONE place per domain
2. Code locations are documented (file:line) for every rule
3. Test cases are documented for every rule
4. Last audit date tracks rule freshness
5. Bidirectional rules are linked and synced
6. All bugs have ticket IDs and root causes
7. Recurring patterns are documented with prevention checklists
8. Future fixes will reference this audit + follow prevention protocol

---

## Next Steps

**Session A (NOW):**
1. Invoke subagent-driven-development skill
2. Execute Tasks 1-8 in series (with two-stage review between each task)
3. All output → git commit
4. Session closes

**Session B (New session):**
1. Read audit reports from git
2. Execute Tasks 9-13
3. Finalize all consolidated docs
4. Final git commit

---

**Status:** ✅ Approved, plan committed, Session A ready to execute
