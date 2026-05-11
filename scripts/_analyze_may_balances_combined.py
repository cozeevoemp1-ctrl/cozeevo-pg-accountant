"""
May 2026 final balance: bank (UPI) + cash payments combined.
- Bank: from HULK/THOR UPI statements (May 1-11)
- Cash: from DB payments table (payment_mode='cash', period_month=2026-05)
- Balance = amount_due - bank_paid - cash_paid
"""
import os, csv, datetime, re
from dotenv import load_dotenv
load_dotenv()
db_url = os.environ['DATABASE_URL'].replace('postgresql+asyncpg://', 'postgresql://')
import psycopg2, openpyxl

MAY_DAYS = 31

# ── 1. Bank statements ───────────────────────────────────────────────────────

def extract_phone(upi_id):
    m = re.match(r'^(\d{10})(?:-\d+)?@', str(upi_id))
    return m.group(1) if m else None

hulk_entries = []
wb = openpyxl.load_workbook('Hulk may 11th bank statement.xlsx')
ws = wb.active
for row in ws.iter_rows(min_row=2, values_only=True):
    if row[11] == 'SUCCESS' and row[3]:
        hulk_entries.append({'amt': float(row[3]), 'phone': extract_phone(row[7]), 'name': str(row[8]).strip().upper(), 'matched': False, 'bank': 'HULK'})

thor_entries = []
with open('thor may 11th.csv', newline='') as f:
    reader = csv.DictReader(f)
    for row in reader:
        if row['Settlement_Status'] == 'SUCCESS' and row['TXN_AMOUNT']:
            thor_entries.append({'amt': float(row['TXN_AMOUNT']), 'phone': extract_phone(row['Payer_VPA']), 'name': row['Payer_Name'].strip().upper(), 'matched': False, 'bank': 'THOR'})

all_entries = hulk_entries + thor_entries

# ── 2. DB data ───────────────────────────────────────────────────────────────

conn = psycopg2.connect(db_url)
cur = conn.cursor()

# Tenants
cur.execute("""
SELECT t.name, t.phone, p.name, tn.agreed_rent, tn.security_deposit,
       tn.checkin_date, tn.checkout_date, r.room_number, tn.status, tn.id
FROM tenancies tn
JOIN tenants t ON t.id = tn.tenant_id
JOIN rooms r ON r.id = tn.room_id
JOIN properties p ON p.id = r.property_id
WHERE tn.status = 'active'
   OR (tn.checkout_date >= '2026-05-01' AND tn.checkout_date <= '2026-05-11' AND tn.status = 'exited')
ORDER BY p.name, t.name
""")
tenants = cur.fetchall()

# Cash payments for May 2026
cur.execute("""
SELECT tenancy_id, SUM(amount)
FROM payments
WHERE is_void = false
  AND payment_mode = 'cash'
  AND period_month = '2026-05-01'
GROUP BY tenancy_id
""")
db_cash = {r[0]: float(r[1]) for r in cur.fetchall()}

cur.close()
conn.close()

# ── 3. Helpers ───────────────────────────────────────────────────────────────

def normalize_phone(ph):
    if not ph: return None
    ph = re.sub(r'\D', '', str(ph))
    if ph.startswith('91') and len(ph) == 12: ph = ph[2:]
    return ph if len(ph) == 10 else None

def name_tokens(s):
    return [p for p in re.sub(r'[^A-Z0-9 ]', ' ', s.upper()).split() if len(p) > 1]

def find_bank_match(tenant_name, tenant_phone, entries):
    tphone = normalize_phone(tenant_phone)
    name_up = tenant_name.strip().upper()
    tparts = name_tokens(name_up)

    # Pass 1: phone
    if tphone:
        total = 0
        for e in entries:
            if e['phone'] == tphone:
                total += e['amt']
                e['matched'] = True
        if total > 0:
            return total, f'phone'

    # Pass 2: exact name
    for e in entries:
        if not e['matched'] and e['name'] == name_up:
            e['matched'] = True
            return e['amt'], 'exact'

    # Pass 3: partial name (2+ tokens, 60%+ match)
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
            e = entries[best_idx]
            e['matched'] = True
            return e['amt'], 'name'

    return 0, None

# ── 4. Build results ─────────────────────────────────────────────────────────

results = []
for row in tenants:
    name, phone, prop, rent, deposit, checkin, checkout, room, status, tenancy_id = row
    rent = float(rent or 0)
    deposit = float(deposit or 0)
    if isinstance(checkin, datetime.datetime): checkin_date = checkin.date()
    else: checkin_date = checkin

    joined_this_month = checkin_date and checkin_date.year == 2026 and checkin_date.month == 5

    if joined_this_month:
        days = MAY_DAYS - checkin_date.day + 1
        prorated = round((rent / MAY_DAYS) * days)
        amount_due = deposit + prorated
        due_basis = f'dep+prorated({days}d)'
    else:
        amount_due = rent
        due_basis = 'full rent'

    bank_paid, match_method = find_bank_match(name, phone, all_entries)
    cash_paid = db_cash.get(tenancy_id, 0)
    total_paid = bank_paid + cash_paid
    balance = amount_due - total_paid

    results.append(dict(
        prop=prop, name=name, phone=phone, room=room, rent=rent,
        checkin=checkin_date, amount_due=amount_due, due_basis=due_basis,
        bank_paid=bank_paid, cash_paid=cash_paid, total_paid=total_paid,
        balance=balance, tenancy_id=tenancy_id
    ))

hulk_results = [r for r in results if 'HULK' in r['prop']]
thor_results = [r for r in results if 'THOR' in r['prop']]

# ── 5. Print ─────────────────────────────────────────────────────────────────

def print_building(results, label):
    print()
    print('=' * 135)
    print(f'  {label}')
    print('=' * 135)
    hdr = f"{'Name':<32} {'Room':>5} {'Rent':>8} {'Joined':>12} {'Due':>10} {'Basis':<22} {'BankPaid':>10} {'CashPaid':>10} {'Total':>8} {'Balance':>10}  Status"
    print(hdr)
    print('-' * 135)

    outstanding = []
    no_payment = []
    cleared = []

    for r in results:
        joined = str(r['checkin']) if r['checkin'] else '?'
        bal = r['balance']
        if bal <= 0:
            status = 'CLEAR'
            cleared.append(r)
        elif r['total_paid'] == 0:
            status = 'NO PAYMENT'
            no_payment.append(r)
        else:
            status = f'BAL {int(bal):,}'
            outstanding.append(r)

        line = (
            f"{r['name']:<32} {r['room']:>5} {r['rent']:>8,.0f} {joined:>12} "
            f"{r['amount_due']:>10,.0f} {r['due_basis']:<22} {r['bank_paid']:>10,.0f} "
            f"{r['cash_paid']:>10,.0f} {r['total_paid']:>8,.0f} {r['balance']:>10,.0f}  {status}"
        )
        print(line)

    print()
    total_due = sum(r['amount_due'] for r in results)
    total_bank = sum(r['bank_paid'] for r in results)
    total_cash = sum(r['cash_paid'] for r in results)
    total_collected = sum(r['total_paid'] for r in results)
    total_balance = sum(r['balance'] for r in results)
    print(f"  Summary: {len(cleared)} cleared | {len(outstanding)} partial | {len(no_payment)} no payment")
    print(f"  Total due: {total_due:,.0f} | Bank: {total_bank:,.0f} | Cash: {total_cash:,.0f} | Total collected: {total_collected:,.0f} | Outstanding: {total_balance:,.0f}")

    if no_payment:
        print()
        print("  NO PAYMENT (neither bank nor cash recorded):")
        for r in sorted(no_payment, key=lambda x: -x['amount_due']):
            print(f"    {r['name']:<32}  {r['phone']}  room {r['room']}  due={r['amount_due']:,.0f}  ({r['due_basis']})")

    if outstanding:
        print()
        print("  OUTSTANDING BALANCE:")
        for r in sorted(outstanding, key=lambda x: -x['balance']):
            print(f"    {r['name']:<32}  {r['phone']}  room {r['room']}  due={r['amount_due']:,.0f}  bank={r['bank_paid']:,.0f}  cash={r['cash_paid']:,.0f}  balance={r['balance']:,.0f}")

print_building(hulk_results, 'HULK')
print_building(thor_results, 'THOR')
