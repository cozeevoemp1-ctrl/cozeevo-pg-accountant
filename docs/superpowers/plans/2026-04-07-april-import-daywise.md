# April Import + Day-wise Stays Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Import April payment data from `april month.xlsx` into DB + Sheet, and consolidate day-wise (short-stay) data from both Excel files into a new DB table + Google Sheet tab.

**Architecture:** Two new scripts: `scripts/import_april.py` (monthly delta updater) and `scripts/import_daywise.py` (short-stay loader). Both are standalone — they don't modify `clean_and_load.py`. Day-wise stays get a new `daywise_stays` table (L2 — financial) since they represent separate revenue outside the monthly tenancy model.

**Tech Stack:** Python, openpyxl, SQLAlchemy (async), Supabase, gspread

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `scripts/import_april.py` | Create | Parse April Excel, update DB (rent_schedule + payments for April), update Sheet APRIL tab + TENANTS comments |
| `scripts/import_daywise.py` | Create | Parse both Day wise sheets, deduplicate, write to DB + Google Sheet DAY WISE tab |
| `src/database/models.py` | Modify | Add `DaywiseStay` model |
| `src/database/migrate_all.py` | Modify | Add migration for `daywise_stays` table |
| `docs/EXCEL_IMPORT.md` | Modify | Document both new scripts |

## Key Design Decisions

1. **Day-wise stays are NOT tenancies.** They're short-stay revenue (1-8 days). Different from the monthly tenant model. A separate `daywise_stays` table avoids polluting the tenant/tenancy/payment chain with short-stay noise.

2. **`import_april.py` matches by phone number** (same as excel_import.py). Finds existing tenancy, adds April rent_schedule + payments. Does NOT re-create tenants or tenancies.

3. **Day-wise dedup:** `SHA-256(name + phone + checkin_date + room)` — same person can have multiple stays but not in the same room on the same date.

4. **The two overlapping names (Syed Arfath, Eldin Henry)** are repeat visitors with different rooms/dates — both records are valid, no dedup needed across files.

---

### Task 1: DaywiseStay DB Model + Migration

**Files:**
- Modify: `src/database/models.py` — add DaywiseStay class after Payment class (~line 477)
- Modify: `src/database/migrate_all.py` — append migration

- [ ] **Step 1: Add DaywiseStay model to models.py**

Add after the `Refund` class (around line 497):

```python
class DaywiseStay(Base):
    """
    Short-term / daily-rate stays — 1 to ~10 days.
    Separate from monthly tenancies. One row per guest per visit.
    Revenue tracked here, not in payments table.
    """
    __tablename__ = "daywise_stays"

    id              = Column(Integer, primary_key=True)
    room_number     = Column(String(10), nullable=False)     # raw room from Excel ("519", "G14")
    guest_name      = Column(String(200), nullable=False)
    phone           = Column(String(20))
    checkin_date    = Column(Date, nullable=False)
    checkout_date   = Column(Date)                           # derived: checkin + days
    num_days        = Column(Integer)
    stay_period     = Column(String(100))                    # raw "march 26-april 2"
    sharing         = Column(Integer)                        # number of people sharing
    occupancy       = Column(Integer)                        # beds occupied
    booking_amount  = Column(Numeric(12, 2), default=0)      # what they paid upfront
    daily_rate      = Column(Numeric(10, 2), default=0)      # per-day rate
    total_amount    = Column(Numeric(12, 2), default=0)      # booking or days*rate
    maintenance     = Column(Numeric(10, 2), default=0)
    payment_date    = Column(Date)
    assigned_staff  = Column(String(50))
    status          = Column(String(20), default="EXIT")     # almost always EXIT
    comments        = Column(Text)
    source_file     = Column(String(100))                    # which Excel it came from
    unique_hash     = Column(String(64), unique=True)        # dedup key
    created_at      = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_daywise_checkin", "checkin_date"),
        Index("ix_daywise_room", "room_number"),
    )
```

- [ ] **Step 2: Add migration to migrate_all.py**

Append to the migrations list (do NOT remove existing):

```python
# ── v24: daywise_stays table ────────────────────────────────────────
async def migrate_v24_daywise_stays(conn):
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS daywise_stays (
            id SERIAL PRIMARY KEY,
            room_number VARCHAR(10) NOT NULL,
            guest_name VARCHAR(200) NOT NULL,
            phone VARCHAR(20),
            checkin_date DATE NOT NULL,
            checkout_date DATE,
            num_days INTEGER,
            stay_period VARCHAR(100),
            sharing INTEGER,
            occupancy INTEGER,
            booking_amount NUMERIC(12,2) DEFAULT 0,
            daily_rate NUMERIC(10,2) DEFAULT 0,
            total_amount NUMERIC(12,2) DEFAULT 0,
            maintenance NUMERIC(10,2) DEFAULT 0,
            payment_date DATE,
            assigned_staff VARCHAR(50),
            status VARCHAR(20) DEFAULT 'EXIT',
            comments TEXT,
            source_file VARCHAR(100),
            unique_hash VARCHAR(64) UNIQUE,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS ix_daywise_checkin ON daywise_stays(checkin_date);
        CREATE INDEX IF NOT EXISTS ix_daywise_room ON daywise_stays(room_number);
    """))
```

Add to the `MIGRATIONS` list at bottom:

```python
("v24_daywise_stays", migrate_v24_daywise_stays),
```

- [ ] **Step 3: Run migration locally**

```bash
python -m src.database.migrate_all
```

Expected: `v24_daywise_stays ... OK`

- [ ] **Step 4: Commit**

```bash
git add src/database/models.py src/database/migrate_all.py
git commit -m "feat: add daywise_stays table for short-term guest revenue"
```

---

### Task 2: import_april.py — April Payment Delta Loader

**Files:**
- Create: `scripts/import_april.py`

This script:
1. Reads `april month.xlsx` → "April month" sheet
2. For each CHECKIN row: matches tenant by phone → finds tenancy → adds April rent_schedule + cash/upi payments
3. Updates TENANTS tab comments on Google Sheet
4. Writes/updates APRIL 2026 tab on Google Sheet

- [ ] **Step 1: Create scripts/import_april.py**

```python
"""
April payment delta importer.
Reads 'april month.xlsx' and updates:
  - DB: rent_schedule (April 2026) + payments (cash/upi)
  - Google Sheet: APRIL 2026 tab + TENANTS comment column

Does NOT re-create tenants/tenancies — only adds April financial data.
Usage:
  python scripts/import_april.py              # dry run
  python scripts/import_april.py --write      # commit to DB
  python scripts/import_april.py --sheet      # update Google Sheet only
  python scripts/import_april.py --write --sheet  # both
"""
import sys, os, re, asyncio, hashlib
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, datetime
from decimal import Decimal
import openpyxl

from sqlalchemy import select, text
from src.database.connection import get_engine, get_session
from src.database.models import (
    Tenant, Tenancy, RentSchedule, Payment,
    RentStatus, PaymentMode, PaymentFor, TenancyStatus,
)

APRIL_FILE = "april month.xlsx"
APRIL_PERIOD = date(2026, 4, 1)

# ── Column mapping for "April month" sheet (27 cols) ───────────────────
# Col 1: Room No, 2: Name, 3: Gender, 4: Mobile Number, 5: Checkin Date
# Col 6: Booking, 7: Security Deposit, 8: Maintenance, 9: Day wise Rent
# Col 10: Monthly Rent, 11: From 1st FEB, 12: From 1st May, 13: Sharing
# Col 14: Paid Date, 15: Comments, 16: Assigned Staff, 17: IN/OUT
# Col 18: BLOCK, 19: Floor Number
# Col 20: April (status), 21: March Balance, 22: April cash, 23: April UPI
# Col 24: April Balance, 25: veg/nonveg/egg, 26: complaints, 27: vacation

COL_ROOM = 1
COL_NAME = 2
COL_PHONE = 4
COL_INOUT = 17
COL_COMMENT = 15
COL_RENT_MONTHLY = 10
COL_RENT_FEB = 11
COL_RENT_MAY = 12
COL_APR_STATUS = 20
COL_MAR_BALANCE = 21
COL_APR_CASH = 22
COL_APR_UPI = 23
COL_APR_BALANCE = 24


def safe_num(v):
    """Extract numeric value from cell. Returns 0 for text/None."""
    if v is None: return 0
    if isinstance(v, (int, float)): return float(v)
    s = str(v).strip()
    try: return float(s)
    except ValueError: pass
    # Try extracting first number from text like "5500 on april 1st"
    m = re.search(r'([\d,]+)', s)
    if m:
        try: return float(m.group(1).replace(',', ''))
        except: pass
    return 0


def safe_str(v):
    if v is None: return ''
    s = str(v).strip()
    if s.endswith('.0'):
        try: return str(int(float(s)))
        except: pass
    return s


def rent_status_map(v):
    """Map April status column to RentStatus enum."""
    s = str(v).strip().upper() if v else ''
    if not s: return None
    if s == 'PAID': return RentStatus.paid
    if 'PARTIAL' in s: return RentStatus.partial
    if 'NOT PAID' in s or 'UNPAID' in s: return RentStatus.unpaid
    if 'EXIT' in s: return None  # exited tenants don't get April rent_schedule
    if 'NO SHOW' in s: return None
    return RentStatus.unpaid  # default for anything else


def read_april(excel_file=APRIL_FILE):
    """Parse 'April month' sheet. Returns list of dicts."""
    wb = openpyxl.load_workbook(excel_file, data_only=True)
    ws = wb['April month']
    records = []

    for row in range(2, ws.max_row + 1):
        name = ws.cell(row, COL_NAME).value
        if not name or not str(name).strip():
            continue

        inout = safe_str(ws.cell(row, COL_INOUT).value).upper()
        if inout not in ('CHECKIN', 'CHECK IN'):
            continue  # only process active tenants

        phone = safe_str(ws.cell(row, COL_PHONE).value)
        # Clean phone: remove +91, spaces, dots
        phone = re.sub(r'[^\d]', '', phone)
        if phone.startswith('91') and len(phone) == 12:
            phone = phone[2:]

        apr_status_raw = safe_str(ws.cell(row, COL_APR_STATUS).value)
        apr_status = rent_status_map(apr_status_raw)

        # Rent for April: use May revision > Feb revision > Monthly
        rm = safe_num(ws.cell(row, COL_RENT_MONTHLY).value)
        rf = safe_num(ws.cell(row, COL_RENT_FEB).value)
        ry = safe_num(ws.cell(row, COL_RENT_MAY).value)
        april_rent = ry if ry > 0 else (rf if rf > 0 else rm)

        apr_cash = safe_num(ws.cell(row, COL_APR_CASH).value)
        apr_upi = safe_num(ws.cell(row, COL_APR_UPI).value)

        comment = safe_str(ws.cell(row, COL_COMMENT).value)
        mar_balance = safe_str(ws.cell(row, COL_MAR_BALANCE).value)
        apr_balance = safe_str(ws.cell(row, COL_APR_BALANCE).value)

        records.append({
            'name': str(name).strip(),
            'phone': phone,
            'room': safe_str(ws.cell(row, COL_ROOM).value),
            'apr_status': apr_status,
            'apr_status_raw': apr_status_raw,
            'april_rent': april_rent,
            'apr_cash': apr_cash,
            'apr_upi': apr_upi,
            'comment': comment,
            'mar_balance': mar_balance,
            'apr_balance': apr_balance,
        })

    return records


async def import_to_db(records, write=False):
    """Match records to existing tenancies, add April rent_schedule + payments."""
    engine = get_engine()
    stats = {'matched': 0, 'skipped': 0, 'rent_schedule': 0, 'payments': 0,
             'already_exists': 0, 'no_match': []}

    async with get_session(engine) as session:
        for rec in records:
            phone = rec['phone']
            if not phone or len(phone) < 10:
                stats['skipped'] += 1
                continue

            # Find tenant by phone
            tenant = await session.scalar(
                select(Tenant).where(Tenant.phone == phone)
            )
            if not tenant:
                # Try with +91 prefix
                tenant = await session.scalar(
                    select(Tenant).where(Tenant.phone == f"91{phone}")
                )
            if not tenant:
                stats['no_match'].append(f"{rec['name']} ({phone}) room {rec['room']}")
                continue

            # Find active tenancy
            tenancy = await session.scalar(
                select(Tenancy).where(
                    Tenancy.tenant_id == tenant.id,
                    Tenancy.status == TenancyStatus.active,
                )
            )
            if not tenancy:
                stats['no_match'].append(f"{rec['name']} ({phone}) — no active tenancy")
                continue

            stats['matched'] += 1

            # Check if April rent_schedule already exists
            existing_rs = await session.scalar(
                select(RentSchedule).where(
                    RentSchedule.tenancy_id == tenancy.id,
                    RentSchedule.period_month == APRIL_PERIOD,
                )
            )

            if existing_rs:
                stats['already_exists'] += 1
                # Update status if we have new info
                if rec['apr_status'] and existing_rs.status != rec['apr_status']:
                    existing_rs.status = rec['apr_status']
                continue

            # Add rent_schedule for April
            if rec['apr_status']:
                session.add(RentSchedule(
                    tenancy_id=tenancy.id,
                    period_month=APRIL_PERIOD,
                    rent_due=Decimal(str(rec['april_rent'])),
                    maintenance_due=Decimal("0"),
                    status=rec['apr_status'],
                    due_date=APRIL_PERIOD,
                    notes=rec.get('apr_balance', ''),
                ))
                stats['rent_schedule'] += 1

            # Add cash payment
            if rec['apr_cash'] > 0:
                session.add(Payment(
                    tenancy_id=tenancy.id,
                    amount=Decimal(str(rec['apr_cash'])),
                    payment_date=APRIL_PERIOD,
                    payment_mode=PaymentMode.cash,
                    for_type=PaymentFor.rent,
                    period_month=APRIL_PERIOD,
                    notes="Imported from April Excel",
                ))
                stats['payments'] += 1

            # Add UPI payment
            if rec['apr_upi'] > 0:
                session.add(Payment(
                    tenancy_id=tenancy.id,
                    amount=Decimal(str(rec['apr_upi'])),
                    payment_date=APRIL_PERIOD,
                    payment_mode=PaymentMode.upi,
                    for_type=PaymentFor.rent,
                    period_month=APRIL_PERIOD,
                    notes="Imported from April Excel",
                ))
                stats['payments'] += 1

            # Update tenancy notes with new comment if changed
            if rec['comment'] and rec['comment'] != (tenancy.notes or ''):
                tenancy.notes = rec['comment']

        if write:
            await session.commit()
            print("  ** COMMITTED to DB **")
        else:
            print("  ** DRY RUN — no changes saved **")

    await engine.dispose()
    return stats


def update_sheet(records):
    """Update APRIL 2026 tab and TENANTS comments on Google Sheet."""
    import gspread
    from google.oauth2.service_account import Credentials
    import time

    SHEET_ID = "1Hp5dTM7TcDEq75jgHEjvwtBjOolruGfQ7CVMzVqjdGw"
    CREDS_FILE = "credentials/gsheets_service_account.json"

    creds = Credentials.from_service_account_file(CREDS_FILE,
        scopes=['https://www.googleapis.com/auth/spreadsheets'])
    gc = gspread.authorize(creds)
    sp = gc.open_by_key(SHEET_ID)

    # ── Update APRIL 2026 tab ──────────────────────────────────────────
    try:
        ws = sp.worksheet("APRIL 2026")
        ws.clear()
    except gspread.WorksheetNotFound:
        ws = sp.add_worksheet("APRIL 2026", rows=300, cols=16)

    headers = ["Room", "Name", "Building", "Sharing", "Rent",
               "Cash", "UPI", "Total Paid", "Balance",
               "Status", "Comment", "March Balance", "April Balance"]

    rows = []
    for rec in records:
        cash = rec['apr_cash']
        upi = rec['apr_upi']
        rent = rec['april_rent']
        row_num = len(rows) + 3  # header on row 2, data from row 3
        rows.append([
            rec['room'], rec['name'], '', '',  # building/sharing not in april file per-record easily
            rent, cash, upi,
            f'=F{row_num}+G{row_num}',           # Total Paid
            f'=E{row_num}-H{row_num}',           # Balance
            rec['apr_status_raw'],
            rec['comment'],
            rec['mar_balance'],
            rec['apr_balance'],
        ])

    # Summary row
    n = len(rows)
    summary = [
        "APRIL 2026", "", "", "", "",
        f"=SUM(F3:F{2+n})", f"=SUM(G3:G{2+n})", f"=SUM(H3:H{2+n})", f"=SUM(I3:I{2+n})",
        "", "", "", "",
    ]

    ws.update(values=[summary, headers] + rows, range_name="A1", value_input_option="USER_ENTERED")
    ws.format("A1:M1", {"textFormat": {"bold": True, "fontSize": 13}})
    ws.format("A2:M2", {"textFormat": {"bold": True},
                         "backgroundColor": {"red": 0.85, "green": 0.9, "blue": 1.0}})
    ws.freeze(rows=2)
    try: ws.set_basic_filter(f"A2:M{2 + n}")
    except: pass
    print(f"  APRIL 2026: {n} rows written to Sheet")

    return n


async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Import April payment data")
    parser.add_argument("--write", action="store_true", help="Commit to DB (default: dry run)")
    parser.add_argument("--sheet", action="store_true", help="Update Google Sheet")
    parser.add_argument("--file", default=APRIL_FILE, help="Excel file path")
    args = parser.parse_args()

    print("=" * 60)
    print("APRIL PAYMENT IMPORT")
    print("=" * 60)

    print("\nStep 1: Reading April Excel...")
    records = read_april(args.file)
    print(f"  {len(records)} CHECKIN records parsed")

    print("\nStep 2: Importing to DB...")
    stats = await import_to_db(records, write=args.write)

    print(f"\n  Matched:         {stats['matched']}")
    print(f"  Already existed: {stats['already_exists']}")
    print(f"  Rent schedules:  {stats['rent_schedule']}")
    print(f"  Payments:        {stats['payments']}")
    print(f"  Skipped:         {stats['skipped']}")

    if stats['no_match']:
        print(f"\n  NO MATCH ({len(stats['no_match'])}):")
        for nm in stats['no_match']:
            print(f"    - {nm}")

    if args.sheet:
        print("\nStep 3: Updating Google Sheet...")
        update_sheet(records)

    print("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Test dry run**

```bash
python scripts/import_april.py
```

Expected: Shows matched/unmatched counts, 0 changes (dry run).

- [ ] **Step 3: Review no-match list, fix if needed, then write**

```bash
python scripts/import_april.py --write --sheet
```

- [ ] **Step 4: Commit**

```bash
git add scripts/import_april.py
git commit -m "feat: add April payment delta importer"
```

---

### Task 3: import_daywise.py — Short-Stay Loader

**Files:**
- Create: `scripts/import_daywise.py`

Reads Day wise from both Excel files, deduplicates, writes to `daywise_stays` table + "DAY WISE" Google Sheet tab.

- [ ] **Step 1: Create scripts/import_daywise.py**

```python
"""
Day-wise / short-stay importer.
Reads 'Daily Basis' from main Excel + 'Day wise' from April Excel.
Deduplicates by SHA-256(name + phone + checkin_date + room).
Writes to daywise_stays table + Google Sheet 'DAY WISE' tab.

Usage:
  python scripts/import_daywise.py              # dry run
  python scripts/import_daywise.py --write      # commit to DB
  python scripts/import_daywise.py --sheet      # update Google Sheet only
  python scripts/import_daywise.py --write --sheet  # both
"""
import sys, os, re, asyncio, hashlib
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, datetime
from decimal import Decimal
import openpyxl

from sqlalchemy import select, text
from src.database.connection import get_engine, get_session
from src.database.models import DaywiseStay

MAIN_EXCEL = "data/raw/Cozeevo Monthly stay (4).xlsx"
APRIL_EXCEL = "april month.xlsx"


def safe_num(v):
    if v is None: return 0
    if isinstance(v, (int, float)): return float(v)
    s = str(v).strip()
    try: return float(s)
    except: pass
    m = re.search(r'([\d,]+)', s)
    if m:
        try: return float(m.group(1).replace(',', ''))
        except: pass
    return 0


def safe_str(v):
    if v is None: return ''
    s = str(v).strip()
    if s.endswith('.0'):
        try: return str(int(float(s)))
        except: pass
    return s


def parse_date(v):
    if v is None: return None
    if isinstance(v, datetime): return v.date()
    if isinstance(v, date): return v
    s = str(v).strip()
    for fmt in ('%d-%m-%Y', '%d-%m-%y', '%Y-%m-%d', '%d/%m/%Y', '%d/%m/%y'):
        try: return datetime.strptime(s, fmt).date()
        except: continue
    return None


def make_hash(name, phone, checkin, room):
    """Dedup key: name + phone + checkin_date + room."""
    raw = f"{name}|{phone}|{checkin}|{room}".lower().strip()
    return hashlib.sha256(raw.encode()).hexdigest()


def read_daywise_sheet(wb, sheet_name, source_file, phone_col=3, has_mobile_col=True):
    """
    Parse a Day wise sheet. Returns list of dicts.
    Main Excel 'Daily Basis': col 3 is empty (no phone), col structure same otherwise.
    April Excel 'Day wise': col 3 is Mobile Number.
    """
    ws = wb[sheet_name]
    records = []

    for row in range(2, ws.max_row + 1):
        name = ws.cell(row, 2).value
        if not name or not str(name).strip():
            continue

        room = safe_str(ws.cell(row, 1).value)
        phone = safe_str(ws.cell(row, phone_col).value) if has_mobile_col else ''
        phone = re.sub(r'[^\d]', '', phone)

        checkin = parse_date(ws.cell(row, 4).value)
        booking = safe_num(ws.cell(row, 5).value)
        stay_period = safe_str(ws.cell(row, 6).value)
        num_days = safe_num(ws.cell(row, 7).value)
        maintenance = safe_num(ws.cell(row, 8).value)
        daily_rate = safe_num(ws.cell(row, 9).value)
        sharing = safe_num(ws.cell(row, 10).value)
        occupancy = safe_num(ws.cell(row, 11).value)
        paid_date = parse_date(ws.cell(row, 12).value)
        comments = safe_str(ws.cell(row, 13).value)
        staff = safe_str(ws.cell(row, 14).value)
        status = safe_str(ws.cell(row, 15).value) or 'EXIT'

        # Total: booking if available, else days * rate
        total = booking if booking > 0 else (num_days * daily_rate if num_days and daily_rate else 0)

        # Checkout: checkin + days if we have both
        checkout = None
        if checkin and num_days and int(num_days) > 0:
            from datetime import timedelta
            checkout = checkin + timedelta(days=int(num_days))

        h = make_hash(str(name).strip(), phone, checkin, room)

        records.append({
            'room_number': room,
            'guest_name': str(name).strip(),
            'phone': phone,
            'checkin_date': checkin,
            'checkout_date': checkout,
            'num_days': int(num_days) if num_days else None,
            'stay_period': stay_period,
            'sharing': int(sharing) if sharing else None,
            'occupancy': int(occupancy) if occupancy else None,
            'booking_amount': booking,
            'daily_rate': daily_rate,
            'total_amount': total,
            'maintenance': maintenance,
            'payment_date': paid_date,
            'assigned_staff': staff,
            'status': status.upper() if status else 'EXIT',
            'comments': comments,
            'source_file': source_file,
            'unique_hash': h,
        })

    return records


def read_all_daywise():
    """Read from both Excel files, deduplicate."""
    all_records = []
    seen_hashes = set()

    # 1. Main Excel — "Daily Basis" sheet (no phone column — col 3 is empty)
    try:
        wb_main = openpyxl.load_workbook(MAIN_EXCEL, data_only=True)
        main_recs = read_daywise_sheet(wb_main, "Daily Basis",
                                        source_file="Cozeevo Monthly stay (4).xlsx",
                                        phone_col=3, has_mobile_col=False)
        for r in main_recs:
            if r['unique_hash'] not in seen_hashes:
                seen_hashes.add(r['unique_hash'])
                all_records.append(r)
        print(f"  Main Excel 'Daily Basis': {len(main_recs)} rows ({len(all_records)} after dedup)")
    except Exception as e:
        print(f"  WARNING: Could not read main Excel: {e}")

    # 2. April Excel — "Day wise" sheet (has phone in col 3)
    try:
        wb_apr = openpyxl.load_workbook(APRIL_EXCEL, data_only=True)
        apr_recs = read_daywise_sheet(wb_apr, "Day wise",
                                      source_file="april month.xlsx",
                                      phone_col=3, has_mobile_col=True)
        added = 0
        for r in apr_recs:
            if r['unique_hash'] not in seen_hashes:
                seen_hashes.add(r['unique_hash'])
                all_records.append(r)
                added += 1
        print(f"  April Excel 'Day wise': {len(apr_recs)} rows ({added} new after dedup)")
    except Exception as e:
        print(f"  WARNING: Could not read April Excel: {e}")

    # Sort by checkin date
    all_records.sort(key=lambda r: r['checkin_date'] or date.min)
    return all_records


async def import_to_db(records, write=False):
    """Insert into daywise_stays table, skip duplicates."""
    engine = get_engine()
    stats = {'inserted': 0, 'skipped_dup': 0, 'skipped_nodate': 0}

    async with get_session(engine) as session:
        for rec in records:
            if not rec['checkin_date']:
                stats['skipped_nodate'] += 1
                continue

            # Check if already exists
            existing = await session.scalar(
                select(DaywiseStay).where(DaywiseStay.unique_hash == rec['unique_hash'])
            )
            if existing:
                stats['skipped_dup'] += 1
                continue

            session.add(DaywiseStay(
                room_number=rec['room_number'],
                guest_name=rec['guest_name'],
                phone=rec['phone'] or None,
                checkin_date=rec['checkin_date'],
                checkout_date=rec['checkout_date'],
                num_days=rec['num_days'],
                stay_period=rec['stay_period'],
                sharing=rec['sharing'],
                occupancy=rec['occupancy'],
                booking_amount=Decimal(str(rec['booking_amount'])),
                daily_rate=Decimal(str(rec['daily_rate'])),
                total_amount=Decimal(str(rec['total_amount'])),
                maintenance=Decimal(str(rec['maintenance'])),
                payment_date=rec['payment_date'],
                assigned_staff=rec['assigned_staff'] or None,
                status=rec['status'],
                comments=rec['comments'] or None,
                source_file=rec['source_file'],
                unique_hash=rec['unique_hash'],
            ))
            stats['inserted'] += 1

        if write:
            await session.commit()
            print("  ** COMMITTED to DB **")
        else:
            print("  ** DRY RUN — no changes saved **")

    await engine.dispose()
    return stats


def update_sheet(records):
    """Write DAY WISE tab to Google Sheet."""
    import gspread
    from google.oauth2.service_account import Credentials
    import time

    SHEET_ID = "1Hp5dTM7TcDEq75jgHEjvwtBjOolruGfQ7CVMzVqjdGw"
    CREDS_FILE = "credentials/gsheets_service_account.json"

    creds = Credentials.from_service_account_file(CREDS_FILE,
        scopes=['https://www.googleapis.com/auth/spreadsheets'])
    gc = gspread.authorize(creds)
    sp = gc.open_by_key(SHEET_ID)

    try:
        ws = sp.worksheet("DAY WISE")
        ws.clear()
    except gspread.WorksheetNotFound:
        ws = sp.add_worksheet("DAY WISE", rows=200, cols=16)

    headers = ["Room", "Guest Name", "Phone", "Check-in", "Stay Period",
               "Days", "Daily Rate", "Booking Amt", "Total", "Maintenance",
               "Sharing", "Staff", "Status", "Comments", "Source"]

    rows = []
    total_revenue = 0
    for rec in records:
        checkin_str = rec['checkin_date'].strftime('%Y-%m-%d') if rec['checkin_date'] else ''
        rows.append([
            rec['room_number'], rec['guest_name'], rec['phone'] or '',
            checkin_str, rec['stay_period'],
            rec['num_days'] or '', rec['daily_rate'] or '',
            rec['booking_amount'] or '', rec['total_amount'] or '',
            rec['maintenance'] or '',
            rec['sharing'] or '', rec['assigned_staff'] or '',
            rec['status'], rec['comments'] or '', rec['source_file'],
        ])
        total_revenue += rec['total_amount']

    n = len(rows)
    summary = [
        "DAY WISE STAYS", f"Total: {n} guests",
        f"Revenue: {total_revenue:,.0f}", "", "", "", "", "", "", "", "", "", "", "", "",
    ]

    ws.update(values=[summary, headers] + rows, range_name="A1", value_input_option="USER_ENTERED")
    ws.format("A1:O1", {"textFormat": {"bold": True, "fontSize": 13}})
    ws.format("A2:O2", {"textFormat": {"bold": True},
                         "backgroundColor": {"red": 1.0, "green": 0.95, "blue": 0.8}})
    ws.freeze(rows=2)
    try: ws.set_basic_filter(f"A2:O{2 + n}")
    except: pass
    print(f"  DAY WISE: {n} rows, revenue {total_revenue:,.0f}")

    return n


async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Import day-wise short stays")
    parser.add_argument("--write", action="store_true", help="Commit to DB")
    parser.add_argument("--sheet", action="store_true", help="Update Google Sheet")
    args = parser.parse_args()

    print("=" * 60)
    print("DAY-WISE STAY IMPORT")
    print("=" * 60)

    print("\nStep 1: Reading Excel files...")
    records = read_all_daywise()
    print(f"  Total: {len(records)} unique records")

    print("\nStep 2: Importing to DB...")
    stats = await import_to_db(records, write=args.write)
    print(f"\n  Inserted:       {stats['inserted']}")
    print(f"  Skipped (dup):  {stats['skipped_dup']}")
    print(f"  Skipped (date): {stats['skipped_nodate']}")

    if args.sheet:
        print("\nStep 3: Writing Google Sheet...")
        update_sheet(records)

    print("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Test dry run**

```bash
python scripts/import_daywise.py
```

Expected: 71 from main + 22 from April = ~91 unique records (minus 2 overlaps = ~89-91).

- [ ] **Step 3: Write to DB + Sheet**

```bash
python scripts/import_daywise.py --write --sheet
```

- [ ] **Step 4: Commit**

```bash
git add scripts/import_daywise.py
git commit -m "feat: add day-wise short-stay importer (DB + Sheet)"
```

---

### Task 4: Update Documentation

**Files:**
- Modify: `docs/EXCEL_IMPORT.md`

- [ ] **Step 1: Add sections for both new scripts**

Append to `docs/EXCEL_IMPORT.md` before the `## Migration & Data Strategy` section:

```markdown
## April Monthly Delta Import

For months where Kiran provides a separate monthly file (e.g. `april month.xlsx`):

```bash
python scripts/import_april.py              # dry run — shows matches/mismatches
python scripts/import_april.py --write      # commit April payments to DB
python scripts/import_april.py --sheet      # update APRIL 2026 tab on Sheet
python scripts/import_april.py --write --sheet  # both
```

The script reads the "April month" sheet (27 columns), matches CHECKIN tenants by phone to existing DB records, and adds:
- `rent_schedule` entry for April 2026
- Cash + UPI payments for April
- Updates tenancy comments

Does NOT re-create tenants or tenancies. Safe to re-run (skips existing rent_schedule entries).

## Day-Wise / Short Stay Import

Consolidates daily-rate guests from both Excel files into `daywise_stays` table + "DAY WISE" Google Sheet tab.

```bash
python scripts/import_daywise.py              # dry run
python scripts/import_daywise.py --write      # commit to DB
python scripts/import_daywise.py --sheet      # update Sheet
python scripts/import_daywise.py --write --sheet  # both
```

Sources:
- `data/raw/Cozeevo Monthly stay (4).xlsx` → "Daily Basis" sheet (Nov 2025 - Mar 2026, ~71 records)
- `april month.xlsx` → "Day wise" sheet (Mar-Apr 2026, ~22 records)

Dedup key: `SHA-256(name + phone + checkin_date + room)`. Safe to re-run.
```

- [ ] **Step 2: Update CLAUDE.md active files table**

Add to the active files table:

```
| `scripts/import_april.py` | April monthly delta importer (DB + Sheet) |
| `scripts/import_daywise.py` | Day-wise short-stay importer (DB + Sheet) |
```

- [ ] **Step 3: Commit**

```bash
git add docs/EXCEL_IMPORT.md CLAUDE.md
git commit -m "docs: add April importer + day-wise importer documentation"
```

---

### Task 5: Run Full Import + Verify

- [ ] **Step 1: Run migration**
```bash
python -m src.database.migrate_all
```

- [ ] **Step 2: Run April import (dry run first)**
```bash
python scripts/import_april.py
```
Review output. Fix any no-match issues.

- [ ] **Step 3: Run April import for real**
```bash
python scripts/import_april.py --write --sheet
```

- [ ] **Step 4: Run day-wise import**
```bash
python scripts/import_daywise.py --write --sheet
```

- [ ] **Step 5: Verify DB counts**
```bash
python -c "
import asyncio
from sqlalchemy import select, func, text
from src.database.connection import get_engine, get_session
from src.database.models import RentSchedule, Payment, DaywiseStay
from datetime import date

async def check():
    engine = get_engine()
    async with get_session(engine) as s:
        rs = await s.scalar(select(func.count()).select_from(RentSchedule).where(RentSchedule.period_month == date(2026,4,1)))
        pay = await s.scalar(select(func.count()).select_from(Payment).where(Payment.period_month == date(2026,4,1)))
        dw = await s.scalar(select(func.count()).select_from(DaywiseStay))
        print(f'April rent_schedule: {rs}')
        print(f'April payments: {pay}')
        print(f'Daywise stays: {dw}')
    await engine.dispose()

asyncio.run(check())
"
```

Expected: ~196 rent_schedule, ~209 payments (51 cash + 158 upi), ~89-91 daywise stays.

- [ ] **Step 6: Commit all**
```bash
git add -A
git commit -m "feat: April import + day-wise import — data loaded"
```
