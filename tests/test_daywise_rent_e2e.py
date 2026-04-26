"""
End-to-end test: daywise rent change yes/no confirmation flow.

Tests:
  1. "change [room] rent to [N] per day"
       → RENT_CHANGE pending saved with is_daywise=True
  2. Reply "Yes" → tenancy.agreed_rent updated, success reply returned
  3. Reply "No" → agreed_rent unchanged, pending resolved cleanly
  4. Stale pending guard — unrelated message keeps pending alive

Run: venv/Scripts/python -X utf8 tests/test_daywise_rent_e2e.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import json
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8")
from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import select, delete
from src.database.db_manager import init_db, get_session
from src.database.models import (
    PendingAction, Tenancy, StayType, TenancyStatus, Room,
)
from src.whatsapp.role_service import CallerContext, _normalize
from src.whatsapp.intent_detector import detect_intent


ADMIN_PHONE = os.getenv("TEST_ADMIN_PHONE", "+917845952289")


# ── helpers ────────────────────────────────────────────────────────────────────

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


async def _route_message(ctx: CallerContext, message: str) -> str:
    from src.whatsapp.chat_api import _get_active_pending
    from src.whatsapp.handlers.owner_handler import resolve_pending_action

    _CANCEL_WORDS = {"cancel", "stop", "abort", "quit", "nevermind", "never mind"}

    async with get_session() as s:
        pending = await _get_active_pending(ctx.phone, s)
        if pending and not pending.resolved:
            try:
                resolved_reply = await resolve_pending_action(pending, message, s)
            except Exception as e:
                print(f"  [ERROR in resolver] {e}")
                resolved_reply = None
            if resolved_reply:
                if resolved_reply.startswith("__KEEP_PENDING__"):
                    await s.commit()
                    return resolved_reply[len("__KEEP_PENDING__"):]
                pending.resolved = True
                await s.commit()
                return resolved_reply
            if message.strip().lower() in _CANCEL_WORDS:
                pending.resolved = True
                await s.commit()
                return "Cancelled."
        intent_r = detect_intent(message, ctx.role)
        entities = dict(intent_r.entities or {})
        entities.setdefault("_raw_message", message)
        from src.whatsapp.gatekeeper import route
        reply = await route(intent_r.intent, entities, ctx, message, s)
        await s.commit()
        return reply or ""


async def _get_agreed_rent(tenancy_id: int) -> Decimal:
    async with get_session() as s:
        t = await s.get(Tenancy, tenancy_id)
        return t.agreed_rent or Decimal("0")


async def _set_agreed_rent(tenancy_id: int, value: Decimal) -> None:
    async with get_session() as s:
        t = await s.get(Tenancy, tenancy_id)
        t.agreed_rent = value
        await s.commit()


# ── find a daywise tenancy ─────────────────────────────────────────────────────

async def _find_active_daywise() -> tuple[Tenancy, Room] | None:
    async with get_session() as s:
        rows = (await s.execute(
            select(Tenancy, Room)
            .join(Room, Room.id == Tenancy.room_id)
            .where(
                Tenancy.stay_type == StayType.daily,
                Tenancy.status == TenancyStatus.active,
            )
            .limit(1)
        )).all()
        if not rows:
            return None
        t, r = rows[0]
        # detach — load what we need
        return (t.id, r.room_number, t.agreed_rent or Decimal("0"))


# ── tests ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    DATABASE_URL = os.environ["DATABASE_URL"]
    if DATABASE_URL.startswith("postgresql://"):
        DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
    await init_db(DATABASE_URL)

    ctx = CallerContext(phone=ADMIN_PHONE, role="admin", name="Kiran")
    phone_norm = _normalize(ADMIN_PHONE)

    ok = fail = 0
    failures: list[str] = []

    # ── Find a daywise tenancy ─────────────────────────────────────────────────
    result = await _find_active_daywise()
    if not result:
        print("[SKIP] No active day-wise tenancy found in DB — seed one to run this test.")
        return
    tenancy_id, room_number, original_rate = result
    test_rate = 1500  # use a clearly different value
    print(f"\nUsing daywise tenancy {tenancy_id} (room {room_number}, current rate Rs.{original_rate})")

    # ── Test 1: command triggers RENT_CHANGE pending with is_daywise=True ──────
    print("\n--- Test 1: command -> RENT_CHANGE pending (is_daywise) ---")
    await _purge_pending(phone_norm)
    msg = f"change {room_number} rent to {test_rate} per day"
    reply = await _route_message(ctx, msg)
    print(f"  Reply: {reply[:120]!r}")

    pend = await _latest_pending(phone_norm)
    if pend and pend.intent == "RENT_CHANGE":
        action_data = json.loads(pend.action_data or "{}")
        if action_data.get("is_daywise"):
            print("[ OK ] RENT_CHANGE pending saved with is_daywise=True"); ok += 1
        else:
            print(f"[FAIL] pending intent=RENT_CHANGE but is_daywise missing: {action_data!r}")
            fail += 1; failures.append("Test1:is_daywise_missing")
    else:
        print(f"[FAIL] Expected RENT_CHANGE pending, got: {pend.intent if pend else None!r}")
        print(f"  Reply was: {reply!r}")
        fail += 1; failures.append("Test1:no_pending")

    # ── Test 2: "Yes" updates agreed_rent ─────────────────────────────────────
    print("\n--- Test 2: 'Yes' -> agreed_rent updated ---")
    if pend and pend.intent == "RENT_CHANGE":
        await _set_agreed_rent(tenancy_id, original_rate)  # reset first
        reply = await _route_message(ctx, "Yes")
        print(f"  Reply: {reply[:120]!r}")
        new_rate = await _get_agreed_rent(tenancy_id)
        if new_rate == Decimal(str(test_rate)):
            print("[ OK ] agreed_rent updated correctly"); ok += 1
        else:
            print(f"[FAIL] agreed_rent={new_rate!r} expected {test_rate}")
            fail += 1; failures.append("Test2:rate_not_updated")
        if "Daily rate updated" in reply or "daily rate updated" in reply.lower():
            print("[ OK ] success reply returned"); ok += 1
        else:
            print(f"[FAIL] success reply not found in: {reply!r}")
            fail += 1; failures.append("Test2:bad_reply")
    else:
        print("[SKIP] Test 2 skipped — Test 1 failed")
        fail += 1; failures.append("Test2:skipped")

    # ── Test 3: "No" cancels cleanly ──────────────────────────────────────────
    print("\n--- Test 3: 'No' -> rate unchanged, pending resolved ---")
    await _purge_pending(phone_norm)
    await _set_agreed_rent(tenancy_id, original_rate)
    reply = await _route_message(ctx, f"change {room_number} rent to {test_rate} per day")
    pend = await _latest_pending(phone_norm)
    if pend and pend.intent == "RENT_CHANGE":
        reply_no = await _route_message(ctx, "No")
        print(f"  Reply: {reply_no[:120]!r}")
        rate_after = await _get_agreed_rent(tenancy_id)
        if rate_after == original_rate:
            print("[ OK ] rate unchanged after No"); ok += 1
        else:
            print(f"[FAIL] rate changed to {rate_after} after No"); fail += 1; failures.append("Test3:rate_changed")
        pend_after = await _latest_pending(phone_norm)
        if pend_after is None:
            print("[ OK ] pending resolved after No"); ok += 1
        else:
            print(f"[FAIL] pending still alive after No: {pend_after.intent!r}")
            fail += 1; failures.append("Test3:pending_alive")
    else:
        print("[SKIP] Test 3 skipped — couldn't re-trigger RENT_CHANGE")
        fail += 1; failures.append("Test3:skipped")

    # ── Test 4: unrelated message keeps pending alive ─────────────────────────
    print("\n--- Test 4: unrelated message keeps pending alive ---")
    await _purge_pending(phone_norm)
    await _set_agreed_rent(tenancy_id, original_rate)
    await _route_message(ctx, f"change {room_number} rent to {test_rate} per day")
    pend = await _latest_pending(phone_norm)
    if pend and pend.intent == "RENT_CHANGE":
        reply_unrel = await _route_message(ctx, "hello how are you")
        print(f"  Reply: {reply_unrel[:120]!r}")
        pend_after = await _latest_pending(phone_norm)
        if pend_after and not pend_after.resolved:
            print("[ OK ] pending still alive after unrelated message"); ok += 1
        else:
            print("[FAIL] pending was killed by unrelated message")
            fail += 1; failures.append("Test4:pending_killed")
    else:
        print("[SKIP] Test 4 skipped"); fail += 1; failures.append("Test4:skipped")

    # ── cleanup ────────────────────────────────────────────────────────────────
    await _purge_pending(phone_norm)
    await _set_agreed_rent(tenancy_id, original_rate)

    # ── summary ────────────────────────────────────────────────────────────────
    print(f"\n{'='*50}")
    print(f"DAYWISE RENT CHANGE E2E: {ok} passed, {fail} failed")
    if failures:
        print(f"FAILURES: {failures}")
    sys.exit(0 if fail == 0 else 1)


if __name__ == "__main__":
    asyncio.run(main())
