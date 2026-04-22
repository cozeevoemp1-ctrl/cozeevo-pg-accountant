"""Gap report split: explained (has comment) vs unexplained (no comment)."""
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
            is_fm = bool(t.checkin_date and t.checkin_date.replace(day=1) == apr)
            key = (rm.room_number, tn.name.lower())
            if key not in src:
                continue
            cash, upi, bal, note = src[key]
            src_due = cash + upi + bal
            gap = our_due - src_due
            if abs(gap) >= 1:
                gaps.append((rm.room_number, tn.name, int(our_due), int(src_due), int(gap), is_fm, note))

    # Split by whether there's an explanatory comment
    def has_expl(note):
        n = (note or "").lower()
        keywords = [
            "always cash", "vacation", "lockin", "lock in", "month lockin",
            "until may", "until jun", "until april", "until march", "pay half",
            "half deposit", "absconded", "abscond", "referral", "april & may",
            "paid in march", "pay before", "balance", "security", "deposit",
            "rent 1200", "rent 1100", "rent is", "22500", "ref from",
            "he stay", "one month", "1 month", "2 month", "3 month",
            "if cash", "if upi", "cash rent", "exit", "checkout",
        ]
        return any(k in n for k in keywords)

    explained = [g for g in gaps if has_expl(g[6])]
    unexplained = [g for g in gaps if not has_expl(g[6])]

    def print_group(title, items):
        print(f"\n=== {title} ({len(items)} tenants) ===")
        print(f"{'Room':>6}  {'Name':<28}  {'OurDue':>8}  {'SrcDue':>8}  {'Gap':>7}  FM  Comment")
        print("-" * 130)
        for g in sorted(items, key=lambda x: -abs(x[4])):
            fm = "FM" if g[5] else "  "
            note = g[6][:65] if g[6] else "(blank)"
            print(f"{g[0]:>6}  {g[1][:28]:<28}  {g[2]:>8,}  {g[3]:>8,}  {g[4]:>+7,}  {fm}  {note}")
        print(f"Subtotal gap: Rs.{sum(g[4] for g in items):+,}")

    print_group("EXPLAINED — source comment describes the arrangement", explained)
    print_group("UNEXPLAINED — no comment, possible data mismatch", unexplained)

    print(f"\n=== GRAND TOTALS ===")
    print(f"Total gaps:       {len(gaps)}")
    print(f"Explained:        {len(explained)}  (Rs.{sum(g[4] for g in explained):+,})")
    print(f"Unexplained:      {len(unexplained)}  (Rs.{sum(g[4] for g in unexplained):+,})")
    print(f"Net gap:          Rs.{sum(g[4] for g in gaps):+,}")


asyncio.run(main())
