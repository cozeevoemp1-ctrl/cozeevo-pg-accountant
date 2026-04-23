# Phase 2 — Handler Refactor & Operational Hardening

> **Status:** planned · **Author session:** 2026-04-23 late-night · **Owner:** Kiran
>
> **For agentic workers:** Use `superpowers:executing-plans` to walk step-by-step. Each commit must stop for review. No "while I'm here" scope creep.

## Why this plan exists

Kiran's complaint: "too many handlers". Phase 1 (commits 392cdea + e9a3201) added frozen-month guards, a canonical status helper, and consolidated the payment-mode regex. That was the safe low-hanging fruit.

The real structural problem is still there:

- [`src/whatsapp/handlers/owner_handler.py`](../../src/whatsapp/handlers/owner_handler.py) is 6000+ lines.
- `resolve_pending_action` alone is ~3500 lines with **47 `if pending.intent == "X":`** branches (confirmed 2026-04-23 — see grep log at bottom of this doc).
- Every new intent adds another branch. One `return ""` in one branch nearly lost a payment (CHANGELOG 1.50.1).
- Fire-and-forget sheet syncs silently diverge on failure.
- Monthly rollover is polling, not scheduled.

## Scope

This plan splits into **four commits**. Execute in order, stop for review after each.

- **2A** — resolver dispatch table + extract onboarding/form/doc resolvers
- **2B** — extract payment + expense + refund resolvers
- **2C** — extract tenant-edit + room-transfer + staff resolvers
- **2D** — operational hardening (retry queue, checkout cleanup, cron)

Do **not** mix these. Each commit is ~2-3 hours of work and needs its own test run.

Out of scope for Phase 2 (deferred to Phase 3 if ever):
- Splitting `owner_handler.py` dispatcher (`handle_owner`) — only `resolve_pending_action` is touched here.
- Reducing `gsheets.py` 25-function public API — separate concern.
- Rewriting `intent_detector.py` regex list — already centralized payment modes; rest works.

---

## 2A — Resolver dispatch + onboarding/form/doc extraction

**Goal:** Replace the top of `resolve_pending_action` (~47 `if pending.intent ==` branches) with a dispatch table. Extract the first 5 resolvers into their own module. Leave the rest inline until 2B/2C — the dispatcher handles "unknown" by falling through to the remaining inline branches. **Zero behavior change.**

### File map

| File | Action | Responsibility |
|---|---|---|
| `src/whatsapp/handlers/resolvers/__init__.py` | Create | Exports `PENDING_RESOLVERS` dict |
| `src/whatsapp/handlers/resolvers/_common.py` | Create | Shared: ctx types, helper imports, `_save_pending` re-export |
| `src/whatsapp/handlers/resolvers/onboarding.py` | Create | `resolve_approve_onboarding`, `resolve_form_extract_confirm`, `resolve_checkout_form_confirm`, `resolve_collect_docs`, `resolve_collect_receipt` |
| `src/whatsapp/handlers/owner_handler.py` | Modify | Import `PENDING_RESOLVERS`, dispatch at top of `resolve_pending_action`. Delete the extracted branches. |

### Commit breakdown (2A)

1. Create `resolvers/_common.py` with shared helpers.
2. Create `resolvers/onboarding.py` — move (not copy) the bodies of branches at [owner_handler.py:236](../../src/whatsapp/handlers/owner_handler.py#L236), [:391](../../src/whatsapp/handlers/owner_handler.py#L391), [:812](../../src/whatsapp/handlers/owner_handler.py#L812), [:927](../../src/whatsapp/handlers/owner_handler.py#L927), [:1003](../../src/whatsapp/handlers/owner_handler.py#L1003).
3. Create `resolvers/__init__.py` with the dispatch dict:
   ```python
   PENDING_RESOLVERS = {
       "APPROVE_ONBOARDING":      resolve_approve_onboarding,
       "FORM_EXTRACT_CONFIRM":    resolve_form_extract_confirm,
       "CHECKOUT_FORM_CONFIRM":   resolve_checkout_form_confirm,
       "COLLECT_DOCS":            resolve_collect_docs,
       "COLLECT_RECEIPT":         resolve_collect_receipt,
   }
   ```
4. Update `resolve_pending_action` — add dispatch at top:
   ```python
   async def resolve_pending_action(pending, reply_text, session, ...):
       from src.whatsapp.handlers.resolvers import PENDING_RESOLVERS
       action_data = json.loads(pending.action_data or "{}")
       choices = json.loads(pending.choices or "[]")
       if resolver := PENDING_RESOLVERS.get(pending.intent):
           return await resolver(pending, reply_text, session, action_data, choices, media_id=media_id, media_type=media_type, media_mime=media_mime)
       # Fallback to remaining inline branches (2B/2C will migrate these).
       ...existing 42 branches unchanged...
   ```
5. Delete the 5 extracted branches from owner_handler.
6. Run golden suite + test_full_flow_e2e. All must pass.

### Test plan (2A)

Must pass before commit:

```bash
TEST_MODE=1 venv/Scripts/python main.py      # terminal 1
venv/Scripts/python tests/eval_golden.py     # terminal 2 — full golden suite
venv/Scripts/python tests/test_full_flow_e2e.py
```

Manual smoke checks (API must be running):

- Onboarding: admin sends `start onboarding`, completes form, hits "yes" at APPROVE_ONBOARDING — tenant row created, photo sync.
- COLLECT_DOCS: send a photo while in pending docs state — photo saved, receipt continues.
- COLLECT_RECEIPT: after a payment confirm Yes, send a receipt photo / `skip`.

Fail criteria: any regression in the golden suite or an exception in the above smoke flows. If this happens, revert the commit and investigate before retrying.

### Acceptance

- All 5 moved resolvers have **identical** behaviour (same DB writes, same replies, same pending-state transitions). Diff old vs new line-by-line.
- `owner_handler.py` line count drops by ~350.
- `resolve_pending_action` has a dispatch at the top that routes 5 intents; remaining 42 branches stay inline for 2B.

---

## 2B — Extract payment + expense + refund resolvers

**Goal:** Migrate the financial-state resolvers.

### File map

| File | Action |
|---|---|
| `src/whatsapp/handlers/resolvers/payment.py` | Create |
| `src/whatsapp/handlers/resolvers/expense.py` | Create |
| `src/whatsapp/handlers/resolvers/refund.py` | Create |
| `src/whatsapp/handlers/owner_handler.py` | Modify — delete migrated branches |
| `src/whatsapp/handlers/resolvers/__init__.py` | Modify — add 9 entries |

### Branches to migrate (owner_handler.py)

- `CONFIRM_PAYMENT_LOG` — [:1047](../../src/whatsapp/handlers/owner_handler.py#L1047)
- `CONFIRM_PAYMENT_ALLOC` — [:1198](../../src/whatsapp/handlers/owner_handler.py#L1198)
- `CONFIRM_ADD_EXPENSE` — [:1316](../../src/whatsapp/handlers/owner_handler.py#L1316)
- `CONFIRM_DEPOSIT_REFUND` — [:1411](../../src/whatsapp/handlers/owner_handler.py#L1411)
- `COLLECT_RENT_STEP` — [:1730](../../src/whatsapp/handlers/owner_handler.py#L1730) (collect-rent wizard)
- `LOG_EXPENSE_STEP` — [:2087](../../src/whatsapp/handlers/owner_handler.py#L2087)
- `VOID_PAYMENT`, `VOID_WHICH`, `VOID_EXPENSE`, `VOID_WHO` — [:2907-2959](../../src/whatsapp/handlers/owner_handler.py#L2907)
- `OVERPAYMENT_RESOLVE`, `OVERPAYMENT_ADD_NOTE`, `UNDERPAYMENT_NOTE` — [:2774-2879](../../src/whatsapp/handlers/owner_handler.py#L2774)
- `DUPLICATE_CONFIRM` — [:2760](../../src/whatsapp/handlers/owner_handler.py#L2760)

Plus the `chosen is not None and pending.intent == "PAYMENT_LOG"` / `"REFUND_WHO"` disambig branches — those stay in owner_handler for 2A+2B (they're pre-resolver choice handling; don't touch).

### Test plan (2B)

- `tests/test_full_flow_e2e.py` — end-to-end payment + allocation + overpay + void
- `tests/test_collect_rent_comprehensive.py`
- `tests/test_payment_confirm_overpay.py` (the one written for CHANGELOG 1.50.1)

**All must pass.** Any missing test = write it before migrating.

### Acceptance (2B)

- `owner_handler.py` line count drops another ~900.
- `PENDING_RESOLVERS` dict grows to 14 entries.
- Payment smoke: log rent, split payment, overpay, void — each produces identical DB rows + sheet writes as before.

---

## 2C — Extract tenant-edit + room-transfer + staff resolvers

### Branches to migrate

| Intent | Line | Resolver file |
|---|---|---|
| `CONFIRM_ADD_TENANT` | [:3210](../../src/whatsapp/handlers/owner_handler.py#L3210) | `resolvers/tenant.py` |
| `CONFIRM_FIELD_UPDATE` | [:1369](../../src/whatsapp/handlers/owner_handler.py#L1369) | `resolvers/tenant.py` |
| `UPDATE_TENANT_NOTES_STEP` | [:3317](../../src/whatsapp/handlers/owner_handler.py#L3317) | `resolvers/tenant.py` |
| `UPDATE_CHECKOUT_DATE_ASK` | [:1500](../../src/whatsapp/handlers/owner_handler.py#L1500) | `resolvers/tenant.py` |
| `RECORD_CHECKOUT` | [:1518](../../src/whatsapp/handlers/owner_handler.py#L1518) | `resolvers/tenant.py` |
| `ADD_TENANT_INCOMPLETE` | [:2229](../../src/whatsapp/handlers/owner_handler.py#L2229) | `resolvers/tenant.py` |
| `RENT_CHANGE`, `DEPOSIT_CHANGE`, `DEPOSIT_CHANGE_AMT` | [:2234, :3102, :3115](../../src/whatsapp/handlers/owner_handler.py#L2234) | `resolvers/tenant.py` |
| `ROOM_TRANSFER*` (5 variants) | [:2251-2376](../../src/whatsapp/handlers/owner_handler.py#L2251) | `resolvers/room_transfer.py` |
| `ASSIGN_ROOM_STEP` | [:2376](../../src/whatsapp/handlers/owner_handler.py#L2376) | `resolvers/room.py` |
| `EXIT_STAFF_WHO` (inside `CONFIRM_FIELD_UPDATE`) | [:1393](../../src/whatsapp/handlers/owner_handler.py#L1393) | `resolvers/staff.py` |
| `ADD_CONTACT_STEP`, `UPDATE_CONTACT_STEP` | [:3415, :3590](../../src/whatsapp/handlers/owner_handler.py#L3415) | `resolvers/contact.py` |

### Test plan (2C)

- `tests/test_room_transfer_e2e.py`
- `tests/test_staff_room_invariant.py`
- Manual: `update notes for 603` (regression-test the fix we just shipped)
- Manual: `add tenant` flow end-to-end
- Manual: `change rent for <X> to <N>` flow

### Acceptance (2C)

- `owner_handler.py` line count drops another ~800. Final size < 3000 lines.
- `PENDING_RESOLVERS` has ~35+ entries.
- `resolve_pending_action` itself is < 200 lines — just dispatch + fallthrough for any unmigrated edge case.

---

## 2D — Operational hardening (parallel to 2A/2B/2C — no dependency)

### Items

#### 1. Sheet-sync retry queue (HIGH — silent divergence risk)

Currently 20+ sites do `asyncio.create_task(sheet_write(...))` with no retry, no alert. If sheet API is down for 5 minutes, every mutation during that window silently diverges.

**Fix:** In `src/services/sheet_sync_queue.py` (new):
- `enqueue_sheet_op(op_name: str, payload: dict)` — writes a row to a new `sheet_sync_queue` DB table.
- A scheduled job drains the queue every 60s, retries failed rows up to 5x with exponential backoff, alerts admin phone on persistent failure.
- Replace every `asyncio.create_task(X)` in handlers with `await enqueue_sheet_op("X", {...})`. Drain worker does the actual call.

**Migration:** new table `sheet_sync_queue` (id, op, payload_json, attempts, last_error, status, created_at). Append to `migrate_all.py`.

#### 2. Checkout → next-month cleanup (HIGH — ghost rows)

When a tenant is checked out, their row on **next** month's tab is NOT removed. Audit flagged it.

**Fix:** In `_do_checkout` (owner_handler or record_checkout service), after marking `status=exited`:
- Call `remove_from_next_month_tab(room, tenant_name)` (new helper in `gsheets.py`).
- Delete their `RentSchedule` rows for `period_month >= checkout_month + 1`.
- Audit log entry: `field="next_month_cleanup"`, new_value=`"removed"`.

#### 3. Refund audit log (MED — compliance)

`Refund` table mutations have no `AuditLog` entry.

**Fix:** In whichever handler writes `Refund` rows, wrap the write in a helper that also writes audit. Pattern is the same as `Tenancy.notes` already has.

#### 4. Monthly rollover → cron (MED — reliability)

Currently `_monthly_tab_rollover` runs daily and self-checks "is this the 2nd-to-last day?". Brittle.

**Fix:** In `src/scheduler.py`, register the rollover as a **cron-style** APScheduler job: `CronTrigger(day='last')` running at 00:30 IST on the last day of every month. Remove the daily polling self-check.

#### 5. DB pool config (MED — crash risk under load)

Today: `create_async_engine` with defaults.

**Fix:** In `src/database/db_manager.py`:
```python
create_async_engine(
    DB_URL,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
    pool_recycle=1800,
    connect_args={"server_settings": {"application_name": "pg_accountant"}},
)
```
Test: hammer `/healthz` with 50 concurrent requests, confirm no pool exhaustion.

#### 6. Health check actually checks (MED)

`/healthz` returns `{"status": "ok"}` without checking anything.

**Fix:** `GET /healthz` does: `SELECT 1` (DB), `gspread.authorize()` (Sheets creds), Meta Graph API ping. Return 200 only if all pass; 503 with breakdown otherwise. nginx uses this for upstream health.

---

## Commit order & stop points

1. **2A** commit → stop → Kiran smoke-tests live for 1 hour → approve.
2. **2B** commit → stop → golden suite + live smoke → approve.
3. **2C** commit → stop → full manual smoke (every intent) → approve.
4. **2D** four commits (one per item 1-6). Each can ship independently.

**Do not batch.** Each commit must be individually revertible.

## Rollback plan

Each phase ships as a single commit. If post-deploy a bug appears:

```bash
ssh root@187.127.130.194 "cd /opt/pg-accountant && git revert <sha> && systemctl restart pg-accountant"
```

Pre-refactor baseline is commit `e9a3201` (Phase 1b complete, 2026-04-23 night).

## Appendix — pending-intent inventory

From grep on 2026-04-23 after Phase 1b. 47 branches in `owner_handler.py::resolve_pending_action`:

| Line | Intent |
|---|---|
| 236 | APPROVE_ONBOARDING |
| 391 | FORM_EXTRACT_CONFIRM |
| 812 | CHECKOUT_FORM_CONFIRM |
| 927 | COLLECT_DOCS |
| 1003 | COLLECT_RECEIPT |
| 1047 | CONFIRM_PAYMENT_LOG |
| 1198 | CONFIRM_PAYMENT_ALLOC |
| 1316 | CONFIRM_ADD_EXPENSE |
| 1369 | CONFIRM_FIELD_UPDATE |
| 1393 | (nested) EXIT_STAFF_WHO |
| 1411 | CONFIRM_DEPOSIT_REFUND |
| 1500 | UPDATE_CHECKOUT_DATE_ASK |
| 1518 | RECORD_CHECKOUT |
| 1730 | COLLECT_RENT_STEP |
| 2087 | LOG_EXPENSE_STEP |
| 2229 | ADD_TENANT_INCOMPLETE |
| 2234 | RENT_CHANGE |
| 2251 | ROOM_TRANSFER |
| 2348 | ROOM_TRANSFER_DW_WHO |
| 2359 | ROOM_TRANSFER_DW_DEST |
| 2367 | ROOM_TRANSFER_DW_CONFIRM |
| 2376 | ASSIGN_ROOM_STEP |
| 2521, 2573 | PAYMENT_LOG (choice resolution) |
| 2627 | UPDATE_CHECKIN |
| 2635 | UPDATE_CHECKOUT_DATE |
| 2658 | NOTICE_GIVEN |
| 2699 | RENT_CHANGE_WHO |
| 2727 | RENT_CHANGE |
| 2743 | QUERY_TENANT |
| 2750 | GET_TENANT_NOTES |
| 2760 | DUPLICATE_CONFIRM |
| 2774 | OVERPAYMENT_RESOLVE |
| 2857 | OVERPAYMENT_ADD_NOTE |
| 2879 | UNDERPAYMENT_NOTE |
| 2907 | VOID_PAYMENT |
| 2916 | VOID_WHICH |
| 2950 | VOID_EXPENSE |
| 2959 | VOID_WHO |
| 3009 | REFUND_WHO |
| 3028 | ROOM_TRANSFER_WHO |
| 3052 | ROOM_TRANSFER_DEST |
| 3065 | DEPOSIT_CHANGE_WHO |
| 3102 | DEPOSIT_CHANGE |
| 3115 | DEPOSIT_CHANGE_AMT |
| 3142 | FIELD_UPDATE_WHO |
| 3210 | CONFIRM_ADD_TENANT |
| 3317 | UPDATE_TENANT_NOTES_STEP |
| 3415 | ADD_CONTACT_STEP |
| 3590 | UPDATE_CONTACT_STEP |
