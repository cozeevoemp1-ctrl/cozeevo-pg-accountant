"""
Reconcile April 2026 DB payments to match source sheet totals.
Match by tenant name (case-insensitive), ignore room numbers.
Where DB > sheet: void specific payment records to bring down to sheet total.
Where DB has tenant not in sheet at all: void all their April payments.
"""
import asyncio, os, re
from dotenv import load_dotenv
load_dotenv()
import asyncpg, gspread

def parse(v):
    v = str(v).strip().replace(',', '').replace('Rs.', '')
    try:
        return int(float(v))
    except:
        return 0

def norm(name):
    return re.sub(r'\s+', ' ', name.strip().lower())

async def main():
    # ── Source sheet ──────────────────────────────────────────────────────
    gc = gspread.service_account(filename='credentials/gsheets_service_account.json')
    sh = gc.open_by_key('1Vr_fSIOuuKBK4MWF-FVqgAIUPbqun3POszaXYfj-Ea0')
    ws = sh.worksheet('Long term')
    srows = ws.get_all_values()

    # name → (cash, upi)  [col 21 = April cash, col 22 = April UPI]
    sheet = {}
    for r in srows[1:]:
        if not r[0].strip():
            continue
        name = norm(r[1])
        if not name:
            continue
        c, u = parse(r[21]), parse(r[22])
        if name in sheet:
            sheet[name] = (sheet[name][0] + c, sheet[name][1] + u)
        else:
            sheet[name] = (c, u)

    # ── DB ────────────────────────────────────────────────────────────────
    url = os.getenv('DATABASE_URL').replace('postgresql+asyncpg', 'postgresql')
    conn = await asyncpg.connect(url)

    # All April rent payments with IDs, ordered largest first (void largest first)
    db_payments = await conn.fetch(
        "SELECT p.id, t.name, p.payment_mode, p.amount "
        "FROM payments p "
        "JOIN tenancies te ON p.tenancy_id = te.id "
        "JOIN tenants t ON te.tenant_id = t.id "
        "WHERE p.period_month='2026-04-01' AND p.for_type='rent' AND p.is_void=false "
        "ORDER BY t.name, p.amount DESC",
    )

    # Group by normalised name
    from collections import defaultdict
    db_by_name = defaultdict(list)
    for r in db_payments:
        db_by_name[norm(r['name'])].append({'id': r['id'], 'mode': r['payment_mode'], 'amount': int(r['amount'])})

    # ── Plan ──────────────────────────────────────────────────────────────
    to_void = []   # list of payment IDs to void
    print('=== RECONCILIATION PLAN ===')
    print(f'{"Name":28s}  {"Sheet":>8s}  {"DB":>8s}  {"Action"}')
    print('-' * 70)

    for name, payments in sorted(db_by_name.items()):
        db_total = sum(p['amount'] for p in payments)
        sh_total = sum(sheet.get(name, (0, 0)))

        if db_total == sh_total:
            continue  # already matches

        diff = db_total - sh_total
        if diff > 0:
            # DB has more — need to void diff worth of payments
            remaining = diff
            voiding = []
            for p in payments:  # largest first
                if remaining <= 0:
                    break
                if p['amount'] <= remaining:
                    voiding.append(p['id'])
                    remaining -= p['amount']
                # partial void not possible — skip if payment > remaining
            if remaining == 0:
                to_void.extend(voiding)
                print(f'{name[:28]:28s}  {sh_total:>8,}  {db_total:>8,}  VOID {len(voiding)} pmt(s) totalling {diff:,}')
            else:
                print(f'{name[:28]:28s}  {sh_total:>8,}  {db_total:>8,}  !! CANNOT MATCH exactly (diff={diff}, smallest pmt too large) — VOID ALL extra')
                # just void all their payments if sheet=0, else flag
                if sh_total == 0:
                    for p in payments:
                        to_void.append(p['id'])
                    print(f'  -> voiding all {len(payments)} payments (sheet=0)')
        else:
            # DB has less than sheet — can't add payments here
            print(f'{name[:28]:28s}  {sh_total:>8,}  {db_total:>8,}  DB < SHEET by {-diff:,} — SKIP (need manual add)')

    print(f'\nTotal payments to void: {len(to_void)}')

    if not to_void:
        print('Nothing to void.')
        await conn.close()
        return

    # ── Execute ───────────────────────────────────────────────────────────
    async with conn.transaction():
        await conn.execute("SET LOCAL app.allow_historical_write = 'true'")
        result = await conn.execute(
            "UPDATE payments SET is_void=true WHERE id = ANY($1::int[])",
            to_void)
        print(f'Voided: {result}')

    # ── Verify ────────────────────────────────────────────────────────────
    rows = await conn.fetch(
        "SELECT payment_mode, SUM(amount) as total, COUNT(*) as cnt "
        "FROM payments WHERE period_month='2026-04-01' AND for_type='rent' AND is_void=false "
        "GROUP BY payment_mode")
    cash = next((int(r['total']) for r in rows if r['payment_mode'] == 'cash'), 0)
    upi  = next((int(r['total']) for r in rows if r['payment_mode'] == 'upi'),  0)
    print(f'\nDB after:  Cash {cash:>12,}  UPI {upi:>12,}  Total {cash+upi:>12,}')

    sh_cash = sum(v[0] for v in sheet.values())
    sh_upi  = sum(v[1] for v in sheet.values())
    print(f'Sheet:     Cash {sh_cash:>12,}  UPI {sh_upi:>12,}  Total {sh_cash+sh_upi:>12,}')
    print(f'Diff:      Cash {cash-sh_cash:>+12,}  UPI {upi-sh_upi:>+12,}  Total {(cash+upi)-(sh_cash+sh_upi):>+12,}')

    await conn.close()

asyncio.run(main())
