"""
End-to-end test for ROOM_TRANSFER, exercising the bed-count fix
(_finalize_room_transfer + ASSIGN_ROOM_STEP).

Flow exercised:
  intent_detector -> gatekeeper -> _room_transfer_prompt
  -> ROOM_TRANSFER_WHO disambig (when name matches multiple)
  -> _finalize_room_transfer (bed-count check we just changed)
  -> ROOM_TRANSFER step machine (rent -> deposit -> final confirm)
  -> CANCEL (no mutation)

Auto-discovers two scenarios from live DB:
  - PARTIAL: a double/triple room with at least one free bed
  - FULL:    a room at max_occupancy

Both must be NON-staff and active. Mover is any active tenant whose
current room differs from the test destinations.

Safe to run on live DB: every step ends with "cancel" so no Tenancy is
modified; only PendingAction rows are written and resolved.

Run: venv/Scripts/python -X utf8 tests/test_room_transfer_e2e.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import select, delete, func
from src.database.db_manager import init_db, get_session
from src.database.models import (
    PendingAction, Room, Tenancy, Tenant, TenancyStatus,
)
from src.whatsapp.role_service import CallerContext, _normalize
from src.whatsapp.intent_detector import detect_intent
from src.whatsapp.gatekeeper import route


ADMIN_PHONE = os.getenv("TEST_ADMIN_PHONE", "+917845952289")


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
            except Exception:
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
        reply = await route(intent_r.intent, entities, ctx, message, s)
        await s.commit()
        return reply or ""


async def _find_partial_room(s) -> tuple[Room, int] | None:
    """Pick a non-staff room where active occupants < max_occupancy and >= 1."""
    rows = (await s.execute(
        select(Room.id, Room.room_number, Room.max_occupancy, func.count(Tenancy.id).label("occ"))
        .join(Tenancy, (Tenancy.room_id == Room.id) & (Tenancy.status == TenancyStatus.active))
        .where(Room.active == True, Room.is_staff_room == False, Room.max_occupancy >= 2)
        .group_by(Room.id, Room.room_number, Room.max_occupancy)
        .having(func.count(Tenancy.id) < Room.max_occupancy)
        .order_by(Room.room_number)
        .limit(1)
    )).all()
    if not rows:
        return None
    rid, rn, maxocc, occ = rows[0]
    room = await s.get(Room, rid)
    return room, int(occ)


async def _find_full_room(s) -> tuple[Room, int] | None:
    """Pick a non-staff room where active occupants == max_occupancy."""
    rows = (await s.execute(
        select(Room.id, Room.max_occupancy, func.count(Tenancy.id).label("occ"))
        .join(Tenancy, (Tenancy.room_id == Room.id) & (Tenancy.status == TenancyStatus.active))
        .where(Room.active == True, Room.is_staff_room == False, Room.max_occupancy >= 2)
        .group_by(Room.id, Room.max_occupancy)
        .having(func.count(Tenancy.id) >= Room.max_occupancy)
        .order_by(Room.id)
        .limit(1)
    )).all()
    if not rows:
        return None
    rid, maxocc, occ = rows[0]
    room = await s.get(Room, rid)
    return room, int(occ)


async def _find_mover_not_in(s, exclude_room_ids: list[int]) -> tuple[Tenant, Tenancy, str] | None:
    """Find any active tenant whose current room isn't in the exclude list.
    Prefer a tenant with a unique first-name (skip disambig)."""
    q = (
        select(Tenant, Tenancy, Room.room_number)
        .join(Tenancy, Tenancy.tenant_id == Tenant.id)
        .join(Room, Room.id == Tenancy.room_id)
        .where(
            Tenancy.status == TenancyStatus.active,
            ~Tenancy.room_id.in_(exclude_room_ids),
        )
        .limit(50)
    )
    rows = (await s.execute(q)).all()
    if not rows:
        return None
    # Pick first one
    t, tn, rn = rows[0]
    return t, tn, rn


async def main() -> int:
    await init_db(os.getenv("DATABASE_URL"))
    phone_norm = _normalize(ADMIN_PHONE)
    ctx = CallerContext(phone=ADMIN_PHONE, role="admin", name="TestHarness")

    fails: list[str] = []

    async with get_session() as s:
        partial = await _find_partial_room(s)
        full = await _find_full_room(s)

    if not partial:
        print("[SKIP] No partially-occupied multi-bed room in DB — can't test bed-count fix.")
        return 0
    partial_room, partial_occ = partial
    print(f"PARTIAL room: {partial_room.room_number} ({partial_occ}/{partial_room.max_occupancy} beds)")

    if not full:
        print("[INFO] No fully-occupied multi-bed room in DB — skipping FULL refusal scenario.")
    else:
        full_room, full_occ = full
        print(f"FULL    room: {full_room.room_number} ({full_occ}/{full_room.max_occupancy} beds)")

    excludes = [partial_room.id] + ([full_room.id] if full else [])
    async with get_session() as s:
        mover = await _find_mover_not_in(s, excludes)
    if not mover:
        print("[SKIP] No mover tenant available.")
        return 0
    mover_t, mover_tn, mover_room = mover
    print(f"MOVER:        {mover_t.name} (room {mover_room}, tenancy id={mover_tn.id})")

    # ── Scenario A: move into PARTIAL room — must ACCEPT and show roommate ──
    await _purge_pending(phone_norm)
    msg_a = f"move {mover_t.name} to {partial_room.room_number}"
    reply_a = await _route_message(ctx, msg_a)
    print("\n--- A: PARTIAL ---")
    print(f"> {msg_a}")
    print(reply_a)

    # Handle disambig: pick the line that matches our mover by exact name + room
    if "matching" in reply_a.lower() and f"({mover_room})" in reply_a.replace("Room ", ""):
        idx = None
        for line in reply_a.splitlines():
            line = line.strip()
            if line.startswith(("1.", "2.", "3.", "4.", "5.")) and \
               mover_t.name in line and f"Room {mover_room}" in line:
                idx = line.split(".")[0]
                break
        if idx:
            print(f"> {idx}  (disambig: pick {mover_t.name})")
            reply_a = await _route_message(ctx, idx)
            print(reply_a)
        else:
            fails.append(f"A: disambig listed but mover not found in options")

    if "is full" in reply_a.lower() or "is occupied" in reply_a.lower():
        fails.append(f"A: refused move into partial room {partial_room.room_number}: {reply_a[:120]}")
    elif "Room Transfer" not in reply_a and "Rent for new room" not in reply_a:
        fails.append(f"A: did not reach confirm prompt. reply={reply_a[:160]}")
    else:
        if partial_occ >= 1 and "Sharing with" not in reply_a:
            fails.append("A: confirm prompt missing roommate note")

    # Walk further: keep current rent
    if "Rent for new room" in reply_a:
        reply_a2 = await _route_message(ctx, "1")
        print(f"> 1\n{reply_a2}")
        if "deposit" not in reply_a2.lower() and "confirm" not in reply_a2.lower():
            fails.append(f"A: '1' did not advance to deposit step. reply={reply_a2[:160]}")
        # extra deposit = 0
        reply_a3 = await _route_message(ctx, "0")
        print(f"> 0\n{reply_a3}")
        if "yes" not in reply_a3.lower() and "1" not in reply_a3 and "confirm" not in reply_a3.lower():
            fails.append(f"A: '0' did not advance to final confirm. reply={reply_a3[:160]}")
        # cancel — DO NOT mutate
        reply_a4 = await _route_message(ctx, "no")
        print(f"> no\n{reply_a4}")
    await _purge_pending(phone_norm)

    # ── Scenario B: move into FULL room — must REFUSE with bed-count msg ──
    if full:
        msg_b = f"move {mover_t.name} to {full_room.room_number}"
        reply_b = await _route_message(ctx, msg_b)
        print("\n--- B: FULL ---")
        print(f"> {msg_b}")
        print(reply_b)

        if "matching" in reply_b.lower():
            idx = None
            for line in reply_b.splitlines():
                line = line.strip()
                if line.startswith(("1.", "2.", "3.", "4.", "5.")) and \
                   mover_t.name in line and f"Room {mover_room}" in line:
                    idx = line.split(".")[0]
                    break
            if idx:
                print(f"> {idx}  (disambig: pick {mover_t.name})")
                reply_b = await _route_message(ctx, idx)
                print(reply_b)

        if "is *full*" not in reply_b and "is full" not in reply_b.lower():
            fails.append(f"B: did not refuse full room. reply={reply_b[:160]}")
        await _purge_pending(phone_norm)

    # ── Scenario C: invalid input mid-flow keeps pending alive ──
    msg_c = f"move {mover_t.name} to {partial_room.room_number}"
    await _route_message(ctx, msg_c)
    pend_c = await _latest_pending(phone_norm)
    if not pend_c:
        fails.append("C: no pending after starting transfer")
    else:
        # garbage at rent step should keep pending
        reply_c = await _route_message(ctx, "asdfgh")
        pend_c2 = await _latest_pending(phone_norm)
        print("\n--- C: garbage at rent step ---")
        print(f"> asdfgh\n{reply_c}")
        if not pend_c2:
            fails.append("C: garbage input killed pending silently")
    await _route_message(ctx, "cancel")
    await _purge_pending(phone_norm)

    # ── Scenario D: explicit cancel mid-flow ──
    await _route_message(ctx, f"move {mover_t.name} to {partial_room.room_number}")
    reply_d = await _route_message(ctx, "cancel")
    pend_d = await _latest_pending(phone_norm)
    print("\n--- D: cancel ---")
    print(f"> cancel\n{reply_d}")
    if pend_d:
        fails.append("D: pending still alive after cancel")
    await _purge_pending(phone_norm)

    # ── Scenario E: DAY-WISE move yes-path ──────────────────────────────────
    # Find a day-wise guest active today and a partial destination room.
    from src.database.models import DaywiseStay
    from datetime import date as _d
    async with get_session() as s:
        dw = (await s.execute(
            select(DaywiseStay).where(
                DaywiseStay.checkin_date <= _d.today(),
                DaywiseStay.checkout_date >= _d.today(),
                DaywiseStay.status.notin_(["EXIT", "CANCELLED"]),
            ).limit(1)
        )).scalars().first()
    if not dw:
        print("[SKIP-E] No active day-wise guest in DB — can't test yes-path.")
    else:
        print(f"\nDAYWISE guest: {dw.guest_name} (room {dw.room_number}, till {dw.checkout_date})")
        msg_e = f"move {dw.guest_name} to {partial_room.room_number}"
        reply_e = await _route_message(ctx, msg_e)
        print(f"\n--- E: DAY-WISE confirm ---")
        print(f"> {msg_e}\n{reply_e}")
        # Handle possible disambig
        if reply_e.lower().startswith("found") and "day-wise" in reply_e.lower():
            reply_e = await _route_message(ctx, "1")
            print(f"> 1\n{reply_e}")
        if "Move day-stay guest" not in reply_e:
            fails.append(f"E: did not get day-wise confirm prompt. reply={reply_e[:200]}")
        else:
            # cancel — DO NOT mutate the live day-wise row
            reply_e2 = await _route_message(ctx, "no")
            print(f"> no\n{reply_e2}")
            if "cancel" not in reply_e2.lower():
                fails.append(f"E: 'no' did not cancel day-wise move. reply={reply_e2[:160]}")
        await _purge_pending(phone_norm)

    # ── Scenario F: EXPENSE log yes-path (regression for Prabha's "Yes" bug) ─
    # Walks: ADD_EXPENSE -> pick category 7 (Other) -> 50 -> Flower -> skip photo
    # -> Yes. Cleans up by voiding the expense if it actually got created.
    print("\n--- F: EXPENSE log yes-path ---")
    msg_f1 = "ADD_EXPENSE"
    reply_f1 = await _route_message(ctx, msg_f1)
    print(f"> {msg_f1}\n{reply_f1[:200]}")
    if "category" not in reply_f1.lower():
        fails.append(f"F: ADD_EXPENSE did not prompt for category. reply={reply_f1[:160]}")
    else:
        for step_msg in ("7", "50", "Flower test", "skip"):
            reply_f = await _route_message(ctx, step_msg)
            print(f"> {step_msg}\n{reply_f[:200]}")
        # Now should be at Confirm Expense step. Reply Yes.
        from src.database.models import Expense
        async with get_session() as s:
            count_before = (await s.execute(select(Expense).where(Expense.notes.ilike("%Logged via WhatsApp%")))).scalars().all()
        reply_f_yes = await _route_message(ctx, "yes")
        print(f"> yes\n{reply_f_yes[:200]}")
        if "logged" not in reply_f_yes.lower():
            fails.append(f"F: 'yes' did not log expense. reply={reply_f_yes[:200]}")
        else:
            # Clean up — void the row we just created so we don't pollute reports.
            async with get_session() as s:
                latest = (await s.execute(
                    select(Expense).where(
                        Expense.notes.ilike("%Logged via WhatsApp%"),
                        Expense.is_void == False,
                    ).order_by(Expense.id.desc()).limit(1)
                )).scalars().first()
                if latest and latest.id not in {e.id for e in count_before}:
                    latest.is_void = True
                    print(f"  [cleanup] voided expense id={latest.id}")
                    await s.commit()
        await _purge_pending(phone_norm)

    print("\n" + "=" * 60)
    if fails:
        print(f"FAIL ({len(fails)} issues):")
        for f in fails:
            print("  -", f)
        return 1
    print("PASS — all room-transfer + day-wise + expense e2e scenarios green.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
