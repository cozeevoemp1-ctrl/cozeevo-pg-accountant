"""Gap report: our bot's rent_due vs source sheet's implied due (cash+upi+balance)."""
import asyncio
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

import gspread
from google.oauth2.service_account import Credentials
from sqlalchemy import select
from src.database.db_manager import init_engine, get_session
from src.database.models import RentSchedule, Tenancy, Tenant, Room
from datetime import date


def pn(v):
    if not v:
        return 0.0
    try:
        return float(str(v).replace(",", "").strip())
    except ValueError:
        return 0.0


async def main():
    creds = Credentials.from_service_account_file(
        "credentials/gsheets_service_account.json",
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    gc = gspread.authorize(creds)
    sh = gc.open_by_key("1Vr_fSIOuuKBK4MWF-FVqgAIUPbqun3POszaXYfj-Ea0")
    rows = sh.worksheet("Long term").get_all_values()[1:]
    src = {}
    for r in rows:
        if len(r) < 24:
            continue
        room, name = (r[0] or "").strip(), (r[1] or "").strip()
        if not name:
            continue
        src[(room, name.lower())] = (pn(r[21]), pn(r[22]), pn(r[23]), (r[14] or "").strip())

    init_engine(os.environ["DATABASE_URL"])
    apr = date(2026, 4, 1)
    async with get_session() as s:
        rs_rows = (await s.execute(select(RentSchedule).where(RentSchedule.period_month == apr))).scalars().all()
        gaps = []
        for rs in rs_rows:
            t = await s.get(Tenancy, rs.tenancy_id)
            if not t:
                continue
            tn = await s.get(Tenant, t.tenant_id)
            rm = await s.get(Room, t.room_id)
            our_due = float(rs.rent_due or 0)
            is_fm = t.checkin_date and t.checkin_date.replace(day=1) == apr
            key = (rm.room_number, tn.name.lower())
            if key not in src:
                continue
            cash, upi, bal, note = src[key]
            src_due = cash + upi + bal
            gap = our_due - src_due
            if abs(gap) >= 1:
                gaps.append((rm.room_number, tn.name, int(our_due), int(src_due), int(gap), is_fm, note[:70]))

    gaps.sort(key=lambda x: -abs(x[4]))
    print(f"{'Room':>6}  {'Name':<28}  {'OurDue':>8}  {'SrcDue':>8}  {'Gap':>7}  FM  Note")
    print("-" * 130)
    for g in gaps:
        fm = "FM" if g[5] else "  "
        print(f"{g[0]:>6}  {g[1][:28]:<28}  {g[2]:>8,}  {g[3]:>8,}  {g[4]:>+7,}  {fm}  {g[6]}")
    print()
    print(f"Tenants with gaps: {len(gaps)}")
    print(f"Sum OurDue:  Rs.{sum(g[2] for g in gaps):,}")
    print(f"Sum SrcDue:  Rs.{sum(g[3] for g in gaps):,}")
    print(f"Net gap:     Rs.{sum(g[4] for g in gaps):+,}")


asyncio.run(main())
