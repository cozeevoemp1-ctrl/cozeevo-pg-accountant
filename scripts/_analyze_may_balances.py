"""
May 2026 balance analysis: bank statements vs tenant rent.
- Combines HULK + THOR UPI collections (tenants may pay into either)
- Matches by phone first (extracted from UPI ID), then by name
- Each bank payment matched to at most ONE tenant
"""
import os, csv, datetime, re
from dotenv import load_dotenv
load_dotenv()
db_url = os.environ['DATABASE_URL'].replace('postgresql+asyncpg://', 'postgresql://')
import psycopg2, openpyxl

MAY_DAYS = 31

# ── 1. Load bank statements ──────────────────────────────────────────────────

def extract_phone(upi_id):
    """Extract 10-digit phone from UPI ID like 9012345678@bank or 9012345678-2@bank"""
    m = re.match(r'^(\d{10})(?:-\d+)?@', upi_id)
    if m:
        return m.group(1)
    return None

def load_payments(rows):
    """rows: list of (amount, upi_id, payer_name)"""
    entries = []
    for amt, upi_id, name in rows:
        phone = extract_phone(str(upi_id)) if upi_id else None
        entries.append({'amt': float(amt), 'phone': phone, 'name': str(name).strip().upper(), 'matched': False})
    return entries

hulk_entries = []
wb = openpyxl.load_workbook('Hulk may 11th bank statement.xlsx')
ws = wb.active
for row in ws.iter_rows(min_row=2, values_only=True):
    if row[11] == 'SUCCESS' and row[3]:
        hulk_entries.append({'amt': float(row[3]), 'phone': extract_phone(str(row[7])), 'name': str(row[8]).strip().upper(), 'matched': False, 'bank': 'HULK'})

thor_entries = []
with open('thor may 11th.csv', newline='') as f:
    reader = csv.DictReader(f)
    for row in reader:
        if row['Settlement_Status'] == 'SUCCESS' and row['TXN_AMOUNT']:
            thor_entries.append({'amt': float(row['TXN_AMOUNT']), 'phone': extract_phone(row['Payer_VPA']), 'name': row['Payer_Name'].strip().upper(), 'matched': False, 'bank': 'THOR'})

all_entries = hulk_entries + thor_entries
print(f'HULK transactions: {len(hulk_entries)} | THOR transactions: {len(thor_entries)} | Total: {len(all_entries)}')

# ── 2. Get tenants from DB ───────────────────────────────────────────────────

conn = psycopg2.connect(db_url)
cur = conn.cursor()

cur.execute("""
SELECT
    t.name,
    t.phone,
    p.name as property_name,
    tn.agreed_rent,
    tn.security_deposit,
    tn.checkin_date,
    tn.checkout_date,
    r.room_number,
    tn.status,
    tn.id as tenancy_id
FROM tenancies tn
JOIN tenants t ON t.id = tn.tenant_id
JOIN rooms r ON r.id = tn.room_id
JOIN properties p ON p.id = r.property_id
WHERE tn.status = 'active'
   OR (tn.checkout_date >= '2026-05-01' AND tn.checkout_date <= '2026-05-11' AND tn.status = 'exited')
ORDER BY p.name, t.name
""")
tenants = cur.fetchall()

cur.execute("""
SELECT tenancy_id, SUM(amount)
FROM payments
WHERE is_void = false
  AND period_month = '2026-05-01'
GROUP BY tenancy_id
""")
db_may_payments = {r[0]: float(r[1]) for r in cur.fetchall()}
cur.close()
conn.close()

print(f'Active + May-exit tenants: {len(tenants)}')

# ── 3. Normalize phone helper ────────────────────────────────────────────────

def normalize_phone(ph):
    if not ph:
        return None
    ph = re.sub(r'\D', '', str(ph))
    if ph.startswith('91') and len(ph) == 12:
        ph = ph[2:]
    return ph if len(ph) == 10 else None

# ── 4. Match each tenant to bank entries ────────────────────────────────────

def name_tokens(s):
    """Split name into meaningful tokens (2+ chars)"""
    return [p for p in re.sub(r'[^A-Z0-9 ]', ' ', s.upper()).split() if len(p) > 1]

def find_match(tenant_name, tenant_phone, entries):
    tphone = normalize_phone(tenant_phone)
    name_up = tenant_name.strip().upper()
    tparts = name_tokens(name_up)

    # Pass 1: phone match (high confidence) — collects all payments from same phone
    if tphone:
        total = 0
        for e in entries:
            if e['phone'] == tphone:
                total += e['amt']
                e['matched'] = True
        if total > 0:
            return total, f'phone:{tphone}'

    # Pass 2: exact name match
    for e in entries:
        if not e['matched'] and e['name'] == name_up:
            e['matched'] = True
            return e['amt'], f'exact:{e["name"]}'

    # Pass 3: strong partial name match (avoid false positives)
    # Require: at least 2 tenant tokens found in bank name AND covers >= 60% of tenant tokens
    if len(tparts) >= 2:
        best_score = 0
        best_idx = None
        for i, e in enumerate(entries):
            if e['matched']:
                continue
            bparts = name_tokens(e['name'])
            hits = sum(1 for tp in tparts if any(tp in bp or bp in tp for bp in bparts))
            score = hits / len(tparts)
            if hits >= 2 and score >= 0.6 and score > best_score:
                best_score = score
                best_idx = i
        if best_idx is not None:
            e = entries[best_idx]
            e['matched'] = True
            return e['amt'], f'name:{e["name"]}'

    return 0, None

# First pass: phone matches (definitive)
results = []
for row in tenants:
    name, phone, prop, rent, deposit, checkin, checkout, room, status, tenancy_id = row
    rent = float(rent or 0)
    deposit = float(deposit or 0)
    if isinstance(checkin, datetime.datetime):
        checkin_date = checkin.date()
    else:
        checkin_date = checkin

    joined_this_month = checkin_date and checkin_date.year == 2026 and checkin_date.month == 5

    if joined_this_month:
        days_staying = MAY_DAYS - checkin_date.day + 1
        prorated_rent = round((rent / MAY_DAYS) * days_staying)
        amount_due = deposit + prorated_rent
        due_basis = f'dep+prorated({days_staying}d)'
    else:
        amount_due = rent
        due_basis = 'full rent'

    bank_paid, match_method = find_match(name, phone, all_entries)
    db_paid = db_may_payments.get(tenancy_id, 0)
    balance = amount_due - bank_paid

    results.append(dict(
        prop=prop, name=name, phone=phone, room=room, rent=rent,
        checkin=checkin_date, amount_due=amount_due, due_basis=due_basis,
        bank_paid=bank_paid, db_paid=db_paid, balance=balance,
        tenancy_id=tenancy_id, match_method=match_method
    ))

hulk_results = [r for r in results if 'HULK' in r['prop']]
thor_results = [r for r in results if 'THOR' in r['prop']]

# ── 5. Print report ──────────────────────────────────────────────────────────

def print_building(results, label):
    print()
    print('=' * 125)
    print(f'  {label}')
    print('=' * 125)
    hdr = f"{'Name':<32} {'Room':>6} {'Rent':>8} {'Joined':>12} {'Due':>10} {'Basis':<24} {'BankPaid':>10} {'DBPaid':>8} {'Balance':>10}  Status"
    print(hdr)
    print('-' * 125)

    outstanding = []
    no_payment = []
    cleared = []

    for r in results:
        joined = str(r['checkin']) if r['checkin'] else '?'
        bal = r['balance']
        if bal <= 0:
            status = 'CLEAR'
            cleared.append(r)
        elif r['bank_paid'] == 0:
            status = 'NO PAYMENT'
            no_payment.append(r)
        else:
            status = f'BAL {bal:,.0f}'
            outstanding.append(r)

        line = (
            f"{r['name']:<32} {r['room']:>6} {r['rent']:>8,.0f} {joined:>12} "
            f"{r['amount_due']:>10,.0f} {r['due_basis']:<24} {r['bank_paid']:>10,.0f} "
            f"{r['db_paid']:>8,.0f} {r['balance']:>10,.0f}  {status}"
        )
        print(line)

    print()
    total_due = sum(r['amount_due'] for r in results)
    total_paid = sum(r['bank_paid'] for r in results)
    total_balance = sum(r['balance'] for r in results)
    print(f"  Summary: {len(cleared)} cleared | {len(outstanding)} partial | {len(no_payment)} no payment")
    print(f"  Total due: {total_due:,.0f}  |  Collected (bank): {total_paid:,.0f}  |  Outstanding: {total_balance:,.0f}")

    if no_payment:
        print()
        print("  NO PAYMENT:")
        for r in sorted(no_payment, key=lambda x: x['name']):
            print(f"    {r['name']:<32}  {r['phone']}  due={r['amount_due']:,.0f}  ({r['due_basis']})")

    if outstanding:
        print()
        print("  OUTSTANDING BALANCE (sorted by amount):")
        for r in sorted(outstanding, key=lambda x: -x['balance']):
            print(f"    {r['name']:<32}  {r['phone']}  due={r['amount_due']:,.0f}  paid={r['bank_paid']:,.0f}  balance={r['balance']:,.0f}")

print_building(hulk_results, 'HULK')
print_building(thor_results, 'THOR')

# ── 6. Unmatched bank entries ────────────────────────────────────────────────

unmatched = [e for e in all_entries if not e['matched']]
if unmatched:
    print()
    print('=' * 80)
    print(f'UNMATCHED bank entries ({len(unmatched)} transactions — not linked to any active tenant):')
    print('-' * 80)
    total_unmatched = 0
    for e in sorted(unmatched, key=lambda x: -x['amt']):
        print(f"  [{e['bank']}] {e['name']:<45} {e['amt']:>10,.0f}  UPI:{e['phone'] or '?'}")
        total_unmatched += e['amt']
    print(f"\n  Total unmatched: {total_unmatched:,.0f}")
