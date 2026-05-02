"""
Sync April 2026 DB payments to match source sheet exactly.
Source sheet (1Vr_...) is master truth.
Matching: normalised first-word of name + total amount.
"""
import asyncio, os, re, datetime
from collections import defaultdict
from dotenv import load_dotenv
load_dotenv()
import asyncpg, gspread

def parse(v):
    v = str(v).strip().replace(',', '').replace('Rs.', '')
    try: return int(float(v))
    except: return 0

def norm(name):
    return re.sub(r'\s+', ' ', name.strip().lower())

def first_word(name):
    return norm(name).split()[0] if norm(name).split() else ''

APR = datetime.date(2026, 4, 1)

async def main():
    # ── Source sheet ──────────────────────────────────────────────────────
    gc = gspread.service_account(filename='credentials/gsheets_service_account.json')
    sh = gc.open_by_key('1Vr_fSIOuuKBK4MWF-FVqgAIUPbqun3POszaXYfj-Ea0')
    ws = sh.worksheet('Long term')
    srows = ws.get_all_values()

    # name → (cash, upi)
    sheet_by_name = {}
    for r in srows[1:]:
        if not r[0].strip(): continue
        name = norm(r[1])
        if not name: continue
        c, u = parse(r[21]), parse(r[22])
        if c + u == 0: continue
        if name in sheet_by_name:
            sheet_by_name[name] = (sheet_by_name[name][0]+c, sheet_by_name[name][1]+u)
        else:
            sheet_by_name[name] = (c, u)

    # ── DB current state ──────────────────────────────────────────────────
    url = os.getenv('DATABASE_URL').replace('postgresql+asyncpg', 'postgresql')
    conn = await asyncpg.connect(url)

    db_pmts = await conn.fetch(
        "SELECT p.id, t.name, te.id as tenancy_id, p.payment_mode, p.amount, p.is_void "
        "FROM payments p "
        "JOIN tenancies te ON p.tenancy_id = te.id "
        "JOIN tenants t ON te.tenant_id = t.id "
        "WHERE p.period_month=$1 AND p.for_type='rent' "
        "ORDER BY t.name, p.amount DESC", APR)

    # Include voided (so we can un-void if needed)
    db_active = defaultdict(list)  # norm name → active payments
    db_voided = defaultdict(list)  # norm name → voided payments

    for r in db_pmts:
        n = norm(r['name'])
        entry = {'id': r['id'], 'tenancy_id': r['tenancy_id'],
                 'mode': r['payment_mode'], 'amount': int(r['amount'])}
        if r['is_void']:
            db_voided[n].append(entry)
        else:
            db_active[n].append(entry)

    # Also get tenancies for April active tenants (to create new payments if needed)
    tenancies = await conn.fetch(
        "SELECT te.id, t.name, r.room_number "
        "FROM tenancies te "
        "JOIN tenants t ON te.tenant_id = t.id "
        "JOIN rooms r ON te.room_id = r.id "
        "WHERE te.status != 'exited' OR (te.checkout_date >= $1 AND te.checkin_date <= $2)",
        APR, datetime.date(2026, 4, 30))
    tenancy_by_name = {}
    for r in tenancies:
        n = norm(r['name'])
        tenancy_by_name[n] = r['id']

    # ── Match and reconcile ───────────────────────────────────────────────
    to_void    = []   # payment IDs to void
    to_unvoid  = []   # payment IDs to un-void
    to_insert  = []   # (tenancy_id, mode, amount) to insert

    print('=== SYNC PLAN ===')

    for sh_name, (sh_cash, sh_upi) in sorted(sheet_by_name.items()):
        sh_total = sh_cash + sh_upi

        # Try exact name match, then first-word match
        db_pmts_for = db_active.get(sh_name, [])
        if not db_pmts_for:
            # Try first-word match
            fw = first_word(sh_name)
            candidates = {n: v for n, v in db_active.items() if first_word(n) == fw}
            if len(candidates) == 1:
                matched_name = list(candidates.keys())[0]
                db_pmts_for = candidates[matched_name]
                if matched_name != sh_name:
                    print(f'  [name match] sheet={sh_name!r} -> db={matched_name!r}')
            # Also check voided payments
            if not db_pmts_for:
                voided_for = db_voided.get(sh_name, [])
                if not voided_for:
                    voided_for = [v for n, vl in db_voided.items()
                                  if first_word(n) == fw for v in vl]
                if voided_for:
                    # Un-void up to sh_total
                    remaining = sh_total
                    for p in sorted(voided_for, key=lambda x: x['amount'], reverse=True):
                        if remaining <= 0: break
                        if p['amount'] <= remaining:
                            to_unvoid.append(p['id'])
                            remaining -= p['amount']
                    if remaining == 0:
                        print(f'  UN-VOID  {sh_name:28s}  +{sh_total:,}')
                    else:
                        print(f'  UN-VOID+ADD  {sh_name:28s}  voided {sh_total-remaining:,}, still need {remaining:,}')
                        tid = tenancy_by_name.get(sh_name) or tenancy_by_name.get(
                            next((n for n in tenancy_by_name if first_word(n)==fw), ''), None)
                        if tid:
                            # add remaining as UPI (default)
                            mode = 'cash' if remaining == sh_cash else 'upi'
                            to_insert.append((tid, mode, remaining))
                    continue

        db_total = sum(p['amount'] for p in db_pmts_for)

        if db_total == sh_total:
            continue  # already matches

        diff = sh_total - db_total
        if diff > 0:
            # Need to add
            tid = (db_pmts_for[0]['tenancy_id'] if db_pmts_for
                   else tenancy_by_name.get(sh_name)
                   or tenancy_by_name.get(next((n for n in tenancy_by_name if first_word(n)==first_word(sh_name)), ''), None))
            if tid:
                mode = 'cash' if diff == sh_cash - sum(p['amount'] for p in db_pmts_for if p['mode']=='cash') else 'upi'
                to_insert.append((tid, mode, diff))
                print(f'  ADD      {sh_name:28s}  +{diff:,} ({mode})')
            else:
                print(f'  ADD ??   {sh_name:28s}  +{diff:,}  NO TENANCY FOUND')
        else:
            # Need to void excess
            excess = -diff
            remaining = excess
            for p in sorted(db_pmts_for, key=lambda x: x['amount'], reverse=True):
                if remaining <= 0: break
                if p['amount'] <= remaining:
                    to_void.append(p['id'])
                    remaining -= p['amount']
            if remaining == 0:
                print(f'  VOID     {sh_name:28s}  -{excess:,}')

    print(f'\nPlan: void={len(to_void)}, un-void={len(to_unvoid)}, insert={len(to_insert)}')

    # ── Execute ───────────────────────────────────────────────────────────
    async with conn.transaction():
        await conn.execute("SET LOCAL app.allow_historical_write = 'true'")

        if to_void:
            await conn.execute(
                "UPDATE payments SET is_void=true WHERE id=ANY($1::int[])", to_void)

        if to_unvoid:
            await conn.execute(
                "UPDATE payments SET is_void=false WHERE id=ANY($1::int[])", to_unvoid)

        for tid, mode, amount in to_insert:
            await conn.execute(
                "INSERT INTO payments (tenancy_id, amount, payment_mode, for_type, period_month, payment_date, created_at) "
                "VALUES ($1, $2, $3, 'rent', $4, $5, NOW())",
                tid, amount, mode, APR, datetime.date(2026, 4, 30))

    # ── Final verify ──────────────────────────────────────────────────────
    rows = await conn.fetch(
        "SELECT payment_mode, SUM(amount) as total FROM payments "
        "WHERE period_month=$1 AND for_type='rent' AND is_void=false GROUP BY payment_mode", APR)
    db_cash = next((int(r['total']) for r in rows if r['payment_mode']=='cash'), 0)
    db_upi  = next((int(r['total']) for r in rows if r['payment_mode']=='upi'),  0)

    sh_cash = sum(v[0] for v in sheet_by_name.values())
    sh_upi  = sum(v[1] for v in sheet_by_name.values())

    print(f'\nDB after:  Cash {db_cash:>12,}  UPI {db_upi:>12,}  Total {db_cash+db_upi:>12,}')
    print(f'Sheet:     Cash {sh_cash:>12,}  UPI {sh_upi:>12,}  Total {sh_cash+sh_upi:>12,}')
    print(f'Diff:      Cash {db_cash-sh_cash:>+12,}  UPI {db_upi-sh_upi:>+12,}  Total {(db_cash+db_upi)-(sh_cash+sh_upi):>+12,}')

    await conn.close()

asyncio.run(main())
