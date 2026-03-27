"""Generate monthly report from original Google Sheet."""
import sys, re
sys.stdout.reconfigure(encoding='utf-8')
from datetime import date, datetime
import gspread
from google.oauth2.service_account import Credentials

creds = Credentials.from_service_account_file(
    'credentials/gsheets_service_account.json',
    scopes=['https://www.googleapis.com/auth/spreadsheets'])
gc = gspread.authorize(creds)
ws = gc.open_by_key('1T4YE7RK2eIZRg330kaOaNb5-8o8kJbxpDzK_7MfoyiA').worksheet('History')
rows = ws.get_all_values()

def pn(v):
    if not v: return 0.0
    s = str(v).strip().replace(',', '')
    m = re.search(r'[\d.]+', s)
    return float(m.group()) if m else 0.0

def pd(v):
    if not v or not str(v).strip(): return None
    s = str(v).strip()
    for fmt in ('%d-%m-%Y', '%d-%m-%y', '%Y-%m-%d', '%d/%m/%Y', '%d/%m/%y'):
        try: return datetime.strptime(s, fmt).date()
        except: continue
    return None

def st(v):
    s = str(v).strip().upper()
    if s in ('CHECKIN', 'CHECK IN', ''): return 'Active'
    if 'EXIT' in s: return 'Exited'
    if 'NO SHOW' in s: return 'No-show'
    if 'CANCEL' in s: return 'Cancelled'
    return 'Active'

tenants = []
for row in rows[1:]:
    if not row[1].strip(): continue
    while len(row) < 42: row.append('')
    rent = pn(row[9])
    rf, rm = pn(row[10]), pn(row[11])
    if rm > 0: rent = rm
    elif rf > 0: rent = rf
    tenants.append({
        'name': row[1].strip(), 'room': row[0].strip(), 'block': row[17].strip(),
        'sharing': row[12].strip().lower(), 'status': st(row[16]),
        'checkin': pd(row[4]), 'rent': rent,
        'jan_cash': pn(row[23]), 'jan_upi': pn(row[24]),
        'feb_cash': pn(row[28]), 'feb_upi': pn(row[29]),
        'mar_cash': pn(row[31]), 'mar_upi': pn(row[32]),
    })

TOTAL_BEDS = 291

print('=' * 90)
print('COZEEVO MONTHLY REPORT')
print('=' * 90)

months = [
    ('JANUARY 2026',  date(2026,1,1),  date(2026,1,31),  'jan_cash', 'jan_upi'),
    ('FEBRUARY 2026', date(2026,2,1),  date(2026,2,28),  'feb_cash', 'feb_upi'),
    ('MARCH 2026',    date(2026,3,1),  date(2026,3,31),  'mar_cash', 'mar_upi'),
]

for label, m_start, m_end, ck, uk in months:
    print(f'\n{"─"*90}')
    print(f'  {label}')
    print(f'{"─"*90}')

    # Occupancy: active tenants checked in by month end
    occ = [t for t in tenants if t['status'] == 'Active' and t['checkin'] and t['checkin'] <= m_end]
    prem = [t for t in occ if t['sharing'] == 'premium']
    reg = len(occ) - len(prem)
    beds = reg + len(prem) * 2
    ns = len([t for t in tenants if t['status'] == 'No-show'])
    vacant = TOTAL_BEDS - beds - ns

    # THOR/HULK
    thor = [t for t in occ if t['block'] == 'THOR']
    hulk = [t for t in occ if t['block'] == 'HULK']
    tp = sum(1 for t in thor if t['sharing'] == 'premium')
    hp = sum(1 for t in hulk if t['sharing'] == 'premium')
    tb = (len(thor) - tp) + tp * 2
    hb = (len(hulk) - hp) + hp * 2
    tc = sum(t[ck] for t in tenants if t['block'] == 'THOR')
    tu = sum(t[uk] for t in tenants if t['block'] == 'THOR')
    hc = sum(t[ck] for t in tenants if t['block'] == 'HULK')
    hu = sum(t[uk] for t in tenants if t['block'] == 'HULK')

    # Collections: raw column sums
    total_cash = sum(t[ck] for t in tenants)
    total_upi = sum(t[uk] for t in tenants)
    total_coll = total_cash + total_upi

    # Dues: active, checkin < month_start, rent - paid > 0
    scoped = [t for t in tenants if t['status'] == 'Active' and t['checkin'] and t['checkin'] < m_start]
    rent_exp = sum(t['rent'] for t in scoped)
    dues = []
    for t in scoped:
        paid = t[ck] + t[uk]
        due = t['rent'] - paid
        if due > 0:
            dues.append((t['name'], t['room'], t['block'], t['rent'], paid, due))
    total_dues = sum(d[5] for d in dues)

    paid_c = sum(1 for t in scoped if t[ck] + t[uk] >= t['rent'])
    part_c = sum(1 for t in scoped if 0 < t[ck] + t[uk] < t['rent'])
    unpaid_c = sum(1 for t in scoped if t[ck] + t[uk] == 0)

    print(f'')
    print(f'  OCCUPANCY                          COLLECTIONS')
    print(f'  Revenue Beds:  {TOTAL_BEDS:>5}               Cash:        Rs.{total_cash:>10,.0f}')
    print(f'  Checked-in:    {beds:>5} beds            UPI:         Rs.{total_upi:>10,.0f}')
    print(f'    Regular:     {reg:>5}               Total:       Rs.{total_coll:>10,.0f}')
    print(f'    Premium:     {len(prem):>5}')
    print(f'  No-show:       {ns:>5}               DUES (checkin < {m_start})')
    print(f'  Vacant:        {vacant:>5}               Tenants:     {len(scoped):>5}')
    print(f'  Occupancy:     {beds/TOTAL_BEDS*100:>5.1f}%             Rent expected: Rs.{rent_exp:>10,.0f}')
    print(f'                                      Paid: {paid_c}  Partial: {part_c}  Unpaid: {unpaid_c}')
    print(f'  THOR: {tb} beds ({len(thor)}t)            Outstanding: Rs.{total_dues:>10,.0f}  ({len(dues)} tenants)')
    print(f'    Cash Rs.{tc:>10,.0f}')
    print(f'    UPI  Rs.{tu:>10,.0f}')
    print(f'  HULK: {hb} beds ({len(hulk)}t)')
    print(f'    Cash Rs.{hc:>10,.0f}')
    print(f'    UPI  Rs.{hu:>10,.0f}')

    if dues:
        print(f'')
        print(f'  WHO OWES:')
        dues.sort(key=lambda x: -x[5])
        for name, room, blk, rent, paid, due in dues[:15]:
            print(f'    {name:25s} {room:6s} {blk:5s} Rent:{rent:>8,.0f} Paid:{paid:>8,.0f} DUE:{due:>8,.0f}')
        if len(dues) > 15:
            print(f'    ... and {len(dues)-15} more')

print(f'\n{"="*90}')
print(f'VALIDATION (raw column sums)')
print(f'  Jan Cash: {sum(t["jan_cash"] for t in tenants):>10,.0f}   Jan UPI: {sum(t["jan_upi"] for t in tenants):>10,.0f}')
print(f'  Feb Cash: {sum(t["feb_cash"] for t in tenants):>10,.0f}   Feb UPI: {sum(t["feb_upi"] for t in tenants):>10,.0f}')
print(f'  Mar Cash: {sum(t["mar_cash"] for t in tenants):>10,.0f}   Mar UPI: {sum(t["mar_upi"] for t in tenants):>10,.0f}')
print(f'  Total tenants: {len(tenants)}  Active: {sum(1 for t in tenants if t["status"]=="Active")}  Exited: {sum(1 for t in tenants if t["status"]=="Exited")}  No-show: {sum(1 for t in tenants if t["status"]=="No-show")}')
