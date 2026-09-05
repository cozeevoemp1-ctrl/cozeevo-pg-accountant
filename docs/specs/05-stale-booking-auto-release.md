# Spec 05 — Stale booking auto-release

Status: **specced 2026-09-05, not implemented** — 3 decisions open (see bottom).

## Goal

A booking that is never checked into stops holding a bed. After a grace period the
tenancy is cancelled through the existing `cancel-no-show` path, the bed returns to
vacant-beds, and the row leaves the "Awaiting check-in" tile. Nothing goes stale:
that tile should never again contain something 62 days overdue.

Kiran, 2026-09-05: *"if any booking is cancelled due to inactivity or not checked in
it should show up in vacant beds, it should not get stuck in awaiting, become stale."*

## Why

Room 621 / Harshit Srivastava sat at `no_show` for 62 days. It held one bed of a double
(`room_occupancy.py:174` counts a past-dated `no_show` as occupied), so the room read
2/2 full and that bed was unsellable the whole time. Nothing swept it, and nothing
surfaced it except the tile itself. See `docs/architecture/BRAIN.md` §15b and
`scripts/_fix_harshit_621_checkin.py`.

**The hard part:** a real resident whose check-in was never recorded in the app and a
genuine no-show are *byte-identical in the DB*. Harshit had paid an advance, was living
in the room, and looked exactly like an abandoned booking. So this must not silently
hard-cancel on day N — it warns first, then releases.

## Design decisions

- **Reuse the existing path, do not duplicate it.** `cancel_no_show` in
  `src/api/v2/tenants.py:1198-1252` already does the whole job correctly: tenancy →
  `cancelled`, pending RS rows voided, linked onboarding session synced, audit_log
  written. Extract its body into `src/services/bookings.py::release_booking(session,
  tenancy_id, *, reason, actor)` and have both the endpoint and the sweep call it.
  This is the bug that caused the incident — `_cleanup_2026_08_06.py` hand-rolled a
  session update instead of using the endpoint, and left the tenancy behind.
- **Two stages, not one.** Silent auto-cancel would have deleted Harshit's real tenancy.
  - Stage 1 (`WARN_DAYS`, recommend **7**): no state change. WhatsApp the operators
    (`src/whatsapp/broadcast_report.py` `OPERATORS`) — "Room 621 · Harshit Srivastava ·
    booked for 5 Jul · not checked in after 7 days. Did he move in?" Set
    `onboarding_sessions.cancellation_reason = 'stale_warned'` so it warns once.
  - Stage 2 (`RELEASE_DAYS`, recommend **14**): call `release_booking()` with
    `reason='stale_no_checkin'`. Bed frees, tile clears.
- **No tenant messages, ever** — operators only (memory `rules_no_tenant_comms.md`).
- **Money is never touched.** A booking advance stays on the record, not voided
  (CLAUDE.md: never hard-delete financial records). Forfeit vs refund is a human call
  made later in the PWA.
- **Vacant beds needs no change.** `room_occupancy.py:62` already excludes `cancelled`,
  so releasing is sufficient — verify, don't rebuild.
- **Scheduling:** a new APScheduler job beside `_daily_reconciliation`
  (`src/scheduler.py:143`), daily 02:15 IST, `misfire_grace_time` wide enough to catch
  up after downtime.

## Implementation

1. `src/services/bookings.py` (new) — `release_booking()` lifted verbatim from
   `tenants.py:1198-1252`; `cancel_no_show` endpoint becomes a thin caller.
2. `src/scheduler.py` — `_stale_booking_sweep()` + `add_job(..., id="stale_booking_sweep")`.
   Query: `status='no_show'` AND `checkin_date < today - INTERVAL 'N days'` AND room is
   not staff and not `000`.
3. `src/api/v2/kpi.py` — the `no_show` tile list (`kpi.py:692-712`) gains a
   `days_late` badge threshold so anything past `WARN_DAYS` is visually flagged before
   the sweep acts.
4. Constants in ONE place — `WARN_DAYS` / `RELEASE_DAYS` in `src/services/bookings.py`,
   exposed via `GET /api/v2/app/config` so the PWA never hardcodes them
   (CLAUDE.md single-source rule).
5. `tests/test_stale_booking.py` — warn boundary, release boundary, idempotency
   (running twice releases once), and that a `daily` stay_type is never swept.

## Out of scope

- Refunding or voiding booking advances — record stays, human decides.
- Any message to the tenant.
- Day-wise (`stay_type='daily'`) bookings — different lifecycle, leave alone.
- Changing what "Awaiting check-in" counts (still `no_show`) — the fix is that nothing
  stale survives in it, not a new filter.
- Retroactively sweeping today's 3 overdue no-shows — all are 1–4 days old and live.

## Verification checklist

- [ ] `python tests/eval_golden.py` (bot behavior unchanged, but the suite must stay green)
- [ ] `pytest tests/test_stale_booking.py`
- [ ] Seed a `no_show` dated 20 days back → run sweep → tenancy `cancelled`, session
      synced, bed appears in vacant-beds, row gone from the tile
- [ ] Run the sweep twice — second run is a no-op, no duplicate audit rows
- [ ] audit_log row uses `field='status'` so it renders in the activity feed
      (BRAIN.md §15b — the feed filters on `field`)
- [ ] Operator WhatsApp warn fires once, not daily
- [ ] Dependency sync rule (CLAUDE.md checklist)

## Open decisions — need Kiran

1. **Grace period.** Recommend warn at 7 days, release at 14. Too short and a tenant
   arriving late loses their room; too long and the bed sits dead.
2. **Fully automatic, or warn + manual button?** Recommend automatic release at 14 days
   with the day-7 operator warning — Harshit proves the manual route doesn't get done.
   The alternative is a "Release bed" button on the tile and no auto-cancel.
3. **Booking advance on release** — confirm it stays recorded (forfeited) rather than
   being voided.
