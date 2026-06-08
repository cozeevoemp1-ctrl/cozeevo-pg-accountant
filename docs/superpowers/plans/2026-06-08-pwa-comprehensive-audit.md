# PWA End-to-End Business Logic Audit + Consolidation

> **For agentic workers:** Use superpowers:subagent-driven-development to execute this plan. Each audit agent works in parallel; consolidation agents merge findings into existing docs.

**Goal:** Audit all 19 PWA pages for business logic consistency, endpoint connectivity, and bugs. Consolidate scattered rules into existing docs with code locations, test cases, and audit dates. Create permanent bug tracker with historical tickets.

**Architecture:** 
- Phase 1: Parallel audit of 5 domains (Financial, Occupancy, Data Sync, Bookings, Auth) + historical bug scan
- Phase 2: Parallel consolidation (scan existing docs, identify duplicates and linked rules)
- Phase 3: Integration (merge audit findings, create indexes, link bidirectional rules, build BUG_TRACKER.md)

**Tech Stack:** Git, Markdown, Python (for analysis), ripgrep (for codebase search)

---

## File Structure

**Outputs (no new files, reuse existing):**
- `docs/REPORTING.md` ← Consolidated financial rules (enhanced with code locations, test cases, audit dates)
- `docs/BUSINESS_LOGIC.md` ← Consolidated calculation rules (enhanced, linked to REPORTING.md where bidirectional)
- `docs/BRAIN.md` ← Consolidated architecture (replacement booking logic, occupancy logic)
- `docs/SHEET_LOGIC.md` ← Consolidated sheet/Excel parsing rules (enhanced with code locations)
- `docs/BOT_FLOWS.md` ← Consolidated intent/workflow flows (enhanced)
- `docs/MASTER_DATA.md` ← Room layout, bed counts (enhanced with code locations)
- `docs/BUG_TRACKER.md` ← NEW: All historical bugs with ticket IDs (BUG-0001 onwards)
- `memory/recurring_issues.md` ← NEW: Bug patterns + prevention checklists
- `docs/INDEX.md` ← NEW: Navigation index linking all business logic docs
- `docs/audits/2026-06-08-pwa-comprehensive/` ← NEW: Audit reports (5 domain reports + synthesis)

---

## Phase 1: Audit Agents (Parallel)

### Task 1: Financial Domain Audit

**Files:**
- Audit: `/notices`, `/checkout/new`, `/payment/new`, `/checkouts`, `/payments/history`, `/finance` pages
- Reference: `web/lib/api.ts`, `src/api/v2/tenants.py`, `src/api/v2/finance.py`
- Output: `docs/audits/2026-06-08-pwa-comprehensive/01_FINANCIAL_AUDIT.md`

**Steps:**

- [ ] **Step 1: Inventory all financial pages**

Analyze these pages and document:
```
/notices → endpoints called, business logic used
/checkout/new → endpoints called, business logic used
/payment/new → endpoints called, business logic used
/checkouts → endpoints called, business logic used
/payments/history → endpoints called, business logic used
/finance → endpoints called, business logic used
```

Create audit report section:
```markdown
## Page: /notices
- Endpoints: GET /api/v2/app/notices/active
- Business Logic: Deposit eligibility, expected_checkout, notice_date, days_remaining
- Data Flow: API → Component state → Display
- Related Rules: REPORTING.md §Deposit Eligibility, BUSINESS_LOGIC.md §Notice Logic
```

- [ ] **Step 2: Map endpoints to rules**

For each endpoint, trace to documented rule and verify code matches:
```markdown
## Endpoint: GET /api/v2/app/notices/active
- Code: src/api/v2/notices.py
- Returns: NoticeItem[] with deposit_eligible, expected_checkout
- Rule: REPORTING.md §Deposit Eligibility (definition) + BUSINESS_LOGIC.md §Notice Dates
- Implementation Match: ✅ Code matches docs / ⚠️ Partial / ❌ Conflict
- Code location: src/api/v2/notices.py:104-125 (deposit_eligible logic)
```

- [ ] **Step 3: Check for inconsistencies**

Search for conflicts:
- Same rule calculated differently across pages?
- Endpoint returns different data than page expects?
- Documented rule doesn't match code?

Document findings:
```markdown
## Inconsistency: [Issue Name]
- Page X shows: [behavior]
- Page Y shows: [different behavior]
- Root cause: [why different]
- Impact: [what breaks]
- Fix: [recommendation]
```

- [ ] **Step 4: Identify missing tests**

Check test coverage for each rule:
```bash
grep -r "deposit_eligible\|expected_checkout" tests/ 2>/dev/null | wc -l
```

Document:
```markdown
## Test Coverage: Deposit Eligibility
- Unit test: tests/test_deposit_logic.py::test_deposit_eligible_on_time ✅
- Unit test: tests/test_deposit_logic.py::test_deposit_eligible_late ✅
- Integration test: tests/test_notices_api.py::test_notices_deposit_flag ✅
- E2E test: None (user journey not covered)
- Gap: [specific gap]
```

- [ ] **Step 5: Identify bugs + severity**

Document any bugs found:
```markdown
## Bugs Found: Financial Domain

### BUG-XXXX: [Bug Name]
- Pages affected: [list]
- Root cause: [why]
- Impact: CRITICAL / HIGH / MEDIUM / LOW
- Fix: [code change needed]
- Effort: [time estimate]
```

- [ ] **Step 6: Commit audit report**

```bash
git add docs/audits/2026-06-08-pwa-comprehensive/01_FINANCIAL_AUDIT.md
git commit -m "audit: Financial domain pages — rules, endpoints, bugs, test gaps"
```

---

### Task 2: Occupancy Domain Audit

**Files:**
- Audit: `/` (home), `/tenants`, `/operations`, `/onboarding/bookings` pages
- Reference: `web/lib/api.ts`, `src/api/v2/kpi.py`, `src/api/onboarding_router.py`
- Output: `docs/audits/2026-06-08-pwa-comprehensive/02_OCCUPANCY_AUDIT.md`

**Steps:**

- [ ] **Step 1: Inventory occupancy pages**

Document each page:
```markdown
## Page: / (Home)
- Endpoints: GET /api/v2/app/kpi
- Logic: Occupancy %, beds occupied, free beds, premium vs regular
- Related Rules: BUSINESS_LOGIC.md §Occupancy Calculation, MASTER_DATA.md §Bed Counts

## Page: /tenants
- Endpoints: GET /api/v2/app/tenants/list
- Logic: Tenant list, status, room occupancy indicator
- Related Rules: BUSINESS_LOGIC.md §Room Occupancy

## Page: /operations
- Endpoints: GET /api/v2/app/kpi, GET /api/v2/app/occupancy/detail
- Logic: Building occupancy breakdown, room-by-room status
- Related Rules: MASTER_DATA.md §Room Layout, BUSINESS_LOGIC.md §Occupancy Calculation

## Page: /onboarding/bookings
- Endpoints: GET /api/onboarding/admin/pending
- Logic: Replacement badge (is booking replacing leaving tenant?), room assignment
- Related Rules: BRAIN.md §Replacement Booking Logic, BUSINESS_LOGIC.md §Room Occupancy
```

- [ ] **Step 2: Trace replacement booking logic**

Find where replacement logic is implemented:
```bash
grep -n "is_replacement\|replacement.*booking\|prebooking" src/api/v2/kpi.py
grep -n "is_replacement\|replacement.*booking\|prebooking" src/api/onboarding_router.py
```

Document all locations:
```markdown
## Replacement Booking Logic Locations

### Implementation 1: src/api/v2/kpi.py (Notices page)
- Lines: [line range]
- Rule: booking.checkin_date >= leaving_tenant.expected_checkout
- Includes: pending_review + pending_tenant statuses
- Test: [test name if exists]

### Implementation 2: src/api/onboarding_router.py (Bookings page)
- Lines: [line range]
- Rule: room has active tenants → is_replacement = true
- Missing: [what's different from Implementation 1]
- Test: [test name if exists]
- Discrepancy: ⚠️ Different logic on different pages!
```

- [ ] **Step 3: Check bed count consistency**

Verify TOTAL_BEDS constant matches across codebase:
```bash
grep -n "TOTAL_BEDS" src/integrations/gsheets.py
grep -n "TOTAL_BEDS" scripts/clean_and_load.py
grep -n "TOTAL_BEDS" src/whatsapp/handlers/account_handler.py
```

Document bed counts:
```markdown
## Bed Count Constants (Should all match)

### src/integrations/gsheets.py
- TOTAL_BEDS = [value]
- Last verified: [date]
- Definition: [explanation]

### scripts/clean_and_load.py
- TOTAL_BEDS = [value]
- Last verified: [date]
- Matches: ✅ / ⚠️ / ❌

### ... (continue for all locations)

## Status: ✅ Consistent / ⚠️ Minor discrepancies / ❌ Major inconsistencies
```

- [ ] **Step 4: Verify occupancy formula**

```markdown
## Occupancy Calculation Formula

### Current (code):
[code snippet showing how it's calculated]

### Documented (BUSINESS_LOGIC.md §Occupancy):
[what docs say]

### Match: ✅ / ⚠️ / ❌

### Test Coverage:
- [test 1] ✅
- [test 2] ✅
- [test 3] ✅
- Gap: [what's not tested]
```

- [ ] **Step 5: Identify bugs**

```markdown
## Bugs Found: Occupancy Domain

### BUG-XXXX: [Bug Name]
- Pages affected: [list]
- Root cause: [why]
- Code: [file:line]
- Impact: CRITICAL / HIGH / MEDIUM / LOW
- Fix: [recommendation]
- Effort: [time estimate]
```

- [ ] **Step 6: Commit audit report**

```bash
git add docs/audits/2026-06-08-pwa-comprehensive/02_OCCUPANCY_AUDIT.md
git commit -m "audit: Occupancy domain — replacement logic, bed counts, inconsistencies"
```

---

### Task 3: Data Sync Domain Audit

**Files:**
- Audit: `/tenants/[id]/edit`, `/finance` (data upload), `/checkouts` pages
- Reference: `src/integrations/gsheets.py`, `src/database/excel_import.py`, `src/api/v2/finance.py`
- Output: `docs/audits/2026-06-08-pwa-comprehensive/03_DATA_SYNC_AUDIT.md`

**Steps:**

- [ ] **Step 1: Verify DB-first policy**

Trace data flow from PWA write to DB to Sheet:
```markdown
## Data Flow Example: Edit Tenant Agreed Rent

### Step 1: Frontend POST
- Endpoint: PATCH /api/v2/tenancies/{id}
- Payload: { agreed_rent: 11000 }
- Code: [file:line]

### Step 2: Backend DB write
- Code: [file:line function name]
- DB: UPDATE tenancies SET agreed_rent=... WHERE id=...
- Audit log: [Is it created?]
- Status: ✅ DB updated first / ❌ Not first

### Step 3: Sheet sync
- Code: [file:line]
- Call: [function call shown]
- Action: [what it does]
- Status: ✅ Mirrors DB / ❌ Other direction

## Conclusion: ✅ DB-first policy verified / ❌ Violated
```

- [ ] **Step 2: Check sheet column refs**

Verify no hardcoded column indexes:
```bash
grep -n "r\[14\]\|row\[2\]\|chr(65.*n)" src/integrations/gsheets.py
grep -n "r\[14\]\|row\[2\]\|chr(65.*n)" scripts/clean_and_load.py
```

Document findings:
```markdown
## Sheet Column References

### Findings:
- ✅ src/integrations/gsheets.py: Uses [method]
- ✅ scripts/clean_and_load.py: Uses [method]
- ❌ [file]: Uses hardcoded indexes

## Status: ✅ No column index bugs / ⚠️ Partial / ❌ Issues found
```

- [ ] **Step 3: Audit payment sync**

```markdown
## Payment Sync Flow

### Source of Truth: [which system]
### Mirror: [where it mirrors to]

### Payment Recording:
1. [step 1]
2. [step 2]
3. [result]

### Consistency Check:
- Code: [file:line]
- Query: [SQL or logic]
- Sheet formula: [what sheet does]
- Match: ✅ / ⚠️ / ❌

### Known Issues:
- [issue 1]
- [issue 2]
```

- [ ] **Step 4: Check import idempotency**

```markdown
## Excel Import Idempotency

### Script: [file]

### Idempotency check:
- Question: [what happens on duplicate import?]
- Code: [file:line logic]
- Status: ✅ Idempotent / ❌ Not safe

### Mitigation: [how it's safe despite potential issues]
```

- [ ] **Step 5: Identify bugs**

```markdown
## Bugs Found: Data Sync Domain

### BUG-XXXX: [Bug Name]
- Symptom: [what user sees]
- Root cause: [why it happens]
- Impact: [what breaks]
- Fix: [code change]
- Effort: [time estimate]
```

- [ ] **Step 6: Commit audit report**

```bash
git add docs/audits/2026-06-08-pwa-comprehensive/03_DATA_SYNC_AUDIT.md
git commit -m "audit: Data sync domain — DB-first policy, sheet columns, import idempotency"
```

---

### Task 4: Bookings/Onboarding Domain Audit

**Files:**
- Audit: `/onboarding/bookings`, `/tenants/pre-register`, `/checkin/new`, `/checkout/new` pages
- Reference: `src/api/onboarding_router.py`, `src/api/v2/bookings.py`, `BOT_FLOWS.md`
- Output: `docs/audits/2026-06-08-pwa-comprehensive/04_BOOKINGS_AUDIT.md`

**Steps:**

- [ ] **Step 1: Map onboarding state machine**

```markdown
## Onboarding Session Status Flow

### States (from code):
- [state 1]: [description]
- [state 2]: [description]
- ... (list all)

### Transitions (documented in BOT_FLOWS.md):
- [state] → [state]: [how] (code: [file:line])
- [state] → [state]: [how] (code: [file:line])
- ... (list all)

### Match: ✅ Code transitions match documented flow / ⚠️ / ❌
```

- [ ] **Step 2: Verify room assignment validation**

```markdown
## Room Assignment Validation

### Check: When booking assigned to room, is occupancy validated?

### Code path:
1. [user action]
2. [API call]
3. [validation function]

### Validation logic:
- Query: [what query is run]
- Check: [what condition is checked]
- Status: ✅ Prevents overbooking / ❌ Missing validation

### Edge cases:
- [case 1]: [how it's handled]
- [case 2]: [gap detected]
```

- [ ] **Step 3: Check quick_book logic**

```markdown
## Quick Book (Fast Check-in)

### Flow:
1. [step 1]
2. [step 2]
3. [result]

### Code: [file:line]

### Test: [test file]
- ✅ [test name]
- ✅ [test name]
- ⚠️ [gap]

### Issue: [any problems found]
```

- [ ] **Step 4: Verify no-show → active transition**

```markdown
## No-Show Tenant Check-In

### User journey:
1. [step]
2. [step]
3. [result]

### Idempotency check:
- If checked in twice: [what happens]
- Code: [file:line]
- Status: ✅ Idempotent / ❌ Bug

### Financial impact:
- Rent schedule: [when calculated]
- Code: [file:line function]
- Test: [test name] ✅
- Status: ✅ Correct / ❌ Wrong
```

- [ ] **Step 5: Identify bugs**

```markdown
## Bugs Found: Bookings/Onboarding Domain

### BUG-XXXX: [Bug Name]
- Pages affected: [list]
- Root cause: [why]
- Impact: [what breaks]
- Fix: [code change]
- Effort: [time estimate]
```

- [ ] **Step 6: Commit audit report**

```bash
git add docs/audits/2026-06-08-pwa-comprehensive/04_BOOKINGS_AUDIT.md
git commit -m "audit: Bookings/onboarding domain — state machine, room validation, quick-book logic"
```

---

### Task 5: Auth/Admin Domain Audit

**Files:**
- Audit: `/login`, `/auth/update-password`, `/activity`, `/reminders`, `/collection/*`, `/operations` pages
- Reference: `web/middleware.ts`, `src/api/v2/auth.py`, `src/whatsapp/chat_api.py`
- Output: `docs/audits/2026-06-08-pwa-comprehensive/05_AUTH_AUDIT.md`

**Steps:**

- [ ] **Step 1: Verify auth gate on all protected pages**

```bash
grep -n "middleware\|getSession\|redirect" web/app/*/page.tsx
```

Document auth coverage:
```markdown
## Auth Gate Coverage

### Protected pages (should require auth):
- /page ✅ / ❌
- /notices ✅ / ❌
- /finance ✅ / ❌
- ... (list all)

### Verification: [middleware file]
- Code: [snippet]
- Status: ✅ All pages gated / ⚠️ / ❌ Missing gates
```

- [ ] **Step 2: Check role-based access**

```markdown
## Role-Based Access Control

### Roles in system:
- [role]: [permissions]
- [role]: [permissions]

### Enforcement points:
1. [location]
2. [location]
3. [location]

### Test coverage:
- [test] ✅
- [test] ✅
- Gap: [what's not tested]

### Issues:
- ⚠️ [issue 1]
- ⚠️ [issue 2]
```

- [ ] **Step 3: Verify audit logging**

```markdown
## Audit Log Coverage

### What should be logged:
- [sensitive operation 1]
- [sensitive operation 2]

### Code paths:
- [operation]: [file:line] ✅ / ❌
- [operation]: [file:line] ✅ / ❌

### Missing:
- ❌ [operation not logged]
- ❌ [operation not logged]

### Fix recommendation:
- [what to add]
```

- [ ] **Step 4: Check password reset flow**

```markdown
## Password Reset (Forgot Password)

### Flow:
1. [step]
2. [step]
3. [step]

### Code:
- [file:line]
- [file:line]

### Verification:
- ✅ [security check]
- ✅ [security check]
- ⚠️ [gap]: [what's missing]

### Test: [test file]
- ✅ [test name]
- ✅ [test name]
- ⚠️ Missing: [gap]
```

- [ ] **Step 5: Identify bugs**

```markdown
## Bugs Found: Auth/Admin Domain

### BUG-XXXX: [Bug Name]
- Pages affected: [list]
- Root cause: [why]
- Impact: [what breaks]
- Fix: [code change]
- Effort: [time estimate]
```

- [ ] **Step 6: Commit audit report**

```bash
git add docs/audits/2026-06-08-pwa-comprehensive/05_AUTH_AUDIT.md
git commit -m "audit: Auth/admin domain — access control, audit logging, password reset"
```

---

### Task 6: Historical Bug Collection & Ticket Assignment

**Files:**
- Source: `docs/CHANGELOG.md`, `git log`
- Output: `docs/BUG_TRACKER.md` (structure), assignment log

**Steps:**

- [ ] **Step 1: Extract bugs from CHANGELOG.md**

```bash
grep "^### fix:" docs/CHANGELOG.md | wc -l
```

Create list of all historical bugs with details:
```markdown
## Historical Bugs Extracted from CHANGELOG

From v1.76.52 (2026-06-07):
1. [bug name] — [brief description]
2. [bug name] — [brief description]

From v1.76.51 (2026-06-07):
3. [bug name] — [brief description]

... (continue through all releases)
```

- [ ] **Step 2: Assign ticket IDs**

Map chronologically:
```markdown
BUG-0001: [First bug from CHANGELOG]
BUG-0002: [Second bug]
BUG-0003: [Third bug]
... (continue sequential)
```

- [ ] **Step 3: Extract root causes from commit messages**

```bash
git log --oneline --all --grep="fix:" | head -50
```

For each bug, add to tracking doc:
```markdown
BUG-0001: [Bug Name]
- Commit: [hash]
- Root cause: [why it happened]
- Code: [file:line original code]
- Fix: [what was changed]
- How missed: [code review gap / test gap / design gap]
- Deployed: [date]
```

- [ ] **Step 4: Link to code locations**

Find what code was changed:
```bash
git log --oneline -S "keyword" | grep -i "fix"
git show [commit_hash]
```

Document affected files:
```markdown
BUG-0001: [Bug Name]
- Files changed: [file 1], [file 2]
- Lines changed: [range]
- Test added: [test name]
```

- [ ] **Step 5: Create BUG_TRACKER.md structure**

Create master bug tracker file with all historical bugs:
```markdown
# Bug Tracker

All bugs since project inception, with root causes, prevention steps, and recurring patterns.

---

## BUG-0001: [Bug Name]

**Symptom:** [What user sees]

**Root Cause:** [Why it happens]

**Implementation:**
[Code snippet showing before/after]

**Affected Endpoints:**
- [endpoint 1] (impact: [what breaks])
- [endpoint 2] (impact: [what breaks])

**Code Locations:**
- File: [file]
- Lines: [range]
- Commit: [hash]

**How It Was Missed:**
- [ ] Code review gap: [what reviewer should have caught]
- [ ] Test gap: [what test should exist]
- [x] Caught by: [how it was discovered]

**Prevention Steps:**
- [ ] [checklist item 1]
- [ ] [checklist item 2]

**Pattern:** [Pattern name from recurring_issues.md]

**Fixed:** [date], commit [hash]

---
```

- [ ] **Step 6: Commit bug tracker structure**

```bash
git add docs/BUG_TRACKER.md
git commit -m "audit: Create bug tracker with BUG-0001 through BUG-NNNN ticket IDs + root causes"
```

---

## Phase 2: Consolidation Agents (Parallel)

### Task 7: Scan Existing Docs & Extract Rules

**Files:**
- Scan: `docs/REPORTING.md`, `docs/BUSINESS_LOGIC.md`, `docs/BRAIN.md`, `docs/SHEET_LOGIC.md`, `docs/BOT_FLOWS.md`, `docs/MASTER_DATA.md`
- Output: `docs/audits/2026-06-08-pwa-comprehensive/RULES_EXTRACTION.md` (working doc)

**Steps:**

- [ ] **Step 1: Extract all rules from REPORTING.md**

Read file and list every rule:
```markdown
## Rules from REPORTING.md

### §1: [Rule Name]
**Rule ID:** RULE-FIN-001
**Text:** [Complete rule definition]
**Code location:** [file:line or function name]
**Last mentioned:** [filename line number]
**Related rules:** [list of related rules in other docs]

### §2: [Rule Name]
**Rule ID:** RULE-FIN-002
**Text:** [Complete rule definition]
**Code location:** [file:line]
**Last mentioned:** [filename line number]
**Related rules:** [list]

### § Continue... (all sections)
```

- [ ] **Step 2: Extract all rules from BUSINESS_LOGIC.md**

```markdown
## Rules from BUSINESS_LOGIC.md

### §1: [Rule Name]
**Rule ID:** RULE-OCC-001
**Text:** [Complete rule definition]
**Code location:** [file:line]
**Last mentioned:** [filename line number]
**Related rules:** [list including REPORTING.md cross-refs]
**Mirror location:** [if appears in other doc, note here]

### § Continue... (all sections)
```

- [ ] **Step 3: Extract all rules from BRAIN.md**

```markdown
## Rules from BRAIN.md

### [Section]: [Rule Name]
**Rule ID:** RULE-ARCH-001
**Text:** [Complete rule definition]
**Code locations:** 
  - [location 1]
  - [location 2] (if multiple implementations)
**Last mentioned:** [filename line number]
**Status:** ⚠️ CONFLICT if multiple implementations / ✅ Single implementation

### Continue... (all sections)
```

- [ ] **Step 4: Extract from SHEET_LOGIC.md**

```markdown
## Rules from SHEET_LOGIC.md

### Column: [Name]
**Rule ID:** RULE-SHEET-001
**Text:** [Column definition, format, contents]
**Format:** [number, text, date, etc]
**Related DB field:** [tenancies.field_name]
**Code location:** [file:line where it's referenced]
**Last mentioned:** [filename line number]

### Continue... (all columns/rules)
```

- [ ] **Step 5: Consolidate into extraction working document**

Create comprehensive rules extraction:
```bash
cat > docs/audits/2026-06-08-pwa-comprehensive/RULES_EXTRACTION.md << 'EOF'
# Rules Extraction Workbook

Working document: Extract all rules from existing docs, identify duplicates, conflicts, gaps.

## Summary
- Financial rules: [count] extracted
- Occupancy rules: [count] extracted
- Data sync rules: [count] extracted
- Sheet rules: [count] extracted
- Duplicates found: [count] (list which)
- Conflicts found: [count] (list which)
- Gaps: [list missing rules]

## Detailed Rules (see sections above)

## Duplicate Rules (need consolidation)
1. [Rule name]: [location 1] + [location 2] (same rule appears twice)
2. [Rule name]: [location 1] + [location 2]

## Conflicting Rules
1. [Rule name]: [location 1 says X] vs [location 2 says Y]

## Missing/Undocumented
1. [Rule that should be documented but isn't]
2. [Rule that's vague/unclear]

EOF
```

- [ ] **Step 6: Commit working doc**

```bash
git add docs/audits/2026-06-08-pwa-comprehensive/RULES_EXTRACTION.md
git commit -m "audit: Extract rules from existing docs — identify duplicates, conflicts, gaps"
```

---

### Task 8: Identify Linked Rules & Verify Sync

**Files:**
- Reference: Extracted rules from Task 7
- Output: `docs/audits/2026-06-08-pwa-comprehensive/LINKED_RULES_AUDIT.md`

**Steps:**

- [ ] **Step 1: List bidirectional rules**

Rules that appear in multiple docs and must stay in sync:
```markdown
## Bidirectional Rules (Must Stay in Sync)

### Rule: [Rule Name]
- **Primary location:** [doc §section]
- **Secondary location:** [doc §section]
- **Code:** [file:line function]
- **Sync requirement:** [What happens if formula changes]

### Rule: [Rule Name]
- **Primary location:** [doc §section]
- **Secondary location:** [doc §section]
- **Code:** [file:line function]
- **Sync requirement:** [What happens if formula changes]

### Continue... (all linked rules)
```

- [ ] **Step 2: Verify sync — Rule 1**

Read both docs and compare for first linked rule:
```markdown
## [Rule Name] Sync Check

### [Doc 1] §[section]:
"[Exact quote from doc 1]"
- References: [what constants/rules it cites]

### [Doc 2] §[section]:
"[Exact quote from doc 2]"
- References: [what constants/rules it cites]

### Code: [file:line]:
[Code snippet showing implementation]

### Verdict: ✅ SYNCED / ❌ OUT OF SYNC
- [explanation]

### Last verified: [date]
```

- [ ] **Step 3: Verify sync — Rule 2**

Repeat for second linked rule...

- [ ] **Step 4: Verify sync — Rule 3+**

Continue for all linked rules...

- [ ] **Step 5: Create linked rules map**

```markdown
# Linked Rules Audit

All bidirectional rules checked for sync.

## Summary
- Total bidirectional rules: [count]
- Synced: [count] ✅
- Out of sync: [count] ❌
- Last audit: [date]

## Map

[RULE 1] ← status → [RULE 1] + [CODE]
  ↓ verified [date]

[RULE 2] ← status → [RULE 2] + [RULE 3] + [CODE]
  ↓ verified [date]

... (continue for all)
```

- [ ] **Step 6: Commit linked rules audit**

```bash
git add docs/audits/2026-06-08-pwa-comprehensive/LINKED_RULES_AUDIT.md
git commit -m "audit: Verify linked rules sync — identify inconsistencies and create map"
```

---

## End of Session A

At this point:
- ✅ All 6 audit agents (Tasks 1-6) have completed and committed audit reports
- ✅ Both consolidation agents (Tasks 7-8) have completed and committed analysis docs
- ✅ All findings are in git (`docs/audits/2026-06-08-pwa-comprehensive/`)
- ✅ Session A is complete and safe to close

**Session B (new session) will:**
- Read all audit findings from git
- Execute Tasks 9-13 (merge findings into consolidated docs, create indexes, finalize BUG_TRACKER.md)
- End with all business logic consolidated + linked + audit-dated
