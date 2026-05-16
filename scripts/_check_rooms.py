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
            "SELECT SUM(max_occupancy) as total, COUNT(*) as rooms "
            "FROM rooms WHERE is_staff_room = false AND room_number != '000'"
        ))
        row = r.fetchone()
        print(f"Revenue beds: {row[0]}  ({row[1]} rooms)")

        r2 = await s.execute(text(
            "SELECT room_number, max_occupancy FROM rooms "
            "WHERE is_staff_room = true ORDER BY room_number"
        ))
        rows = r2.fetchall()
        print(f"Staff rooms ({len(rows)}):")
        for row in rows:
            print(f"  {row[0]}  beds={row[1]}")

        # Staff rooms with occupancy
        r3 = await s.execute(text("""
            SELECT r.room_number, r.max_occupancy,
                   COUNT(t.id) FILTER (WHERE t.status = 'active') as active_tenants
            FROM rooms r
            LEFT JOIN tenancies t ON t.room_id = r.id
            WHERE r.is_staff_room = true
            GROUP BY r.room_number, r.max_occupancy
            ORDER BY r.room_number
        """))
        rows3 = r3.fetchall()
        print(f"\nStaff rooms with occupancy:")
        for row in rows3:
            free = row[1] - row[2]
            print(f"  {row[0]}  max={row[1]}  active={row[2]}  free={free}")
    await engine.dispose()

asyncio.run(run())
