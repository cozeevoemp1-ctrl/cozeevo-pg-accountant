"""
April + May 2026 — outstanding dues only (partial + no payment).
One table per month per building. Sorted by balance descending.
"""
import os, csv, datetime, re
from dotenv import load_dotenv
load_dotenv()
db_url = os.environ['DATABASE_URL'].replace('postgresql+asyncpg://', 'postgresql://')
import psycopg2, openpyxl

APR_DAYS = 30
MAY_DAYS = 31

def extract_phone(upi_id):
    m = re.match(r'^(\d{10})(?:-\d+)?@', str(upi_id))
    return m.group(1) if m else None

hulk_entries = []
wb = openpyxl.load_workbook('Hulk may 11th bank statement.xlsx')
ws = wb.active
for row in ws.iter_rows(min_row=2, values_only=True):
    if row[11] == 'SUCCESS' and row[3]:
        hulk_entries.append({'amt': float(row[3]), 'phone': extract_phone(row[7]),
                              'name': str(row[8]).strip().upper(), 'matched': False})

thor_entries = []
with open('thor may 11th.csv', newline='') as f:
    for row in csv.DictReader(f):
        if row['Settlement_Status'] == 'SUCCESS' and row['TXN_AMOUNT']:
            thor_entries.append({'amt': float(row['TXN_AMOUNT']), 'phone': extract_phone(row['Payer_VPA']),
                                  'name': row['Payer_Name'].strip().upper(), 'matched': False})
may_entries = hulk_entries + thor_entries

conn = psycopg2.connect(db_url)
cur = conn.cursor()

cur.execute("""
SELECT t.name, t.phone, p.name, tn.agreed_rent, tn.security_deposit,
       tn.checkin_date, tn.checkout_date, r.room_number, tn.status, tn.id
FROM tenancies tn
JOIN tenants t ON t.id = tn.tenant_id
JOIN rooms r ON r.id = tn.room_id
JOIN properties p ON p.id = r.property_id
WHERE tn.status = 'active'
   OR (tn.checkout_date >= '2026-04-01' AND tn.checkout_date <= '2026-05-11' AND tn.status = 'exited')
ORDER BY p.name, t.name
""")
tenants = cur.fetchall()

cur.execute("""
SELECT tenancy_id, payment_mode, SUM(amount)
FROM payments WHERE is_void=false AND period_month='2026-04-01'
GROUP BY tenancy_id, payment_mode
""")
apr_pay = {}
for r in cur.fetchall():
    apr_pay.setdefault(r[0], {'upi': 0, 'cash': 0})
    apr_pay[r[0]]['upi' if r[1] in ('upi','bank') else 'cash'] += float(r[2])

cur.execute("""
SELECT tenancy_id, SUM(amount) FROM payments
WHERE is_void=false AND payment_mode='cash' AND period_month='2026-05-01'
GROUP BY tenancy_id
""")
may_cash = {r[0]: float(r[1]) for r in cur.fetchall()}
cur.close(); conn.close()

def normalize_phone(ph):
    if not ph: return None
    ph = re.sub(r'\D', '', str(ph))
    if ph.startswith('91') and len(ph)==12: ph = ph[2:]
    return ph if len(ph)==10 else None

def name_tokens(s):
    return [p for p in re.sub(r'[^A-Z0-9 ]',' ',s.upper()).split() if len(p)>1]

def find_may_bank(name, phone, entries):
    tphone = normalize_phone(phone)
    name_up = name.strip().upper()
    tparts = name_tokens(name_up)
    if tphone:
        total = sum(e['amt'] for e in entries if e['phone']==tphone)
        if total > 0:
            for e in entries:
                if e['phone']==tphone: e['matched']=True
            return total
    for e in entries:
        if not e['matched'] and e['name']==name_up:
            e['matched']=True; return e['amt']
    if len(tparts)>=2:
        best,bi = 0,None
        for i,e in enumerate(entries):
            if e['matched']: continue
            bparts = name_tokens(e['name'])
            hits = sum(1 for tp in tparts if any(tp in bp or bp in tp for bp in bparts))
            score = hits/len(tparts)
            if hits>=2 and score>=0.6 and score>best: best,bi=score,i
        if bi is not None:
            entries[bi]['matched']=True; return entries[bi]['amt']
    return 0

def prorated(rent, days_in_month, checkin_day):
    days = days_in_month - checkin_day + 1
    return round((rent/days_in_month)*days), days

results = []
for row in tenants:
    name, phone, prop, rent, deposit, checkin, checkout, room, status, tid = row
    rent = float(rent or 0); deposit = float(deposit or 0)
    if isinstance(checkin, datetime.datetime): checkin = checkin.date()
    if isinstance(checkout, datetime.datetime): checkout = checkout.date()

    # April
    exited_pre_apr = checkout and checkout < datetime.date(2026,4,1)
    joined_apr = checkin and checkin.year==2026 and checkin.month==4
    if exited_pre_apr:
        apr_due = 0; apr_basis = 'exited'
    elif joined_apr:
        pr,d = prorated(rent,APR_DAYS,checkin.day)
        apr_due = deposit+pr; apr_basis = f'dep+pro({d}d)'
    else:
        apr_due = rent; apr_basis = 'full rent'
    ap = apr_pay.get(tid,{'upi':0,'cash':0})
    apr_upi, apr_cash = ap['upi'], ap['cash']
    apr_total = apr_upi+apr_cash; apr_bal = apr_due-apr_total

    # May
    exited_pre_may = checkout and checkout < datetime.date(2026,5,1)
    joined_may = checkin and checkin.year==2026 and checkin.month==5
    if exited_pre_may:
        may_due = 0; may_basis = 'exited'
    elif joined_may:
        pr,d = prorated(rent,MAY_DAYS,checkin.day)
        may_due = deposit+pr; may_basis = f'dep+pro({d}d)'
    else:
        may_due = rent; may_basis = 'full rent'
    may_upi = find_may_bank(name,phone,may_entries)
    may_cash_v = may_cash.get(tid,0)
    may_total = may_upi+may_cash_v; may_bal = may_due-may_total

    results.append(dict(
        prop=prop, name=name, room=room, rent=rent,
        apr_due=apr_due, apr_basis=apr_basis, apr_upi=apr_upi, apr_cash=apr_cash,
        apr_total=apr_total, apr_bal=apr_bal,
        may_due=may_due, may_basis=may_basis, may_upi=may_upi, may_cash=may_cash_v,
        may_total=may_total, may_bal=may_bal,
        combined=max(apr_bal,0)+may_bal
    ))

BUILDINGS = [
    ('HULK',[r for r in results if 'HULK' in r['prop']]),
    ('THOR',[r for r in results if 'THOR' in r['prop']]),
]

HDR = f"{'Name':<30} {'Rm':>4} {'Rent':>7} {'Due':>9} {'Basis':<16} {'UPI':>9} {'Cash':>9} {'Total':>8} {'Balance':>9}  Status"
W = 125

def print_month(rows, label, due_k, basis_k, upi_k, cash_k, total_k, bal_k):
    outstanding = [r for r in rows if r[due_k]>0 and r[bal_k]>0]
    if not outstanding:
        print(f'\n  {label} — all cleared')
        return
    outstanding.sort(key=lambda x: -x[bal_k])
    print(f'\n{"="*W}')
    print(f'  {label}  —  {len(outstanding)} tenants with balance outstanding')
    print(f'{"="*W}')
    print(HDR); print('-'*W)
    t_due=t_upi=t_cash=t_total=t_bal=0
    no_pay = [r for r in outstanding if r[total_k]==0]
    partial = [r for r in outstanding if r[total_k]>0]
    for section, rows_s in [('PARTIAL PAYMENT', partial), ('NO PAYMENT', no_pay)]:
        if not rows_s: continue
        print(f'  --- {section} ---')
        for r in rows_s:
            print(f"  {r['name']:<30} {r['room']:>4} {r['rent']:>7,.0f} {r[due_k]:>9,.0f} {r[basis_k]:<16} "
                  f"{r[upi_k]:>9,.0f} {r[cash_k]:>9,.0f} {r[total_k]:>8,.0f} {r[bal_k]:>9,.0f}  "
                  f"{'BAL '+str(int(r[bal_k])) if r[total_k]>0 else 'NO PAYMENT'}")
            t_due+=r[due_k]; t_upi+=r[upi_k]; t_cash+=r[cash_k]; t_total+=r[total_k]; t_bal+=r[bal_k]
    print('-'*W)
    print(f"  TOTAL  Due:{t_due:>9,.0f}  UPI:{t_upi:>9,.0f}  Cash:{t_cash:>9,.0f}  "
          f"Collected:{t_total:>9,.0f}  Outstanding:{t_bal:>9,.0f}")

for bname, brows in BUILDINGS:
    print(f'\n\n{"#"*80}\n##  {bname}\n{"#"*80}')
    print_month(brows, f'{bname} — APRIL 2026',
                'apr_due','apr_basis','apr_upi','apr_cash','apr_total','apr_bal')
    print_month(brows, f'{bname} — MAY 2026',
                'may_due','may_basis','may_upi','may_cash','may_total','may_bal')
    # Combined summary
    combined = [r for r in brows if r['combined']>0]
    combined.sort(key=lambda x: -x['combined'])
    if combined:
        print(f'\n{"="*70}')
        print(f'  {bname} — COMBINED OUTSTANDING (Apr + May carryover)')
        print(f'{"="*70}')
        print(f"  {'Name':<30} {'Room':>4} {'Apr Bal':>9} {'May Bal':>9} {'Total':>9}")
        print('-'*70)
        grand=0
        for r in combined:
            print(f"  {r['name']:<30} {r['room']:>4} {r['apr_bal']:>9,.0f} {r['may_bal']:>9,.0f} {r['combined']:>9,.0f}")
            grand+=r['combined']
        print('-'*70)
        print(f"  {'GRAND TOTAL':>46} {grand:>9,.0f}")
