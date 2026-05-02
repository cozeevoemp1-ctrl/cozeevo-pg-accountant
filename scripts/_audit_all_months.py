"""
Audit Nov 2025 – Apr 2026 across:
  1. DB (payments table)
  2. Cozeevo Ops v2 monthly tab COLLECTION rows (1Hp5dTM7...)
  3. Source sheets:
       Nov-Mar: THOR history (1jOCVBk...) columns until-jan/feb/march cash+upi
       Apr:     April sheet  (1Vr_...) April cash + April UPI columns
"""
import asyncio, os, datetime, re
from dotenv import load_dotenv; load_dotenv()
import asyncpg, gspread

def parse(v):
    s = str(v).strip()
    # If cell contains non-numeric text (notes, names, slashes), treat as 0
    if not re.match(r'^[\d,\.]+$', s): return 0
    s = re.sub(r'[^\d.]', '', s)
    try: return int(float(s))
    except: return 0

async def main():
    gc = gspread.service_account(filename='credentials/gsheets_service_account.json')

    # ── DB ────────────────────────────────────────────────────────────────
    url = os.getenv('DATABASE_URL').replace('postgresql+asyncpg','postgresql')
    conn = await asyncpg.connect(url)
    db = {}
    for m in ['2025-11-01','2025-12-01','2026-01-01','2026-02-01','2026-03-01','2026-04-01']:
        rows = await conn.fetch(
            "SELECT payment_mode, SUM(amount) as total FROM payments "
            "WHERE period_month=$1 AND for_type='rent' AND is_void=false GROUP BY payment_mode",
            datetime.date.fromisoformat(m))
        db[m] = {
            'cash': next((int(r['total']) for r in rows if r['payment_mode']=='cash'),0),
            'upi':  next((int(r['total']) for r in rows if r['payment_mode']=='upi'), 0),
        }
    await conn.close()

    # ── Ops sheet (Cozeevo v2) COLLECTION rows ────────────────────────────
    ops_sh = gc.open_by_key('1Hp5dTM7TcDEq75jgHEjvwtBjOolruGfQ7CVMzVqjdGw')
    ops_tabs = {
        '2025-11-01': 'NOVEMBER 2025',
        '2025-12-01': 'DECEMBER 2025',
        '2026-01-01': 'JANUARY 2026',
        '2026-02-01': 'FEBRUARY 2026',
        '2026-03-01': 'MARCH 2026',
        '2026-04-01': 'APRIL 2026',
    }
    ops = {}
    for m, tab in ops_tabs.items():
        ws = ops_sh.worksheet(tab)
        rows = ws.get_all_values()
        cash, upi = 0, 0
        for r in rows[:10]:
            if r and 'COLLECTION' in str(r[0]).upper():
                for cell in r[1:]:
                    s = str(cell).strip()
                    if re.search(r'cash', s, re.I):
                        cash = parse(re.sub(r'cash\s*:\s*rs?\.?\s*', '', s, flags=re.I))
                    if re.search(r'upi', s, re.I):
                        upi = parse(re.sub(r'upi\s*:\s*rs?\.?\s*', '', s, flags=re.I))
                break
        ops[m] = {'cash': cash, 'upi': upi}

    # ── Source sheets ─────────────────────────────────────────────────────
    # THOR history (Nov-Mar): columns 23=until_jan_cash, 24=until_jan_upi,
    #   29=feb_cash, 30=feb_upi, 32=march_cash, 33=march_upi
    thor_sh = gc.open_by_key('1jOCVBkVurLNaht9HYKR6SFqGCciIoMWeOJkfKF9essk')
    thor_ws = thor_sh.worksheet('History')
    thor_rows = thor_ws.get_all_values()
    src = {m: {'cash':0,'upi':0} for m in ['2025-11-01','2025-12-01','2026-01-01','2026-02-01','2026-03-01','2026-04-01']}
    for r in thor_rows[1:]:
        if not r[0].strip(): continue
        src['2026-01-01']['cash'] += parse(r[23])
        src['2026-01-01']['upi']  += parse(r[24])
        src['2026-02-01']['cash'] += parse(r[29])
        src['2026-02-01']['upi']  += parse(r[30])
        src['2026-03-01']['cash'] += parse(r[32])
        src['2026-03-01']['upi']  += parse(r[33])
    # Nov/Dec have no columns in THOR history — use Ops sheet COLLECTION (or 0 if ops shows 0)
    src['2025-11-01'] = {'cash': ops['2025-11-01']['cash'], 'upi': ops['2025-11-01']['upi']}
    src['2025-12-01'] = {'cash': ops['2025-12-01']['cash'], 'upi': ops['2025-12-01']['upi']}

    # April: 1Vr_ sheet
    apr_sh = gc.open_by_key('1Vr_fSIOuuKBK4MWF-FVqgAIUPbqun3POszaXYfj-Ea0')
    apr_ws = apr_sh.worksheet('Long term')
    apr_rows = apr_ws.get_all_values()
    for r in apr_rows[1:]:
        if r[0].strip():
            src['2026-04-01']['cash'] += parse(r[21])
            src['2026-04-01']['upi']  += parse(r[22])

    # ── Print comparison ──────────────────────────────────────────────────
    months = ['2025-11-01','2025-12-01','2026-01-01','2026-02-01','2026-03-01','2026-04-01']
    labels = ["Nov'25","Dec'25","Jan'26","Feb'26","Mar'26","Apr'26"]

    print(f'{"Month":7s}  {"Source":>10s}  {"Ops Sheet":>10s}  {"DB":>10s}  {"Src-DB":>8s}  {"Ops-DB":>8s}  {"Src-Ops":>8s}')
    print('-'*75)
    all_ok = True
    for m, label in zip(months, labels):
        s = src[m]['cash'] + src[m]['upi']
        o = ops[m]['cash'] + ops[m]['upi']
        d = db[m]['cash']  + db[m]['upi']
        sd = s - d
        od = o - d
        so = s - o
        flag = '' if sd == 0 and od == 0 else '  <<'
        if flag: all_ok = False
        print(f"{label:7s}  {s:>10,}  {o:>10,}  {d:>10,}  {sd:>+8,}  {od:>+8,}  {so:>+8,}{flag}")

    print()
    if all_ok:
        print('All months: Source = Ops = DB')
    else:
        print('Discrepancies found (<<)')

asyncio.run(main())
