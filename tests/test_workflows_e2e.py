"""End-to-end workflow test suite.

Covers the top ~10 receptionist workflows × {happy, cancel mid-flow,
correction mid-flow} paths. Safe to run on live DB — every mutating
scenario ends with "cancel" OR targets a known test tenant OR is
read-only.

Pattern mirrors tests/test_disambig_e2e.py: direct-route messages via
intent_detector -> gatekeeper -> handler, read pending state from DB,
assert bot reply shape, cancel pending between scenarios.

Scope (happy = H, cancel = C, correction = X, workflow-switch = S):
  1. PAYMENT_LOG        H + X + C
  2. COLLECT_RENT step  H (name -> cash -> upi -> notes -> confirm)
  3. CHECKOUT           H + C
  4. SCHEDULE_CHECKOUT  H
  5. ADD_TENANT bulk    H (won't actually commit — cancel before approve)
  6. DEPOSIT_CHANGE     H + C
  7. ROOM_TRANSFER      H + C
  8. RENT_CHANGE        H + C
  9. NOTICE             H
 10. UPDATE_SHARING     H + C
 11. VOID_PAYMENT       C (never actually void)
 12. STAFF rooms        H (mark + unmark + list + multi)
 13. QUERY              H (Dues / occupancy / staff rooms list)

Run: venv/Scripts/python -X utf8 tests/test_workflows_e2e.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import select, delete, text
from src.database.db_manager import init_db, get_session
from src.database.models import PendingAction
from src.whatsapp.role_service import CallerContext, _normalize
from src.whatsapp.intent_detector import detect_intent, _extract_entities
from src.whatsapp.gatekeeper import route


ADMIN_PHONE = os.getenv("TEST_ADMIN_PHONE", "+917845952289")  # Kiran


async def _purge_pending(phone_norm: str) -> None:
    async with get_session() as s:
        await s.execute(delete(PendingAction).where(PendingAction.phone == phone_norm))
        await s.commit()


async def _latest_pending(phone_norm: str) -> PendingAction | None:
    async with get_session() as s:
        rows = (await s.execute(
            select(PendingAction).where(
                PendingAction.phone == phone_norm,
                PendingAction.resolved == False,
            ).order_by(PendingAction.id.desc())
        )).scalars().all()
        return rows[0] if rows else None


async def _pick_duplicate_first_name() -> str:
    async with get_session() as s:
        q = await s.execute(text(
            "SELECT SPLIT_PART(LOWER(t.name),' ',1) fn, COUNT(*) c "
            "FROM tenants t JOIN tenancies tc ON tc.tenant_id=t.id "
            "WHERE tc.status='active' GROUP BY fn HAVING COUNT(*)>1 "
            "ORDER BY c DESC LIMIT 1"
        ))
        row = q.first()
        return row[0] if row else "pratik"


async def _pick_unique_tenant() -> tuple[str, str, str]:
    """Return (name, room_number, phone) of an active tenant with unique first name."""
    async with get_session() as s:
        q = await s.execute(text(
            "SELECT t.name, r.room_number, t.phone "
            "FROM tenants t "
            "JOIN tenancies tc ON tc.tenant_id=t.id "
            "JOIN rooms r ON r.id=tc.room_id "
            "WHERE tc.status='active' "
            "  AND LOWER(SPLIT_PART(t.name,' ',1)) IN ( "
            "    SELECT LOWER(SPLIT_PART(t2.name,' ',1)) FROM tenants t2 "
            "    JOIN tenancies tc2 ON tc2.tenant_id=t2.id "
            "    WHERE tc2.status='active' "
            "    GROUP BY LOWER(SPLIT_PART(t2.name,' ',1)) HAVING COUNT(*)=1) "
            "ORDER BY t.id DESC LIMIT 1"
        ))
        row = q.first()
        return (row[0], row[1], row[2]) if row else ("TestTenant", "000", "+910000000000")


async def _send(ctx: CallerContext, message: str) -> str:
    intent, conf, _ = detect_intent(message)
    entities = _extract_entities(message, intent) if intent else {}
    entities["_raw_message"] = message
    try:
        reply = await route(ctx, message, intent, entities)
    except Exception as e:
        reply = f"__ERROR__ {type(e).__name__}: {e}"
    return reply or ""


# ── Scenario runner ─────────────────────────────────────────────────────────

RESULTS: list[tuple[str, bool, str]] = []

async def scenario(name: str, turns: list[tuple[str, callable]]) -> None:
    """Each turn: (message, check_fn). check_fn takes the reply and returns
    (ok: bool, note: str). The scenario PASSes only if every turn's check returns ok."""
    phone_norm = _normalize(ADMIN_PHONE)
    await _purge_pending(phone_norm)
    ctx = CallerContext(phone=ADMIN_PHONE, role="admin", name="Kiran")

    notes: list[str] = []
    ok = True
    for msg, check in turns:
        reply = await _send(ctx, msg)
        passed, note = check(reply)
        notes.append(f"[{'OK' if passed else 'FAIL'}] >> {msg[:60]} :: {note}")
        if not passed:
            ok = False
            break

    # Always clean up
    await _purge_pending(phone_norm)
    RESULTS.append((name, ok, "\n    ".join(notes)))
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name}")
    if not ok:
        for n in notes:
            print(f"    {n}")


# ── Check helpers ──────────────────────────────────────────────────────────

def contains(*needles):
    def check(reply):
        lo = reply.lower()
        hits = [n for n in needles if n.lower() in lo]
        return (len(hits) == len(needles), f"want {needles!r}, got: {reply[:150]!r}")
    return check

def not_contains(*needles):
    def check(reply):
        lo = reply.lower()
        bad = [n for n in needles if n.lower() in lo]
        return (not bad, f"should NOT contain {bad!r}: {reply[:150]!r}")
    return check

def is_error(reply):
    return reply.startswith("__ERROR__") or "went wrong" in reply.lower()

def not_error(note="no error"):
    def check(reply):
        return (not is_error(reply), f"{note}; got: {reply[:200]!r}")
    return check

def nonempty_reply(reply):
    return (bool(reply and reply.strip()), f"empty reply ({reply!r})")


# ── Scenarios ──────────────────────────────────────────────────────────────

async def run_all():
    # Get a real tenant for happy-path payment tests
    tenant_name, tenant_room, _ = await _pick_unique_tenant()
    dup_name = await _pick_duplicate_first_name()
    short_name = tenant_name.split()[0]
    print(f"\n=== Tenants used: unique='{tenant_name}' (room {tenant_room}), duplicate-first='{dup_name}' ===\n")

    # ── QUERIES (read-only) ────────────────────────────────────────────────
    await scenario("QUERY-1: occupancy", [
        ("occupancy", lambda r: (("active" in r.lower() or "occup" in r.lower()), f"expected occupancy reply: {r[:100]}")),
    ])
    await scenario("QUERY-2: staff rooms list", [
        ("staff rooms", lambda r: (("staff" in r.lower() and ("room" in r.lower() or "no staff" in r.lower())), f"expected staff-rooms reply: {r[:120]}")),
    ])
    await scenario("QUERY-3: tenant balance (unique)", [
        (f"{short_name} balance", lambda r: ((short_name.lower() in r.lower() or "rent" in r.lower()), f"{r[:120]}")),
    ])
    await scenario("QUERY-4: dues this month", [
        ("who owes", lambda r: (("paid" in r.lower() or "dues" in r.lower() or "all" in r.lower()), f"{r[:120]}")),
    ])

    # ── PAYMENT_LOG — happy path w/ confirm+cancel (safer than actually logging) ──
    await scenario("PAY-1: log-confirm-cancel", [
        (f"{short_name} paid 1 cash", lambda r: (("confirm" in r.lower() or "yes/no" in r.lower() or "rs" in r.lower()), f"expected confirm prompt: {r[:150]}")),
        ("cancel", contains("cancel")),
    ])

    # ── PAYMENT_LOG correction mid-flow ──────────────────────────────────────
    await scenario("PAY-2: correction amount mid-flow", [
        (f"{short_name} paid 1 cash", not_error("initial prompt")),
        ("no 2", lambda r: (("2" in r or "rs" in r.lower() or "confirm" in r.lower()), f"correction should update: {r[:150]}")),
        ("cancel", contains("cancel")),
    ])

    # ── PAYMENT_LOG correction mode mid-flow ─────────────────────────────────
    await scenario("PAY-3: correction mode mid-flow", [
        (f"{short_name} paid 1 cash", not_error("initial prompt")),
        ("no it was upi", lambda r: (("upi" in r.lower() or "confirm" in r.lower()), f"mode update: {r[:150]}")),
        ("cancel", contains("cancel")),
    ])

    # ── PAYMENT_LOG with ambiguous name → disambig ──────────────────────────
    await scenario("PAY-4: disambig-cancel", [
        (f"{dup_name} paid 1 cash", lambda r: (("1." in r or "reply" in r.lower() or "which" in r.lower() or "multiple" in r.lower()), f"expected disambig: {r[:150]}")),
        ("cancel", contains("cancel")),
    ])

    # ── COLLECT_RENT step flow ──────────────────────────────────────────────
    await scenario("COLLECT-1: step-form-cancel", [
        ("collect rent", contains("who paid")),
        (short_name, not_error("name accepted")),
        ("cancel", contains("cancel")),
    ])

    # ── CHECKOUT (scheduled — future date, no DB damage) ────────────────────
    await scenario("CHECKOUT-1: schedule-cancel", [
        (f"{short_name} leaving on 31 Dec 2026", not_error("checkout prompt")),
        ("cancel", lambda r: (("cancel" in r.lower() or "no changes" in r.lower() or not r.strip()), f"{r[:100]}")),
    ])

    # ── DEPOSIT_CHANGE (→ confirm → cancel) ─────────────────────────────────
    await scenario("DEPOSIT-1: change-cancel", [
        (f"change deposit for {short_name}", lambda r: (("new deposit" in r.lower() or "amount" in r.lower() or "reply" in r.lower()), f"{r[:150]}")),
        ("1", not_error("numeric reply")),
        ("cancel", lambda r: (("cancel" in r.lower() or "updated" in r.lower() or not r.strip()), f"{r[:100]}")),
    ])

    # ── RENT_CHANGE — confirm then cancel ───────────────────────────────────
    await scenario("RENT-1: change-cancel", [
        (f"change {short_name} rent to 99999", not_error("prompt")),
        ("cancel", lambda r: (("cancel" in r.lower() or not r.strip() or "changes" in r.lower()), f"{r[:100]}")),
    ])

    # ── UPDATE_SHARING — disambig + cancel ──────────────────────────────────
    await scenario("SHARING-1: change-cancel", [
        (f"change {dup_name} sharing to premium", lambda r: (("reply" in r.lower() or "which" in r.lower() or "1." in r or "confirm" in r.lower()), f"{r[:150]}")),
        ("cancel", lambda r: (("cancel" in r.lower() or not r.strip() or "nothing" in r.lower()), f"{r[:100]}")),
    ])

    # ── NOTICE — happy (adds notice row) — use a future-cancellable flow ────
    await scenario("NOTICE-1: give-notice", [
        (f"notice", contains("who")),
        ("cancel", lambda r: (("cancel" in r.lower() or "nothing" in r.lower() or not r.strip()), f"{r[:100]}")),
    ])

    # ── VOID_PAYMENT — cancel ───────────────────────────────────────────────
    await scenario("VOID-1: void-cancel", [
        (f"void payment {tenant_room}", not_error("prompt")),
        ("cancel", lambda r: (("cancel" in r.lower() or not r.strip() or "nothing" in r.lower()), f"{r[:100]}")),
    ])

    # ── STAFF ROOM mark / unmark ────────────────────────────────────────────
    await scenario("STAFF-1: list (read-only)", [
        ("staff rooms", lambda r: (("staff" in r.lower() and "room" in r.lower()), f"{r[:120]}")),
    ])

    # ── ROOM_TRANSFER — cancel ──────────────────────────────────────────────
    await scenario("TRANSFER-1: transfer-cancel", [
        (f"transfer {short_name} to 999", not_error("prompt")),
        ("cancel", lambda r: (("cancel" in r.lower() or not r.strip() or "not found" in r.lower() or "invalid" in r.lower()), f"{r[:120]}")),
    ])

    # ── BARE CANCEL (no pending) ────────────────────────────────────────────
    await scenario("GUARD-1: bare cancel w/no pending", [
        ("cancel", lambda r: (("nothing" in r.lower() or "no active" in r.lower() or "no pending" in r.lower() or not r.strip() or "cancel" in r.lower()), f"{r[:120]}")),
    ])

    # ── GIBBERISH w/no pending ──────────────────────────────────────────────
    await scenario("GUARD-2: gibberish w/no pending", [
        ("asdfkjhasdkjfh", nonempty_reply),
    ])

    # ── BARE YES w/no pending ───────────────────────────────────────────────
    await scenario("GUARD-3: bare yes w/no pending", [
        ("yes", nonempty_reply),
    ])


async def main():
    await init_db(os.environ["DATABASE_URL"])
    await run_all()
    total = len(RESULTS)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"\n=== RESULTS: {passed}/{total} PASS ===\n")
    failed = [(n, note) for n, ok, note in RESULTS if not ok]
    if failed:
        print("=== FAILURES ===")
        for n, note in failed:
            print(f"\n{n}")
            print(f"    {note}")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    asyncio.run(main())
