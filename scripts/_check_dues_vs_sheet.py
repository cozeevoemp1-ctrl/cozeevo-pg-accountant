"""Compare sheet April/May balances vs DB dues for all tenants."""
import asyncio, os, sys, re
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv; load_dotenv()

import gspread
from google.oauth2.service_account import Credentials
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

SOURCE_SHEET_ID = "1Vr_fSIOuuKBK4MWF-FVqgAIUPbqun3POszaXYfj-Ea0"
CREDS_FILE = "credentials/gsheets_service_account.json"

def pn(v):
    if not v: return 0
    s = str(v).replace(",", "").strip()
    try: return max(0, int(float(s)))
    except: return 0

def norm_phone(raw):
    d = re.sub(r"\D", "", str(raw or ""))
    if d.startswith("91") and len(d) == 12: d = d[2:]
    return f"+91{d}" if len(d) == 10 else ""

SQL_DUES = """
SELECT
    rs.period_month,
    (rs.rent_due + COALESCE(rs.adjustment, 0)) AS eff_due,
    COALESCE((
        SELECT SUM(p.amount) FROM payments p
        WHERE p.tenancy_id = t.id AND p.is_void = false
          AND p.for_type = 'rent' AND p.period_month = rs.period_month
    ), 0) AS rent_paid,
    COALESCE((
        SELECT SUM(p.amount) FROM payments p
        WHERE p.tenancy_id = t.id AND p.is_void = false
          AND p.for_type IN ('deposit','booking')
          AND p.period_month IS NULL
          AND p.payment_date >= '2026-04-01' AND p.payment_date < '2026-06-01'
    ), 0) AS dep_paid
FROM tenants tn
JOIN tenancies t ON t.tenant_id = tn.id
JOIN rent_schedule rs ON rs.tenancy_id = t.id
WHERE tn.phone = :phone
  AND t.status = 'active'
  AND rs.period_month IN ('2026-04-01', '2026-05-01')
ORDER BY rs.period_month
"""


async def main():
    scopes = ["https://www.googleapis.com/auth/spreadsheets",
              "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_file(CREDS_FILE, scopes=scopes)
    gc = gspread.authorize(creds)
    ws = gc.open_by_key(SOURCE_SHEET_ID).worksheet("Long term")
    all_rows = ws.get_all_values()
    header = all_rows[0]
    col = {h.strip().lower(): i for i, h in enumerate(header)}

    url = os.environ["DATABASE_URL"].replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(url, echo=False)

    ok = 0
    mismatches = []

    async with engine.connect() as conn:
        for row in all_rows[1:]:
            name = row[col["name"]].strip() if "name" in col else ""
            if not name: continue
            phone = norm_phone(row[col["mobile number"]]) if "mobile number" in col else ""
            if not phone: continue

            apr_bal = pn(row[col["april balance"]]) if "april balance" in col and col["april balance"] < len(row) else 0
            jun_bal = pn(row[col["june balance"]]) if "june balance" in col and col["june balance"] < len(row) else 0

            if apr_bal == 0 and jun_bal == 0:
                continue

            r = await conn.execute(text(SQL_DUES), {"phone": phone})
            db_rows = r.fetchall()

            apr_dues_db = 0
            may_dues_db = 0
            for dbr in db_rows:
                eff = int(dbr.eff_due or 0)
                rent_p = int(dbr.rent_paid or 0)
                dep_p = int(dbr.dep_paid or 0)
                total_paid = rent_p + dep_p
                dues = max(0, eff - total_paid)
                if str(dbr.period_month) == "2026-04-01":
                    apr_dues_db = dues
                elif str(dbr.period_month) == "2026-05-01":
                    may_dues_db = dues

            if apr_bal > 0:
                diff = apr_dues_db - apr_bal
                if abs(diff) > 50:
                    mismatches.append(f"APR {name:<32} sheet={apr_bal:>8,}  db={apr_dues_db:>8,}  diff={diff:>+8,}")
                else:
                    ok += 1

            if jun_bal > 0:
                diff = may_dues_db - jun_bal
                if abs(diff) > 50:
                    mismatches.append(f"MAY {name:<32} sheet={jun_bal:>8,}  db={may_dues_db:>8,}  diff={diff:>+8,}")
                else:
                    ok += 1

    await engine.dispose()
    print(f"Match (within Rs.50): {ok}")
    print(f"Mismatches          : {len(mismatches)}")
    for m in mismatches:
        print(" ", m)


asyncio.run(main())
