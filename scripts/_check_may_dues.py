"""
One-off: Check May 2026 dues — DB vs Google Sheet May cash/UPI columns.
Also checks: which active tenants are missing from the KPI dues tile.

Run: venv/Scripts/python scripts/_check_may_dues.py
"""
import asyncio, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

DB_URL = os.environ["DATABASE_URL"]

GSHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "")
GCREDS_FILE = os.environ.get("GOOGLE_CREDENTIALS_FILE", "credentials.json")

MAY_PERIOD = "2026-05-01"


async def get_db_dues():
    from src.database.db_manager import init_engine, get_session
    init_engine(DB_URL)
    from sqlalchemy import text

    async with get_session() as s:
        # 1. Ivish specific
        r = await s.execute(text("""
            SELECT t.name, t.id as tid, tn.id as tnid, tn.status, tn.checkin_date,
                   tn.agreed_rent, tn.security_deposit, tn.booking_amount,
                   rm.room_number,
                   rs.id as rs_id, rs.rent_due, rs.adjustment,
                   rs.status as rs_status,
                   COALESCE((SELECT SUM(p.amount) FROM payments p
                     WHERE p.tenancy_id = tn.id AND p.for_type = 'rent'
                       AND p.period_month = '2026-05-01' AND p.is_void = false), 0) as rent_paid
            FROM tenants t
            JOIN tenancies tn ON tn.tenant_id = t.id
            JOIN rooms rm ON tn.room_id = rm.id
            LEFT JOIN rent_schedule rs ON rs.tenancy_id = tn.id
                AND rs.period_month = '2026-05-01'
            WHERE t.name ILIKE '%ivish%'
            ORDER BY tn.id DESC
        """))
        rows = r.fetchall()
        print("=== IVISH ===")
        for row in rows:
            print(f"  {row[0]} (tnid={row[2]}) status={row[3]} room={row[8]} checkin={row[4]}")
            print(f"  agreed_rent={row[5]:,}  sec_dep={row[6]:,}  booking={row[7]:,}")
            if row[9]:
                rent_due = int(row[10] or 0)
                adj = int(row[11] or 0)
                paid = int(row[13] or 0)
                balance = rent_due + adj - paid
                print(f"  May RS: rent_due={rent_due:,} adj={adj:,} rent_paid={paid:,} BALANCE={balance:,}  rs_status={row[12]}")
            else:
                print(f"  May RS: MISSING")

        # 2. All active with no May RS
        r2 = await s.execute(text("""
            SELECT t.name, rm.room_number, tn.id, tn.checkin_date, tn.agreed_rent
            FROM tenancies tn
            JOIN tenants t ON t.id = tn.tenant_id
            JOIN rooms rm ON rm.id = tn.room_id
            WHERE tn.status = 'active'
              AND NOT EXISTS (
                SELECT 1 FROM rent_schedule rs
                WHERE rs.tenancy_id = tn.id AND rs.period_month = '2026-05-01'
              )
            ORDER BY rm.room_number
        """))
        rows2 = r2.fetchall()
        print(f"\n=== ACTIVE TENANTS WITH NO MAY RS ({len(rows2)}) ===")
        for row in rows2:
            print(f"  {row[0]}  Room {row[1]}  (tn={row[2]})  checkin={row[3]}  rent={row[4]:,}")

        # 3. Full May dues from DB — mirrors KPI dues logic exactly
        r3 = await s.execute(text("""
            SELECT
                t.name, rm.room_number, tn.id as tnid, tn.status,
                rs.rent_due, COALESCE(rs.adjustment,0) as adj,
                rs.status as rs_status,
                tn.security_deposit, tn.booking_amount, tn.checkin_date,
                COALESCE(
                    (SELECT SUM(p.amount) FROM payments p
                     WHERE p.tenancy_id = tn.id
                       AND p.is_void = false
                       AND (
                         (p.for_type = 'rent' AND p.period_month = '2026-05-01')
                         OR (p.for_type = 'deposit' AND p.period_month IS NULL
                             AND p.payment_date >= '2026-05-01' AND p.payment_date < '2026-06-01')
                         OR (p.for_type = 'booking'
                             AND p.payment_date >= '2026-05-01' AND p.payment_date < '2026-06-01')
                       )
                    ), 0) as rent_paid,
                COALESCE(
                    (SELECT SUM(p.amount) FROM payments p
                     WHERE p.tenancy_id = tn.id AND p.for_type = 'deposit' AND p.is_void = false),
                0) as dep_paid
            FROM rent_schedule rs
            JOIN tenancies tn ON rs.tenancy_id = tn.id
            JOIN tenants t ON tn.tenant_id = t.id
            JOIN rooms rm ON tn.room_id = rm.id
            WHERE rs.period_month = '2026-05-01'
              AND tn.status IN ('active', 'no_show')
            ORDER BY rm.room_number, t.name
        """))
        rows3 = r3.fetchall()

        import math
        print(f"\n=== FULL MAY DUES (active+no_show with RS) ===")
        print(f"{'Name':<30} {'Room':<6} {'Eff':>8} {'Paid':>8} {'RentBal':>8} {'DepDue':>8} {'Total':>8}")
        print("-"*85)
        total = 0
        dues_tenants = []
        for row in rows3:
            rent_due = int(row[4] or 0)
            adj = int(row[5] or 0)
            paid = int(row[10] or 0)
            eff = rent_due + adj
            rent_bal = math.ceil(max(0, eff - paid) / 100) * 100
            dep_agreed = int(row[7] or 0)
            booking = int(row[8] or 0)
            dep_paid = int(row[11] or 0)
            booking_surplus = max(0, booking - eff)
            dep_due = math.ceil(max(0, dep_agreed - dep_paid - booking_surplus) / 100) * 100
            total_dues = rent_bal + dep_due
            if total_dues > 0:
                total += total_dues
                dues_tenants.append((row[0], row[1], eff, paid, rent_bal, dep_due, total_dues, row[6]))
                print(f"  {row[0]:<28} {row[1]:<6} {eff:>8,} {paid:>8,} {rent_bal:>8,} {dep_due:>8,} {total_dues:>8,}  {row[3]}")
        print(f"\n  TOTAL dues: {total:,}  ({len(dues_tenants)} tenants)")
        return dues_tenants


def get_sheet_may_data():
    """Read May UPI and May Cash columns from Google Sheet Long term tab."""
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        scopes = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_file(GCREDS_FILE, scopes=scopes)
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(GSHEET_ID)

        # Try to find the Long term tab
        ws = None
        for tab_name in ["Long term", "Long Term", "LONG TERM", "May 2026", "May"]:
            try:
                ws = sh.worksheet(tab_name)
                print(f"\nFound sheet tab: {tab_name}")
                break
            except Exception:
                continue

        if not ws:
            print("\nCould not find Long term sheet tab. Listing all tabs:")
            for ws2 in sh.worksheets():
                print(f"  {ws2.title}")
            return {}

        data = ws.get_all_values()
        if not data:
            return {}

        headers = [h.strip().lower() for h in data[0]]
        print(f"Sheet headers: {headers[:20]}")

        # Find name, room, may_upi, may_cash columns
        def find_col(candidates):
            for c in candidates:
                for i, h in enumerate(headers):
                    if c in h:
                        return i
            return None

        name_col = find_col(["name"])
        room_col = find_col(["room"])
        may_upi_col = find_col(["may upi", "mayupi"])
        may_cash_col = find_col(["may cash", "maycash"])
        june_bal_col = find_col(["june balance", "junebal", "june bal"])

        print(f"Cols: name={name_col} room={room_col} may_upi={may_upi_col} may_cash={may_cash_col} june_bal={june_bal_col}")

        result = {}
        for row in data[1:]:
            if not row or len(row) <= max(filter(lambda x: x is not None, [name_col, room_col])):
                continue
            name = row[name_col].strip() if name_col is not None else ""
            room = row[room_col].strip() if room_col is not None else ""
            if not name:
                continue

            def parse_amt(col):
                if col is None or col >= len(row):
                    return 0
                val = row[col].replace(",", "").replace("₹", "").strip()
                try:
                    return int(float(val)) if val else 0
                except Exception:
                    return 0

            may_upi = parse_amt(may_upi_col)
            may_cash = parse_amt(may_cash_col)
            june_bal = parse_amt(june_bal_col)
            result[name.lower()] = {
                "name": name, "room": room,
                "may_upi": may_upi, "may_cash": may_cash,
                "june_bal": june_bal,
                "total_paid": may_upi + may_cash,
            }
        return result
    except Exception as e:
        print(f"Sheet read failed: {e}")
        return {}


if __name__ == "__main__":
    dues_tenants = asyncio.run(get_db_dues())
    sheet_data = get_sheet_may_data()

    if sheet_data:
        print(f"\n=== DB vs SHEET COMPARISON (May) ===")
        print(f"{'Name':<30} {'Room':<6} {'DB_dues':>8} {'Sh_paid':>8} {'Sh_bal':>8} {'Match?'}")
        print("-"*75)
        matches = mismatches = 0
        for name, room, eff, paid, rent_bal, dep_due, total_dues, rs_status in dues_tenants:
            sh = sheet_data.get(name.lower(), {})
            sh_paid = sh.get("total_paid", 0)
            sh_june_bal = sh.get("june_bal", 0)
            match = abs(total_dues - sh_june_bal) <= 100
            flag = "OK" if match else "MISMATCH"
            if not match:
                mismatches += 1
            else:
                matches += 1
            print(f"  {name:<28} {room:<6} {total_dues:>8,} {sh_paid:>8,} {sh_june_bal:>8,}  {flag}")
        print(f"\nMatches: {matches}  Mismatches: {mismatches}")
