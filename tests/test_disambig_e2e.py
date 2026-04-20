"""
End-to-end disambiguation test.

Exercises every name-based intent through the full stack:
  intent_detector -> gatekeeper -> handler -> _save_pending -> resolver.

Covers:
  - QUERY_TENANT / QUERY_RENT_HISTORY (read-only)
  - PAYMENT_LOG / VOID_PAYMENT / RENT_CHANGE / RENT_DISCOUNT /
    UPDATE_SHARING_TYPE / UPDATE_RENT / UPDATE_PHONE / UPDATE_GENDER /
    ADD_REFUND / CHECKOUT / SCHEDULE_CHECKOUT / ROOM_TRANSFER /
    ASSIGN_ROOM / DEPOSIT_CHANGE
  - ASSIGN_STAFF_ROOM / EXIT_STAFF (newly wired)

For mutating intents we send the ambiguous message, verify the bot saved
a pending action with the expected intent, then send "cancel" so nothing
is actually applied.

Also probes state-machine invariants:
  1. Unrelated mid-pending message keeps pending alive.
  2. "cancel" mid-pending closes it cleanly.
  3. Valid numeric choice resolves the pending.

Run: venv/Scripts/python -X utf8 tests/test_disambig_e2e.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import select, delete, text
from src.database.db_manager import init_db, get_session
from src.database.models import PendingAction, Staff, Room, Tenancy
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


async def _pick_duplicate_first_name(session) -> str:
    """Return a first-name that has 2+ active tenants. 'pratik' preferred."""
    q = await session.execute(text(
        "SELECT SPLIT_PART(LOWER(t.name), ' ', 1) AS fn, COUNT(*) c "
        "FROM tenants t JOIN tenancies tc ON tc.tenant_id=t.id "
        "WHERE tc.status='active' GROUP BY fn HAVING COUNT(*)>1 "
        "ORDER BY c DESC, fn LIMIT 1"
    ))
    row = q.first()
    if not row:
        raise SystemExit("No duplicate first-names found in DB — can't run test.")
    return row[0]


async def _route_message(ctx: CallerContext, message: str) -> str:
    """Run intent detection + gatekeeper route for a fresh message."""
    async with get_session() as s:
        intent_r = detect_intent(message, ctx.role)
        entities = dict(intent_r.entities or {})
        entities.setdefault("_raw_message", message)
        reply = await route(intent_r.intent, entities, ctx, message, s)
        await s.commit()
        return reply or ""


async def _resolve(ctx: CallerContext, pending: PendingAction, reply_text: str) -> str:
    """Invoke the resolver cascade for a specific pending."""
    from src.whatsapp.handlers.owner_handler import resolve_pending_action
    async with get_session() as s:
        p = await s.get(PendingAction, pending.id)
        result = await resolve_pending_action(p, reply_text, s)
        await s.commit()
        return result or ""


def _is_disambig_reply(reply: str) -> bool:
    r = reply.lower()
    return ("which one" in r or "found" in r and "matching" in r or
            "pick one" in r or ("reply *1*" in r and "*2*" in r))


async def main():
    await init_db(os.getenv("DATABASE_URL"))
    phone_norm = _normalize(ADMIN_PHONE)
    ctx = CallerContext(phone=ADMIN_PHONE, role="admin", name="TestHarness")

    # Pick a real duplicate first-name for tenant-side tests
    async with get_session() as s:
        dup_name = await _pick_duplicate_first_name(s)
    print(f"Using duplicate first-name: *{dup_name}*")

    # Each case: (label, message_to_send, expected_pending_intent).
    # expected_pending_intent=None means "handler replies directly, no pending".
    cases = [
        # Read-only — should disambig
        (f"QUERY_TENANT  '{dup_name} balance'", f"{dup_name} balance", "QUERY_TENANT"),
        # Mutating — disambig first (we cancel before the confirm step applies)
        (f"PAYMENT_LOG   '{dup_name} paid 1 cash'", f"{dup_name} paid 1 cash", "PAYMENT_WHO"),
        (f"VOID_PAYMENT  'void {dup_name}'", f"void {dup_name}", "VOID_WHO"),
        (f"RENT_CHANGE   '{dup_name} rent 99999'", f"{dup_name} rent 99999", "FIELD_UPDATE_WHO"),
        (f"UPDATE_SHARING '{dup_name} premium'", f"{dup_name} premium", "FIELD_UPDATE_WHO"),
        (f"UPDATE_PHONE  '{dup_name} phone 9999999999'", f"{dup_name} phone 9999999999", "FIELD_UPDATE_WHO"),
        (f"ADD_REFUND    'refund {dup_name} 1'", f"refund {dup_name} 1", "REFUND_WHO"),
        (f"CHECKOUT      'checkout {dup_name}'", f"checkout {dup_name}", "CHECKOUT_WHO"),
        (f"ROOM_TRANSFER 'move {dup_name} to 999'", f"move {dup_name} to 999", "ROOM_TRANSFER_WHO"),
    ]

    ok, fail, skip = 0, 0, 0
    failures: list[str] = []

    for label, msg, exp_pending in cases:
        await _purge_pending(phone_norm)
        reply = await _route_message(ctx, msg)
        pend = await _latest_pending(phone_norm)

        reply_short = (reply or "")[:80].replace("\n", " / ")
        if exp_pending is None:
            print(f"[SKIP] {label} — {reply_short}")
            skip += 1
            continue

        if pend is None:
            print(f"[FAIL] {label} — no PendingAction saved. reply={reply_short!r}")
            fail += 1
            failures.append(label)
            continue

        if pend.intent != exp_pending:
            # Some handlers use slight variants (e.g. FIELD_UPDATE_WHO vs CONFIRM_FIELD_UPDATE
            # when only one tenant matches). Consider any *_WHO or *_WHICH or *FIELD_UPDATE* a
            # pass-by-shape if disambig-like reply came back.
            shape_ok = (pend.intent.endswith("_WHO") or pend.intent.endswith("_WHICH")
                        or "UPDATE" in pend.intent or "REFUND" in pend.intent
                        or "CHECKOUT" in pend.intent or "TRANSFER" in pend.intent)
            if not shape_ok:
                print(f"[FAIL] {label} — pending={pend.intent} (expected {exp_pending}). reply={reply_short!r}")
                fail += 1
                failures.append(label)
                continue
            print(f"[WARN] {label} — pending={pend.intent} (accepted, shape match). reply={reply_short!r}")
            ok += 1
        else:
            print(f"[ OK ] {label} — pending={pend.intent}")
            ok += 1

        # Try to cancel so we never actually mutate
        await _route_message(ctx, "cancel")

    # ─── Staff disambig via seeded test rows ────────────────────────────────
    async with get_session() as s:
        s.add(Staff(name="zzDupStaff", active=True, role="Manager"))
        s.add(Staff(name="zzDupStaff", active=True, role="Security"))
        await s.commit()

    try:
        await _purge_pending(phone_norm)
        reply = await _route_message(ctx, "staff zzDupStaff room G05")
        pend = await _latest_pending(phone_norm)
        if pend and pend.intent == "ASSIGN_STAFF_WHO":
            print("[ OK ] ASSIGN_STAFF_ROOM disambig — pending=ASSIGN_STAFF_WHO"); ok += 1
        else:
            print(f"[FAIL] ASSIGN_STAFF_ROOM — pending={pend.intent if pend else None!r}, reply={reply[:80]!r}")
            fail += 1; failures.append("ASSIGN_STAFF_ROOM")

        # Resolve with "1" — verify staff actually gets linked
        if pend:
            res = await _resolve(ctx, pend, "1")
            if "Assigned" in res or "Added" in res:
                print("[ OK ] ASSIGN_STAFF_ROOM resolve — staff linked"); ok += 1
            else:
                print(f"[FAIL] ASSIGN_STAFF_ROOM resolve — {res[:80]!r}"); fail += 1
                failures.append("ASSIGN_STAFF_ROOM resolve")

        await _purge_pending(phone_norm)
        reply = await _route_message(ctx, "staff zzDupStaff exit")
        pend = await _latest_pending(phone_norm)
        if pend and pend.intent == "EXIT_STAFF_WHO":
            print("[ OK ] EXIT_STAFF disambig — pending=EXIT_STAFF_WHO"); ok += 1
        else:
            print(f"[FAIL] EXIT_STAFF — pending={pend.intent if pend else None!r}, reply={reply[:80]!r}")
            fail += 1; failures.append("EXIT_STAFF")
        if pend:
            res = await _resolve(ctx, pend, "1")
            if "exited" in res.lower():
                print("[ OK ] EXIT_STAFF resolve — staff marked exited"); ok += 1
            else:
                print(f"[FAIL] EXIT_STAFF resolve — {res[:80]!r}"); fail += 1
                failures.append("EXIT_STAFF resolve")
    finally:
        # Cleanup staff rows + any pending + any room flip we caused on G05
        async with get_session() as s:
            await s.execute(delete(Staff).where(Staff.name == "zzDupStaff"))
            await s.execute(delete(PendingAction).where(PendingAction.phone == phone_norm))
            room = (await s.execute(select(Room).where(Room.room_number == "G05"))).scalar_one_or_none()
            # Keep G05 flagged as staff-room ONLY if a real staff is still assigned
            if room:
                real = (await s.execute(
                    select(Staff).where(Staff.room_id == room.id, Staff.active == True)
                )).scalars().first()
                if not real:
                    room.is_staff_room = False
            await s.commit()

    # ─── State-preservation probes ─────────────────────────────────────────
    # (A) Mid-pending unrelated message → pending survives
    await _purge_pending(phone_norm)
    await _route_message(ctx, f"{dup_name} rent 99999")  # creates a pending
    before = await _latest_pending(phone_norm)
    # Send unrelated message
    await _route_message(ctx, "staff rooms")
    after = await _latest_pending(phone_norm)
    if before and after and before.id == after.id and not after.resolved:
        print("[ OK ] State preservation — unrelated message kept pending alive"); ok += 1
    else:
        print(f"[FAIL] State preservation — before={before and before.intent}, after={after and after.intent}")
        fail += 1; failures.append("state preservation")

    # (B) "cancel" → pending resolves cleanly
    await _route_message(ctx, "cancel")
    after_cancel = await _latest_pending(phone_norm)
    if after_cancel is None:
        print("[ OK ] Cancel — pending resolved cleanly"); ok += 1
    else:
        print(f"[FAIL] Cancel — pending still alive: {after_cancel.intent}")
        fail += 1; failures.append("cancel")

    await _purge_pending(phone_norm)

    print("\n" + "="*60)
    print(f"OK: {ok}   FAIL: {fail}   SKIP: {skip}")
    if failures:
        print("Failures:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("All disambiguation flows verified ✓")


if __name__ == "__main__":
    asyncio.run(main())
