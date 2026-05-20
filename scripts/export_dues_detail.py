"""
Dues Detail Export — all tenants with pending dues (from DB)
Columns: Building, Name, Room, Check-in Date, May Check-in?, Stay Type,
         Agreed Rent, Security Deposit, Booking Amount Paid,
         Total Charged, Total Paid, Outstanding Dues, Months Pending

Output: data/reports/Dues_Detail_2026_05.xlsx
"""
import asyncio, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from datetime import date
from dotenv import load_dotenv
load_dotenv()

import asyncpg, openpyxl
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from openpyxl.utils import get_column_letter

# ── styles ────────────────────────────────────────────────────────────────────
HDR_FILL    = PatternFill('solid', fgColor='1F3864')
HDR_FONT    = Font(bold=True, color='FFFFFF', size=10)
MAY_FILL    = PatternFill('solid', fgColor='E2EFDA')   # green = May check-in
OLD_FILL    = PatternFill('solid', fgColor='FCE4D6')   # red = no payment at all
PART_FILL   = PatternFill('solid', fgColor='FFF2CC')   # yellow = partial
TOTAL_FILL  = PatternFill('solid', fgColor='BDD7EE')
TOTAL_FONT  = Font(bold=True, size=10)
NORM_FONT   = Font(size=10)
thin        = Side(style='thin', color='BBBBBB')
BORDER      = Border(left=thin, right=thin, top=thin, bottom=thin)
CENTER      = Alignment(horizontal='center', vertical='center', wrap_text=True)
RIGHT       = Alignment(horizontal='right', vertical='center')
LEFT        = Alignment(horizontal='left', vertical='center')
NUM_FMT     = '#,##0'
DATE_FMT    = 'DD-MMM-YYYY'

COL_HEADERS = [
    '#', 'Building', 'Name', 'Room', 'Phone',
    'Check-in Date', 'May Check-in?', 'Stay Type',
    'Agreed Rent', 'Security Deposit', 'Booking Paid',
    'Total Charged', 'Total Paid', 'Outstanding', 'Months Pending',
]
COL_WIDTHS = [4, 9, 28, 6, 14, 14, 13, 10, 12, 16, 13, 13, 11, 12, 30]
NUM_COLS   = {9, 10, 11, 12, 13, 14}  # 1-indexed money cols


async def main():
    db_url = os.getenv('DATABASE_URL').replace('postgresql+asyncpg', 'postgresql')
    conn = await asyncpg.connect(db_url)

    rows = await conn.fetch("""
        SELECT
            t.name,
            t.phone,
            r.room_number,
            r.building,
            tn.id               AS tenancy_id,
            tn.checkin_date,
            tn.stay_type,
            tn.agreed_rent,
            tn.security_deposit,
            tn.booking_amount,

            -- total rent charged (pending + partial months only)
            COALESCE((
                SELECT SUM(rs.rent_due + COALESCE(rs.adjustment, 0))
                FROM rent_schedule rs
                WHERE rs.tenancy_id = tn.id
                  AND rs.status IN ('pending', 'partial')
            ), 0) AS total_charged,

            -- total paid against those months (rent + deposit/booking in same period)
            COALESCE((
                SELECT SUM(p.amount)
                FROM payments p
                WHERE p.tenancy_id = tn.id
                  AND p.is_void = FALSE
                  AND (
                    p.for_type = 'rent'
                    OR (
                        p.for_type IN ('deposit', 'booking')
                        AND p.period_month IS NULL
                        AND p.payment_date >= (
                            SELECT MIN(rs2.period_month)
                            FROM rent_schedule rs2
                            WHERE rs2.tenancy_id = tn.id
                              AND rs2.status IN ('pending', 'partial')
                        )
                    )
                  )
            ), 0) AS total_paid,

            -- outstanding = charged - paid (floor 0)
            GREATEST(0,
                COALESCE((
                    SELECT SUM(rs.rent_due + COALESCE(rs.adjustment, 0))
                    FROM rent_schedule rs
                    WHERE rs.tenancy_id = tn.id
                      AND rs.status IN ('pending', 'partial')
                ), 0)
                -
                COALESCE((
                    SELECT SUM(p.amount)
                    FROM payments p
                    WHERE p.tenancy_id = tn.id
                      AND p.is_void = FALSE
                      AND (
                        p.for_type = 'rent'
                        OR (
                            p.for_type IN ('deposit', 'booking')
                            AND p.period_month IS NULL
                            AND p.payment_date >= (
                                SELECT MIN(rs2.period_month)
                                FROM rent_schedule rs2
                                WHERE rs2.tenancy_id = tn.id
                                  AND rs2.status IN ('pending', 'partial')
                            )
                        )
                      )
                ), 0)
            ) AS outstanding,

            -- pending month labels
            COALESCE((
                SELECT STRING_AGG(TO_CHAR(rs.period_month, 'Mon YYYY'), ', '
                                  ORDER BY rs.period_month)
                FROM rent_schedule rs
                WHERE rs.tenancy_id = tn.id
                  AND rs.status IN ('pending', 'partial')
            ), '') AS months_pending

        FROM tenancies tn
        JOIN tenants t  ON t.id  = tn.tenant_id
        JOIN rooms   r  ON r.id  = tn.room_id
        WHERE tn.status = 'active'
          AND r.is_staff_room = FALSE
          AND tn.stay_type != 'daily'
          AND EXISTS (
              SELECT 1 FROM rent_schedule rs
              WHERE rs.tenancy_id = tn.id
                AND rs.status IN ('pending', 'partial')
          )
        ORDER BY r.building, outstanding DESC, t.name
    """)

    await conn.close()

    # ── build output rows ─────────────────────────────────────────────────────
    data = []
    for row in rows:
        outstanding = float(row['outstanding'])
        if outstanding <= 0:
            continue
        may_checkin = (row['checkin_date'] and
                       row['checkin_date'].month == 5 and
                       row['checkin_date'].year == 2026)
        building = (row['building'] or '').upper()
        if 'HULK' in building:
            bname = 'HULK'
        elif 'THOR' in building:
            bname = 'THOR'
        else:
            bname = building or '?'

        data.append({
            'building':    bname,
            'name':        row['name'],
            'room':        row['room_number'],
            'phone':       row['phone'] or '',
            'checkin':     row['checkin_date'],
            'may_checkin': 'YES' if may_checkin else '',
            'stay_type':   row['stay_type'] or 'monthly',
            'agreed_rent':  float(row['agreed_rent'] or 0),
            'security_dep': float(row['security_deposit'] or 0),
            'booking_paid': float(row['booking_amount'] or 0),
            'charged':      float(row['total_charged'] or 0),
            'paid':         float(row['total_paid'] or 0),
            'outstanding':  outstanding,
            'months':       row['months_pending'] or '',
            'may_flag':     may_checkin,
        })

    print(f"Total tenants with outstanding dues: {len(data)}")
    print(f"  May check-ins in list: {sum(1 for d in data if d['may_flag'])}")
    total_due = sum(d['outstanding'] for d in data)
    print(f"  Total outstanding: Rs.{total_due:,.0f}")

    # ── write Excel ──────────────────────────────────────────────────────────
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    for bfilter in ['ALL', 'HULK', 'THOR']:
        rows_out = data if bfilter == 'ALL' else [d for d in data if d['building'] == bfilter]
        if not rows_out:
            continue

        ws = wb.create_sheet(bfilter)

        # Title row
        ws.merge_cells(f'A1:{get_column_letter(len(COL_HEADERS))}1')
        title = f'{bfilter} — Dues Detail — May 2026  (generated {date.today().strftime("%d %b %Y")})'
        ws['A1'] = title
        ws['A1'].font = Font(bold=True, size=13, color='1F3864')
        ws['A1'].alignment = CENTER
        ws.row_dimensions[1].height = 28

        # Header row
        for ci, h in enumerate(COL_HEADERS, 1):
            c = ws.cell(row=2, column=ci, value=h)
            c.fill = HDR_FILL; c.font = HDR_FONT
            c.alignment = CENTER; c.border = BORDER
        ws.row_dimensions[2].height = 22

        # Data rows
        tot_charged = tot_paid = tot_out = 0
        for i, d in enumerate(rows_out, 1):
            row_n = i + 2
            if d['may_flag']:
                fill = MAY_FILL
            elif d['paid'] == 0:
                fill = OLD_FILL
            else:
                fill = PART_FILL

            vals = [
                i,
                d['building'],
                d['name'],
                d['room'],
                d['phone'],
                d['checkin'],
                d['may_checkin'],
                d['stay_type'],
                d['agreed_rent'],
                d['security_dep'],
                d['booking_paid'],
                d['charged'],
                d['paid'],
                d['outstanding'],
                d['months'],
            ]
            for ci, v in enumerate(vals, 1):
                cell = ws.cell(row=row_n, column=ci, value=v)
                cell.fill = fill; cell.border = BORDER; cell.font = NORM_FONT
                if ci in NUM_COLS:
                    cell.alignment = RIGHT; cell.number_format = NUM_FMT
                elif ci == 6:   # check-in date
                    cell.alignment = CENTER; cell.number_format = DATE_FMT
                elif ci == 7:   # May check-in flag
                    cell.alignment = CENTER
                    if d['may_flag']:
                        cell.font = Font(bold=True, color='375623', size=10)
                else:
                    cell.alignment = LEFT

            tot_charged += d['charged']
            tot_paid    += d['paid']
            tot_out     += d['outstanding']

        # Totals row
        tot_row = len(rows_out) + 3
        totals = [None, '', 'TOTAL', '', '', None, '', '', None, None, None,
                  tot_charged, tot_paid, tot_out, '']
        for ci, v in enumerate(totals, 1):
            cell = ws.cell(row=tot_row, column=ci, value=v)
            cell.fill = TOTAL_FILL; cell.font = TOTAL_FONT; cell.border = BORDER
            if ci in NUM_COLS and isinstance(v, (int, float)):
                cell.alignment = RIGHT; cell.number_format = NUM_FMT
            else:
                cell.alignment = LEFT

        # Column widths
        for ci, w in enumerate(COL_WIDTHS, 1):
            ws.column_dimensions[get_column_letter(ci)].width = w
        ws.freeze_panes = 'A3'

    os.makedirs('data/reports', exist_ok=True)
    out_path = 'data/reports/Dues_Detail_2026_05.xlsx'
    wb.save(out_path)
    print(f"\nSaved: {out_path}")

    # ── console summary ───────────────────────────────────────────────────────
    print("\nTop 10 by outstanding:")
    for d in sorted(data, key=lambda x: -x['outstanding'])[:10]:
        flag = ' [MAY]' if d['may_flag'] else ''
        print(f"  {d['name']:<30}  Room {d['room']:>5}  Rs.{d['outstanding']:>8,.0f}{flag}")


asyncio.run(main())
