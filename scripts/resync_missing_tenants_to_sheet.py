"""
scripts/resync_missing_tenants_to_sheet.py
===========================================
Finds tenants present in DB but missing from TENANTS sheet (by phone) and
pushes them via gsheets.add_tenant. Safe to re-run; add_tenant appends so
running twice will double-post.

Usage:
    venv/Scripts/python scripts/resync_missing_tenants_to_sheet.py          # dry
    venv/Scripts/python scripts/resync_missing_tenants_to_sheet.py --write  # push
"""
import asyncio
import os
import re
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import dotenv_values
env = dotenv_values(".env")
os.environ.update({k: v for k, v in env.items() if v is not None and k not in os.environ})

import gspread
from google.oauth2.service_account import Credentials
from sqlalchemy import select, desc
from sqlalchemy.orm import selectinload

from src.integrations.gsheets import CREDENTIALS_PATH, SHEET_ID, add_tenant
from src.database.db_manager import init_engine, get_session
from src.database.models import Tenant, Tenancy, Property, Room


def nph(p):
    d = re.sub(r"\D", "", str(p or ""))
    return d[-10:] if len(d) >= 10 else ""


async def get_sheet_phones():
    scopes = ["https://www.googleapis.com/auth/spreadsheets",
              "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=scopes)
    gc = gspread.authorize(creds)
    ss = gc.open_by_key(SHEET_ID)
    ws = ss.worksheet("TENANTS")
    rows = ws.get_all_values()
    return set(nph(r[2]) for r in rows[1:] if len(r) > 2)


async def main(write: bool):
    init_engine(os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL"))
    sheet_phones = await get_sheet_phones()
    print(f"TENANTS sheet unique phones: {len(sheet_phones)}")

    async with get_session() as s:
        cutoff = datetime.utcnow() - timedelta(days=10)
        q = (
            select(Tenant)
            .options(
                selectinload(Tenant.tenancies).selectinload(Tenancy.room).selectinload(Room.property),
            )
            .where(Tenant.created_at >= cutoff)
            .order_by(desc(Tenant.created_at))
        )
        missing = []
        for t in (await s.execute(q)).scalars().all():
            ph = nph(t.phone)
            if not ph or ph in sheet_phones:
                continue
            if not t.tenancies:
                continue
            ten = next((x for x in t.tenancies if x.room and str(getattr(x.stay_type, 'value', x.stay_type) or '') != 'daily'), None)
            if not ten:
                continue
            missing.append((t, ten))

    print(f"Tenants to re-sync: {len(missing)}")
    for t, ten in missing:
        print(f"  {t.name:25s} phone={t.phone:18s} room={ten.room.room_number} "
              f"rent={float(ten.agreed_rent or 0):.0f} dep={float(ten.security_deposit or 0):.0f} "
              f"checkin={ten.checkin_date}")

    if not write:
        print("\nDry-run. Pass --write to push.")
        return

    ok = failed = 0
    for t, ten in missing:
        phone_sheet = t.phone
        if phone_sheet and not phone_sheet.startswith("+"):
            phone_sheet = "+91" + phone_sheet[-10:]
        building = ""
        if ten.room.property:
            building = ten.room.property.name
        sharing = ten.sharing_type.value if ten.sharing_type else (
            ten.room.room_type.value if hasattr(ten.room.room_type, "value") else str(ten.room.room_type or "")
        )
        try:
            r = await add_tenant(
                room_number=str(ten.room.room_number),
                name=t.name,
                phone=phone_sheet,
                gender=t.gender or "",
                building=building,
                floor=str(ten.room.floor or ""),
                sharing=sharing,
                checkin=ten.checkin_date.strftime("%d/%m/%Y") if ten.checkin_date else "",
                agreed_rent=float(ten.agreed_rent or 0),
                deposit=float(ten.security_deposit or 0),
                booking=float(ten.booking_amount or 0),
                maintenance=float(ten.maintenance_fee or 0),
                notes="",
                entered_by="resync_20260423",
            )
            if r.get("success"):
                ok += 1
                print(f"  [ok] {t.name} -> TENANTS row {r.get('tenants_row')} / {r.get('monthly_tab')} row {r.get('monthly_row')}")
            else:
                failed += 1
                print(f"  [FAIL] {t.name}: {r.get('error')}")
        except Exception as e:
            failed += 1
            print(f"  [EXC]  {t.name}: {e}")

    print(f"\nDone. ok={ok}  failed={failed}")


if __name__ == "__main__":
    asyncio.run(main("--write" in sys.argv))
