"""Fix rooms 107, 114, 618 — not staff rooms."""
import asyncio, os, sys
sys.stdout.reconfigure(encoding='utf-8')
from dotenv import load_dotenv; load_dotenv()
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

async def run():
    url = os.environ['DATABASE_URL'].replace('postgresql://', 'postgresql+asyncpg://', 1)
    engine = create_async_engine(url, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as s:
        r = await s.execute(text(
            "UPDATE rooms SET is_staff_room = FALSE "
            "WHERE room_number IN ('107', '114', '618') AND is_staff_room IS DISTINCT FROM FALSE"
        ))
        await s.commit()
        print(f"Updated {r.rowcount} rooms")

        r2 = await s.execute(text(
            "SELECT room_number, is_staff_room, max_occupancy FROM rooms "
            "WHERE room_number IN ('107', '114', '618') ORDER BY room_number"
        ))
        for row in r2.fetchall():
            print(f"  {row[0]}: is_staff_room={row[1]}  beds={row[2]}")

        r3 = await s.execute(text(
            "SELECT SUM(max_occupancy) FROM rooms WHERE is_staff_room=false AND room_number != '000'"
        ))
        print(f"Revenue beds now: {r3.scalar()}")
    await engine.dispose()

asyncio.run(run())
