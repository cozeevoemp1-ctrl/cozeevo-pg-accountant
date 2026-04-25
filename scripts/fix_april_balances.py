"""
scripts/fix_april_balances.py
==============================
Read April Month Collection source sheet → set every April rent_schedule
balance to match exactly. Zero everything not in the source.

Usage:
    python scripts/fix_april_balances.py          # dry run
    python scripts/fix_april_balances.py --write  # commit to DB
"""
import asyncio
import os
import re
import sys
from datetime import date

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

import gspread
from google.oauth2.service_account import Credentials
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from src.database.models import Tenant, Tenancy, Room, Payment, RentSchedule, RentStatus, PaymentFor

SOURCE_SHEET_ID = "1Vr_fSIOuuKBK4MWF-FVqgAIUPbqun3POszaXYfj-Ea0"
CREDENTIALS_PATH = "credentials/gsheets_service_account.json"
APRIL = date(2026, 4, 1)

COL_ROOM = 0
COL_NAME = 1
COL_APR_CASH = 21
COL_APR_UPI = 22
COL_APR_BALANCE = 23
COL_INOUT = 16


def pn(val):
    if val is None or val == "":
        return 0.0
    s = str(val).replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


def norm_room(raw):
    return re.sub(r'\.0+$', '', str(raw or "").strip())


def name_key(name):
    """Lowercase, strip, first token for fuzzy match."""
    return str(name or "").lower().strip()


async def fetch_source():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SOURCE_SHEET_ID)
    ws = sh.worksheet("Long term")
    return ws.get_all_values()


async def main(write: bool):
    print(f"Mode: {'WRITE' if write else 'DRY RUN'}")

    # ── 1. Read source sheet ───────────────────────────────────────────────
    rows = await fetch_source()
    print(f"Fetched {len(rows)} rows from source sheet")

    # Build map: (room, name_lower) → apr_balance
    # Also (room,) → apr_balance for fallback
    source_balance: dict[tuple, float] = {}
    source_rows_with_balance = []
    for row in rows[1:]:
        if len(row) < 24:
            continue
        inout = row[COL_INOUT].strip().upper()
        if inout not in ("CHECKIN", "EXIT", "NO SHOW", "CANCELLED"):
            continue
        raw_room = norm_room(row[COL_ROOM])
        name = row[COL_NAME].strip()
        bal = pn(row[COL_APR_BALANCE])
        key = (raw_room, name_key(name))
        source_balance[key] = bal
        if bal > 0:
            source_rows_with_balance.append((raw_room, name, bal))

    print(f"\nSource sheet — rows with non-zero balance ({len(source_rows_with_balance)}):")
    for r, n, b in sorted(source_rows_with_balance, key=lambda x: x[0]):
        print(f"  Room {r:>5}  {n:<30}  ₹{b:,.0f}")

    # ── 2. Load DB ─────────────────────────────────────────────────────────
    engine = create_async_engine(os.getenv("DATABASE_URL"), echo=False)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with AsyncSessionLocal() as s:
        # Load all April rent_schedules with joins
        rs_rows = (await s.execute(
            select(RentSchedule, Tenancy, Tenant, Room)
            .join(Tenancy, RentSchedule.tenancy_id == Tenancy.id)
            .join(Tenant, Tenancy.tenant_id == Tenant.id)
            .join(Room, Tenancy.room_id == Room.id)
            .where(RentSchedule.period_month == APRIL)
        )).all()
        print(f"\nDB — April rent_schedule rows: {len(rs_rows)}")

        # Load April payments per tenancy
        pay_rows = (await s.execute(
            select(Payment.tenancy_id, func.sum(Payment.amount))
            .where(
                and_(
                    Payment.period_month == APRIL,
                    Payment.is_void == False,
                    Payment.for_type == PaymentFor.rent,
                )
            )
            .group_by(Payment.tenancy_id)
        )).all()
        payments_by_tenancy: dict[int, float] = {tid: float(amt) for tid, amt in pay_rows}

        # ── 3. Process each rent_schedule row ─────────────────────────────
        updates = []
        for rs, tenancy, tenant, room in rs_rows:
            room_num = norm_room(room.room_number)
            tname = tenant.name.strip()
            tname_key = name_key(tname)

            # Try exact match first, then room-only match
            src_bal = source_balance.get((room_num, tname_key))
            if src_bal is None:
                # Try partial name match within same room
                for (sr, sn), sb in source_balance.items():
                    if sr == room_num and (sn in tname_key or tname_key in sn or tname_key[:6] == sn[:6]):
                        src_bal = sb
                        break
            if src_bal is None:
                src_bal = 0.0  # not in source → zero

            # payments already in DB for this tenancy in April
            paid = payments_by_tenancy.get(tenancy.id, 0.0)

            # adjustment needed: balance = effective_due - paid
            # effective_due = rent_due + adjustment
            # → adjustment = src_bal + paid - rent_due
            rent_due = float(rs.rent_due or 0)
            new_adj = src_bal + paid - rent_due
            new_status = RentStatus.paid if src_bal == 0 else RentStatus.partial

            current_adj = float(rs.adjustment or 0)
            current_bal = rent_due + current_adj - paid

            if abs(new_adj - current_adj) < 0.01:
                print(f"  SKIP  Room {room_num:>5}  {tname:<28}  balance already ₹{src_bal:,.0f}")
                continue

            updates.append({
                "rs": rs,
                "room": room_num,
                "name": tname,
                "old_bal": current_bal,
                "new_bal": src_bal,
                "new_adj": new_adj,
                "new_status": new_status,
            })

        print(f"\nRows to update: {len(updates)}")
        print(f"  → set to ₹0 balance: {sum(1 for u in updates if u['new_bal'] == 0)}")
        print(f"  → set to non-zero:   {sum(1 for u in updates if u['new_bal'] > 0)}")
        print()

        if updates:
            print("Changes:")
            for u in sorted(updates, key=lambda x: x['room']):
                arrow = "→" if u["new_bal"] > 0 else "→ ZERO"
                print(f"  Room {u['room']:>5}  {u['name']:<28}  ₹{u['old_bal']:>8,.0f}  {arrow}  ₹{u['new_bal']:>8,.0f}")

        if write and updates:
            for u in updates:
                rs = u["rs"]
                rs.adjustment = u["new_adj"]
                rs.adjustment_note = "MANUAL_LOCK"
                rs.status = u["new_status"]
                rs.notes = (
                    (rs.notes or "") + " | zeroed to match April source 2026-04-25"
                ).lstrip(" | ")
                s.add(rs)
            await s.commit()
            print(f"\nCommitted {len(updates)} rows.")
        elif not write:
            print("\nDry run — pass --write to apply.")

    await engine.dispose()


if __name__ == "__main__":
    write = "--write" in sys.argv
    asyncio.run(main(write))
