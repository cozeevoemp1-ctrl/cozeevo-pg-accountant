"""Exit 6 duplicate/ghost tenancies identified 2026-04-23.

Each of these had a newer correct tenancy (or is in source with different
phone/name). Source "April Month Collection" sheet is truth: 224 regular + 22
premium = 246 active CHECKIN. Before this script, DB had 253 active.

Ghosts:
  628  Anshsinha (301)        — duplicate of tid=891 (different phone)
  749  Sanskar Bharadia (605) — duplicate of tid=913 (different phone)
  818  Chinmay Pagey (124)    — wrong room, duplicate of tid=835 (112)
  892  Arun R L (114)         — duplicate of tid=896 (phone-format twin)
  893  Pooja K L (114)        — duplicate of tid=895 (phone-format twin)
  894  Rakesh Thallapally (415) — premium duplicate of tid=901 T.Rakesh Chetan

tid=742 Yatam Ramakanth (520) is NOT here — source has him as EXIT so
sync_from_source_sheet.py will flip him correctly.
"""
import asyncio
import os
import sys
from datetime import date

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

from src.database.db_manager import init_engine, get_session
from src.database.models import Tenancy, TenancyStatus


GHOSTS = [628, 749, 818, 892, 893, 894]


async def main():
    init_engine(os.environ["DATABASE_URL"])
    async with get_session() as s:
        for tid in GHOSTS:
            t = await s.get(Tenancy, tid)
            if not t:
                print(f"tid={tid}: not found (skip)")
                continue
            if t.status == TenancyStatus.exited:
                print(f"tid={tid}: already exited (skip)")
                continue
            t.status = TenancyStatus.exited
            t.checkout_date = t.checkout_date or date(2026, 4, 23)
            print(f"tid={tid}: status -> exited, checkout_date={t.checkout_date}")
        await s.commit()
    print("done")


if __name__ == "__main__":
    asyncio.run(main())
