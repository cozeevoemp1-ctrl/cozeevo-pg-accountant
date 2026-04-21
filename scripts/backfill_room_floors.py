"""
scripts/backfill_room_floors.py
================================
Fill NULL Room.floor values by deriving from room_number (G-prefix→0,
else first digit). Idempotent — only updates rows where floor IS NULL or
differs from the derived value for G-prefix rooms (they were mostly NULL).

Usage:
    python scripts/backfill_room_floors.py            # dry run
    python scripts/backfill_room_floors.py --write    # commit
"""
import asyncio
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import select
from src.database.db_manager import init_engine, get_session
from src.database.models import Room
from src.utils.room_floor import derive_floor


async def main(write: bool):
    init_engine(os.environ["DATABASE_URL"])
    print(f"Mode: {'WRITE' if write else 'DRY RUN'}", flush=True)

    async with get_session() as s:
        rooms = (await s.execute(select(Room))).scalars().all()
        to_update = []
        for r in rooms:
            derived = derive_floor(r.room_number)
            if derived is None:
                continue
            if r.floor != derived:
                to_update.append((r, derived))
        print(f"Total rooms: {len(rooms)}  Needs update: {len(to_update)}", flush=True)
        for r, d in to_update[:20]:
            print(f"  {r.room_number:>6}  floor {r.floor!r:>5} -> {d}")
        if len(to_update) > 20:
            print(f"  ... +{len(to_update)-20} more")
        if write:
            for r, d in to_update:
                r.floor = d
            await s.commit()
            print(f"Wrote {len(to_update)} rows.", flush=True)


if __name__ == "__main__":
    asyncio.run(main("--write" in sys.argv))
