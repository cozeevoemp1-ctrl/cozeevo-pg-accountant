"""
April + May 2026 outstanding balance per tenant.

April paid:
  - Primary: payments table (period_month=2026-04-01, both UPI + cash) — imported from source sheet
  - Supplemental: bank_transactions table (income entries Apr 1-30) matched by phone in description

May paid:
  - UPI: HULK/THOR bank statement files (May 1-11)
  - Cash: payments table (period_month=2026-05-01, payment_mode='cash')

Output: 1 table per month + combined total outstanding.
"""
import os, csv, datetime, re
from dotenv import load_dotenv
load_dotenv()
db_url = os.environ['DATABASE_URL'].replace('postgresql+asyncpg://', 'postgresql://')
import psycopg2, openpyxl

APR_DAYS = 30
MAY_DAYS = 31

# ── 1. May bank statements (files) ──────────────────────────────────────────

def extract_phone(upi_id):
    m = re.match(r'^(\d{10})(?:-\d+)?@', str(upi_id))
    return m.group(1) if m else None

hulk_entries = []
wb = openpyxl.load_workbook('Hulk may 11th bank statement.xlsx')
for row in wb.worksheets[0].iter_rows(min_row=2, values_only=True):
    if row[11] == 'SUCCESS' and row[3]:
        hulk_entries.append({'amt': float(row[3]), 'phone': extract_phone(row[7]),
                              'name': str(row[8]).strip().upper(), 'matched': False, 'bank': 'HULK'})

thor_entries = []
with open('thor may 11th.csv', newline='') as f:
    reader = csv.DictReader(f)
    for row in reader:
        if row['Settlement_Status'] == 'SUCCESS' and row['TXN_AMOUNT']:
            thor_entries.append({'amt': float(row['TXN_AMOUNT']), 'phone': extract_phone(row['Payer_VPA']),
                                  'name': row['Payer_Name'].strip().upper(), 'matched': False, 'bank': 'THOR'})

may_entries = hulk_entries + thor_entries

# ── 2. DB data ───────────────────────────────────────────────────────────────

conn = psycopg2.connect(db_url)
cur = conn.cursor()

# All relevant tenants: active + exited in Apr or May
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

# April payments from payments table (UPI + cash)
cur.execute("""
SELECT tenancy_id, payment_mode, SUM(amount)
FROM payments
WHERE is_void = false AND period_month = '2026-04-01'
GROUP BY tenancy_id, payment_mode
""")
apr_pay = {}
for r in cur.fetchall():
    apr_pay.setdefault(r[0], {'upi': 0, 'cash': 0})
    mode = 'upi' if r[1] in ('upi', 'bank') else 'cash'
    apr_pay[r[0]][mode] += float(r[2])

# April bank_transactions income (description may contain phone or name)
cur.execute("""
SELECT description, amount
FROM bank_transactions
WHERE txn_type = 'income'
  AND txn_date >= '2026-04-01' AND txn_date <= '2026-04-30'
  AND account_name IN ('THOR', 'HULK')
""")
apr_bank_txns = cur.fetchall()  # (description, amount) — for supplemental cross-check

# May cash payments from payments table
cur.execute("""
SELECT tenancy_id, SUM(amount)
FROM payments
WHERE is_void = false AND payment_mode = 'cash' AND period_month = '2026-05-01'
GROUP BY tenancy_id
""")
may_cash = {r[0]: float(r[1]) for r in cur.fetchall()}

cur.close()
conn.close()

print(f'Tenants: {len(tenants)} | Apr bank txns: {len(apr_bank_txns)} | May entries: {len(may_entries)}')

# ── 3. Helpers ───────────────────────────────────────────────────────────────

def normalize_phone(ph):
    if not ph: return None
    ph = re.sub(r'\D', '', str(ph))
    if ph.startswith('91') and len(ph) == 12: ph = ph[2:]
    return ph if len(ph) == 10 else None

def name_tokens(s):
    return [p for p in re.sub(r'[^A-Z0-9 ]', ' ', s.upper()).split() if len(p) > 1]

def find_may_bank(tenant_name, tenant_phone, entries):
    tphone = normalize_phone(tenant_phone)
    name_up = tenant_name.strip().upper()
    tparts = name_tokens(name_up)

    if tphone:
        total = 0
        for e in entries:
            if e['phone'] == tphone:
                total += e['amt']
                e['matched'] = True
        if total > 0:
            return total

    for e in entries:
        if not e['matched'] and e['name'] == name_up:
            e['matched'] = True
            return e['amt']

    if len(tparts) >= 2:
        best_score, best_idx = 0, None
        for i, e in enumerate(entries):
            if e['matched']: continue
            bparts = name_tokens(e['name'])
            hits = sum(1 for tp in tparts if any(tp in bp or bp in tp for bp in bparts))
            score = hits / len(tparts)
            if hits >= 2 and score >= 0.6 and score > best_score:
                best_score, best_idx = score, i
        if best_idx is not None:
            entries[best_idx]['matched'] = True
            return entries[best_idx]['amt']

    return 0

def check_apr_bank_txns(tenant_phone, tenant_name, txns):
    """Supplemental: scan bank_transactions description for phone or name."""
    tphone = normalize_phone(tenant_phone)
    name_up = tenant_name.strip().upper()
    tparts = name_tokens(name_up)
    found = 0
    for desc, amt in txns:
        desc_up = desc.upper()
        if tphone and tphone in desc_up:
            found += float(amt)
        elif len(tparts) >= 2:
            hits = sum(1 for tp in tparts if tp in desc_up)
            if hits >= 2:
                found += float(amt)
    return found

def prorated(rent, days_in_month, checkin_day):
    days = days_in_month - checkin_day + 1
    return round((rent / days_in_month) * days), days

# ── 4. Build results ─────────────────────────────────────────────────────────

results = []
for row in tenants:
    name, phone, prop, rent, deposit, checkin, checkout, room, status, tenancy_id = row
    rent = float(rent or 0)
    deposit = float(deposit or 0)
    if isinstance(checkin, datetime.datetime): checkin_date = checkin.date()
    else: checkin_date = checkin
    if isinstance(checkout, datetime.datetime): checkout_date = checkout.date()
    else: checkout_date = checkout

    # ── April ────────────────────────────────────────────────────────────────
    joined_apr = checkin_date and checkin_date.year == 2026 and checkin_date.month == 4
    exited_before_apr = checkout_date and checkout_date < datetime.date(2026, 4, 1)

    if exited_before_apr:
        apr_due = 0
        apr_basis = 'exited before Apr'
    elif checkin_date and checkin_date >= datetime.date(2026, 5, 1):
        apr_due = 0
        apr_basis = 'joined in May'
    elif joined_apr:
        pr, days = prorated(rent, APR_DAYS, checkin_date.day)
        apr_due = deposit + pr
        apr_basis = f'dep+prorated({days}d)'
    else:
        apr_due = rent
        apr_basis = 'full rent'

    apr_db = apr_pay.get(tenancy_id, {'upi': 0, 'cash': 0})
    apr_upi_db = apr_db['upi']
    apr_cash_db = apr_db['cash']
    apr_total_db = apr_upi_db + apr_cash_db

    # supplemental: check bank_transactions description
    apr_bank_supp = check_apr_bank_txns(phone, name, apr_bank_txns)
    # only use supplemental if it's more than what DB has (avoid double-count)
    apr_upi_final = max(apr_upi_db, apr_bank_supp) if apr_bank_supp > apr_upi_db else apr_upi_db
    apr_total = apr_upi_final + apr_cash_db
    apr_balance = apr_due - apr_total

    # ── May ──────────────────────────────────────────────────────────────────
    joined_may = checkin_date and checkin_date.year == 2026 and checkin_date.month == 5
    exited_before_may = checkout_date and checkout_date < datetime.date(2026, 5, 1)

    if exited_before_may:
        may_due = 0
        may_basis = 'exited before May'
    elif joined_may:
        pr, days = prorated(rent, MAY_DAYS, checkin_date.day)
        may_due = deposit + pr
        may_basis = f'dep+prorated({days}d)'
    else:
        may_due = rent
        may_basis = 'full rent'

    may_upi = find_may_bank(name, phone, may_entries)
    may_cash_val = may_cash.get(tenancy_id, 0)
    may_total = may_upi + may_cash_val
    may_balance = may_due - may_total

    total_outstanding = max(apr_balance, 0) + may_balance  # don't subtract overpayments from other month

    results.append(dict(
        prop=prop, name=name, phone=phone, room=room, rent=rent,
        checkin=checkin_date, checkout=checkout_date,
        # April
        apr_due=apr_due, apr_basis=apr_basis,
        apr_upi=apr_upi_final, apr_cash=apr_cash_db, apr_total=apr_total, apr_balance=apr_balance,
        # May
        may_due=may_due, may_basis=may_basis,
        may_upi=may_upi, may_cash=may_cash_val, may_total=may_total, may_balance=may_balance,
        # Combined
        total_outstanding=total_outstanding,
        tenancy_id=tenancy_id
    ))

# ── 5. Print ─────────────────────────────────────────────────────────────────

BUILDINGS = [
    ('HULK', [r for r in results if 'HULK' in r['prop']]),
    ('THOR', [r for r in results if 'THOR' in r['prop']]),
]

def print_month_table(rows, month_label, due_key, basis_key, upi_key, cash_key, total_key, bal_key):
    W = 140
    print()
    print('=' * W)
    print(f'  {month_label}')
    print('=' * W)
    hdr = f"{'Name':<32} {'Room':>5} {'Rent':>8} {'Due':>10} {'Basis':<22} {'UPI':>10} {'Cash':>10} {'Total':>8} {'Balance':>10}  Status"
    print(hdr)
    print('-' * W)

    cleared = outstanding = no_payment = 0
    t_due = t_upi = t_cash = t_total = t_bal = 0

    for r in rows:
        bal = r[bal_key]
        due = r[due_key]
        total = r[total_key]
        t_due += due; t_upi += r[upi_key]; t_cash += r[cash_key]; t_total += total; t_bal += bal

        if due == 0:
            status = 'N/A'
        elif bal <= 0:
            status = 'CLEAR'
            cleared += 1
        elif total == 0:
            status = 'NO PAYMENT'
            no_payment += 1
        else:
            status = f'BAL {int(bal):,}'
            outstanding += 1

        print(f"{r['name']:<32} {r['room']:>5} {r['rent']:>8,.0f} {due:>10,.0f} "
              f"{r[basis_key]:<22} {r[upi_key]:>10,.0f} {r[cash_key]:>10,.0f} "
              f"{total:>8,.0f} {bal:>10,.0f}  {status}")

    print()
    print(f"  Total due: {t_due:,.0f} | UPI: {t_upi:,.0f} | Cash: {t_cash:,.0f} | "
          f"Collected: {t_total:,.0f} | Outstanding: {t_bal:,.0f}")
    print(f"  {cleared} cleared | {outstanding} partial | {no_payment} no payment")
    return t_due, t_upi, t_cash, t_total, t_bal

def print_combined_summary(rows, label):
    W = 80
    print()
    print('=' * W)
    print(f'  {label} — COMBINED OUTSTANDING (April + May)')
    print('=' * W)
    print(f"  {'Name':<32} {'Room':>5} {'Apr Bal':>10} {'May Bal':>10} {'Total':>10}")
    print('-' * W)
    grand = 0
    for r in sorted(rows, key=lambda x: -x['total_outstanding']):
        if r['total_outstanding'] <= 0 and r['apr_balance'] <= 0 and r['may_balance'] <= 0:
            continue
        print(f"  {r['name']:<32} {r['room']:>5} {r['apr_balance']:>10,.0f} "
              f"{r['may_balance']:>10,.0f} {r['total_outstanding']:>10,.0f}")
        grand += r['total_outstanding']
    print('-' * W)
    print(f"  {'GRAND TOTAL':>40} {grand:>32,.0f}")

for bname, brows in BUILDINGS:
    print(f'\n\n{"#"*80}')
    print(f'##  {bname}')
    print(f'{"#"*80}')

    print_month_table(brows, f'{bname} — APRIL 2026',
                      'apr_due', 'apr_basis', 'apr_upi', 'apr_cash', 'apr_total', 'apr_balance')
    print_month_table(brows, f'{bname} — MAY 2026',
                      'may_due', 'may_basis', 'may_upi', 'may_cash', 'may_total', 'may_balance')
    print_combined_summary(brows, bname)
