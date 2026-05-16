"""
Void 11 duplicate May rent payments created by Z/AA import bug.

Root cause: _import_may_payments.py only checked for_type='rent' when deduplicating.
New tenants who checked in during May 2026 had their booking advance already in DB.
The sheet's Z/AA columns also included that advance. Import saw db_upi/cash=0 and
added the same amount again as rent -> duplicate.

Confirmed duplicates: booking_date >= 2026-05-01 (May check-ins only).
March/April check-ins verified safe: total_may == agreed_rent exactly, no inflation.
Mathew Koshy (16233) already voided separately.

Usage:
    python scripts/_void_may_dupe_imports.py          # dry run
    python scripts/_void_may_dupe_imports.py --write  # commit
"""
import asyncio, os, sys, argparse
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

TO_VOID = [
    (16255, 'Akshay Kothari     upi  2000'),
    (16231, 'Chandraprakash     upi  5000'),
    (16229, 'LELIN DAS          cash 27000'),
    (16242, 'Rama Krishnan      upi  2000'),
    (16235, 'Abhinav Rastogi    upi  2000'),
    (16237, 'Chaitanya Talokar  upi  2000'),
    (16241, 'Joshua Sakthivel   upi  2000'),
    (16239, 'Shubham Yadav      upi  2000'),
    (16245, 'Kona Yashwanth     upi  2000'),
    (16254, 'Jagpreet Singh     upi 13500'),
    (16260, 'Dhruv              upi 13000'),
]

NOTE = ' [VOIDED: dup of booking advance -- Z/AA import bug 2026-05-16]'


async def run(write):
    url = os.environ['DATABASE_URL']
    if url.startswith('postgresql://'):
        url = url.replace('postgresql://', 'postgresql+asyncpg://', 1)
    engine = create_async_engine(url, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as session:
        await session.execute(text("SET LOCAL app.allow_historical_write = 'true'"))
        upi_total = 0
        cash_total = 0
        for pid, desc in TO_VOID:
            r = (await session.execute(
                text('SELECT amount, payment_mode, is_void FROM payments WHERE id=:id'),
                {'id': pid}
            )).fetchone()
            if not r:
                print(f'  NOT FOUND: {pid}')
                continue
            if r[2]:
                print(f'  ALREADY VOIDED: {pid} {desc}')
                continue
            mode = 'upi' if r[1] == 'upi' else 'cash'
            print(f'  {"VOID" if write else "DRY"}: pmt {pid}  {desc}  amt={int(r[0])}')
            if write:
                await session.execute(
                    text('UPDATE payments SET is_void=true, notes=notes||:n WHERE id=:id'),
                    {'id': pid, 'n': NOTE}
                )
            if mode == 'upi':
                upi_total += int(r[0])
            else:
                cash_total += int(r[0])

        if write:
            await session.commit()
            print('\n** COMMITTED **')
        else:
            print('\n** DRY RUN -- no changes **')

        print(f'\nImpact on May totals (overcounts removed):')
        print(f'  May UPI  -=  {upi_total:,}')
        print(f'  May Cash -=  {cash_total:,}')
        print(f'  (These were booking advances counted twice)')

    await engine.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    asyncio.run(run(args.write))
