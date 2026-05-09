"""
src/reports/pnl_builder.py
---------------------------
Canonical P&L builder — single source of truth shared by:
  - scripts/export_pnl_2026_05_02.py  (local regeneration)
  - src/api/v2/finance.py  GET /finance/pnl/excel  (PWA download)

Both produce identical output. Verified figures as of 2026-05-03.
See memory/sop_pnl.md for full methodology.
"""
from __future__ import annotations

import io
from typing import Optional

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from src.utils.inr_format import INR_NUMBER_FORMAT

# ── Verified income figures (bank statement primary source) ───────────────────
# THOR = original building (Yes Bank acct 124563400000961)
# HULK = second building (Yes Bank acct 124563400000881, live from Mar 2026)
MONTHS = ["Oct'25", "Nov'25", "Dec'25", "Jan'26", "Feb'26", "Mar'26", "Apr'26"]

INCOME = {
    # THOR building (acct ...0961)
    "THOR — UPI batch settlements (merchant QR)":          [0,      0,        0,  175596, 2091597, 2515275, 2834731],
    "THOR — individual direct payments + NEFT":            [0, 723007, 1350547, 1083628,  420690,  225091,  226807],
    "THOR — transferred to HULK acct (reclassification)": [0,      0,        0,       0,       0,       0, -500000],
    "Cash (physical — both buildings combined)":           [0,      0,        0,  300572,  653300, 1094220, 1343783],
    # HULK building (acct ...0881) — live from Mar 2026
    "HULK — UPI batch settlements (merchant QR)":          [0,      0,        0,       0,       0,       0,  247719],
    "HULK — received from THOR acct (reclassification)":   [0,      0,        0,       0,       0,       0,  500000],
    "HULK — cheque / other deposits":                      [0,      0,        0,       0,       0,   71550,       0],
}

CAPITAL_CONTRIBUTIONS = {
    "Owner startup — Lakshmi SBI to Yes Bank (Oct 2025)": [500000, 0, 0,     0, 0, 0, 0],
    "Kiran top-up transfer (Jan 2026)":                   [     0, 0, 0, 90000, 0, 0, 0],
    # THOR→HULK ₹5L transfer (Apr 2026) is already in THOR income — internal bank move, not new capital
}

OPEX = {
    "Property Rent (cash — Jan rent paid Feb, Feb in Mar, Mar in Apr)": [0, 0, 0, 0, 2132000, 2132000, 2132000],
    "Electricity":                                                [0, 0, 0,       131554,  134538,   96617,  140659],
    "Water (bank tankers + Manoj cash; Mar bill paid Apr)":       [0, 0, 0,            0,       0,    8000,   84520],
    "IT & Software":                                              [0, 0, 3480,     10620,       0,       0,       0],
    "Internet & WiFi (cash — Jan Airwire UPI, Feb 8x Razorpay, Mar-Dec Rs.0)": [0, 0, 40946, 70730, 113168, 0, 0],
    "Food & Groceries":                                           [0, 33632, 88250, 201558,  94931,  237747,  233679],
    "Fuel & Diesel":                                              [0, 0, 200,       9099,  104366,  346308,    2800],
    "Staff & Labour":                                             [0, 1000, 125935, 112063, 219715,  155641,  199617],
    "Maintenance & Repairs":                                      [0, 0, 0,            0,     550,   18470,   30740],
    "Cleaning Supplies":                                          [0, 0, 4414,       1400,     700,    4566,   14500],
    "Waste Disposal (Pavan Rs.3.5K/mo)":                         [0, 0, 0,          3000,    3500,    3500,    3500],
    "Shopping & Supplies":                                        [0, 2730, 10530,  12036,   6127,    6184,    7442],
    "Operational Expenses":                                       [0, 0, 47769,     10315,   2174,    3237,  137319],
    "Marketing":                                                  [0, 0, 48500,     17895,   3620,   27700,       0],
    "Govt & Regulatory (incl Police Rs.3K accrual Jan+)":        [0, 0, 75716,     88073,   3000,    3000,    3000],
    "Bank Charges":                                               [0, 0, 0,           149,      0,       0,     100],
    "Other Expenses":                                             [0, 10318, 156337,  4564,  23258,   78780,   99306],
    # HULK building operational expenses (bank withdrawals — Apr ₹4,328)
    "HULK — Operational Expenses":                               [0,     0,     0,     0,      0,       0,    4328],
}

CAPEX = {
    # THOR/HULK Yes Bank + Lakshmi SBI direct vendor payments combined
    "Furniture & Fittings":                    [0, 370071, 419304, 203815, 1185397,   331,   2163],
    "Capital Investment (CCTV, 8 Ball Pool)":  [0,  82000,      0,      0,       0,     0,      0],
}

EXCLUDED = {
    "Tenant Deposit Refund (balance sheet)": [0, 10000,  21500,  55944,  74532,  138231, 129668],
    "Loan Repayment / Transfers (non-op)":   [0, 500000,     0,      0,  600000, 2090000, 22357],
}

# ── Deposit flows — queried from tenancies (security_deposit + maintenance_fee by check-in month)
# These are LIABILITY inflows — real cash but NOT revenue. Subtracted from gross income for True Revenue.
DEPOSIT_RECEIVED = [0, 448000, 838000, 1383000, 1074250, 1256450, 1161125]
# Deposit refunds = same figures as EXCLUDED["Tenant Deposit Refund"] — shown here for net calc
DEPOSIT_REFUNDED = [0, 10000,  21500,   55944,   74532,  138231,  129668]

# Security deposits = active tenants only (what we owe back), split by check-in month
# Maintenance fees  = all non-no-show tenants (non-refundable, retained), by check-in month
# Source: DB query 2026-05-06
DEPOSITS = {
    "Security Deposits — refundable (must return to active tenants)": [0, 193000, 386500, 633500, 498000, 812250, 798125],
    "  Maintenance Fee retained (non-refundable, by check-in month)": [0,  53000, 120000, 178000, 145000, 285700, 287000],
}

BANK_CLOSING_BALANCE_THOR = 1373863   # THOR acct ...0961 Apr 30
BANK_CLOSING_BALANCE_HULK =  814941   # HULK acct ...0881 Apr 30


def build_pnl_workbook() -> openpyxl.Workbook:
    """Return the canonical P&L workbook (Oct'25 – Apr'26)."""
    bold       = Font(bold=True)
    hdr_fill   = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
    hdr_font   = Font(bold=True, color="FFFFFF")
    total_fill = PatternFill(start_color="E7E6E6", end_color="E7E6E6", fill_type="solid")
    flag_fill  = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")
    ctr        = Alignment(horizontal="center")
    capex_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "P&L Summary"

    header = [""] + MONTHS + ["TOTAL"]
    ws.append(header)
    for c in ws[1]:
        c.fill = hdr_fill; c.font = hdr_font; c.alignment = ctr

    # 1. INCOME
    ws.append(["INCOME"])
    ws[ws.max_row][0].font = bold
    for label, row in INCOME.items():
        ws.append([label] + row + [sum(row)])
    rev_row = [sum(col) for col in zip(*INCOME.values())]
    ws.append(["Total Gross Inflows"] + rev_row + [sum(rev_row)])
    for c in ws[ws.max_row]:
        c.font = bold; c.fill = total_fill

    # Less: refundable security deposits (must return at exit — not revenue)
    sec_dep = DEPOSITS["Security Deposits — refundable (must return to active tenants)"]
    ws.append(["  Less: Security Deposits Received (refundable — must return at exit)"]
              + [-x for x in sec_dep] + [-sum(sec_dep)])
    for c in ws[ws.max_row]:
        c.font = Font(italic=True)

    # True Rent Revenue = gross − security deposits held
    true_rev_row = [r - s for r, s in zip(rev_row, sec_dep)]
    ws.append(["True Rent Revenue (excl. refundable deposits)"] + true_rev_row + [sum(true_rev_row)])
    for c in ws[ws.max_row]:
        c.font = bold
        c.fill = PatternFill(start_color="E2EFDA", end_color="E2EFDA", fill_type="solid")

    # Maintenance fee retained (non-refundable context)
    maint = DEPOSITS["  Maintenance Fee retained (non-refundable, by check-in month)"]
    ws.append(["  Note: Maintenance Fee retained (non-refundable, included above)"]
              + maint + [sum(maint)])
    for c in ws[ws.max_row]:
        c.font = Font(italic=True)
    ws.append([])

    # 3. CAPITAL CONTRIBUTIONS
    ws.append(["CAPITAL CONTRIBUTIONS (not P&L — owner's equity injections)"])
    ws[ws.max_row][0].font = bold
    for label, row in CAPITAL_CONTRIBUTIONS.items():
        ws.append([label] + row + [sum(row)])
    ws.append([])

    # 4. OPERATING EXPENSES
    ws.append(["OPERATING EXPENSES (accrual)"])
    ws[ws.max_row][0].font = bold
    for label, row in OPEX.items():
        ws.append([label] + row + [sum(row)])
        if "TBD" in label or "⚠" in label:
            for c in ws[ws.max_row]:
                c.fill = flag_fill

    ws.append(["EXCLUDED FROM OPEX (balance sheet items — not costs)"])
    ws[ws.max_row][0].font = Font(italic=True)
    for label, row in EXCLUDED.items():
        ws.append(["  " + label] + row + [sum(row)])

    opex_row = [sum(col) for col in zip(*OPEX.values())]
    ws.append(["Total Opex"] + opex_row + [sum(opex_row)])
    for c in ws[ws.max_row]:
        c.font = bold; c.fill = total_fill
    ws.append([])

    # 5. EBITDA / OPERATING PROFIT (true rent revenue − opex)
    op_profit_row = [r - o for r, o in zip(true_rev_row, opex_row)]
    ws.append(["EBITDA / OPERATING PROFIT"] + op_profit_row + [sum(op_profit_row)])
    for c in ws[ws.max_row]:
        c.font = bold

    op_margin_row = [f"{(p/r*100):.1f}%" if r else "-" for p, r in zip(op_profit_row, true_rev_row)]
    ws.append(["Operating Margin %"] + op_margin_row
              + [f"{(sum(op_profit_row)/sum(true_rev_row)*100):.1f}%" if sum(true_rev_row) else "-"])
    ws.append([])

    # 6. CAPEX
    ws.append(["CAPEX — ONE-TIME INVESTMENTS"])
    ws[ws.max_row][0].font = Font(bold=True, color="FFFFFF")
    ws[ws.max_row][0].fill = capex_fill
    for ci in range(2, len(header) + 1):
        ws.cell(ws.max_row, ci).fill = capex_fill
    for label, row in CAPEX.items():
        ws.append([label] + row + [sum(row)])
    capex_row = [sum(col) for col in zip(*CAPEX.values())]
    ws.append(["Total CAPEX"] + capex_row + [sum(capex_row)])
    for c in ws[ws.max_row]:
        c.font = bold; c.fill = total_fill
    ws.append([])

    # 7. NET PROFIT AFTER CAPEX
    profit_row = [op - cx for op, cx in zip(op_profit_row, capex_row)]
    ws.append(["NET PROFIT AFTER CAPEX"] + profit_row + [sum(profit_row)])
    for c in ws[ws.max_row]:
        c.font = bold

    margin_row = [f"{(p/r*100):.1f}%" if r else "-" for p, r in zip(profit_row, true_rev_row)]
    ws.append(["Net Margin %"] + margin_row
              + [f"{(sum(profit_row)/sum(true_rev_row)*100):.1f}%" if sum(true_rev_row) else "-"])
    ws.append([])

    # 8. CASH POSITION
    # Security deposits: collected from active tenants (refundable, must return at exit)
    _sec_collected  = sum(DEPOSITS["Security Deposits — refundable (must return to active tenants)"])
    _sec_refunded   = sum(EXCLUDED["Tenant Deposit Refund (balance sheet)"])
    _sec_net_owed   = _sec_collected - _sec_refunded   # what we still owe to tenants
    _bank_total     = BANK_CLOSING_BALANCE_THOR + BANK_CLOSING_BALANCE_HULK

    ws.append(["CASH POSITION (Apr 30)"])
    ws[ws.max_row][0].font = bold
    ws.append(["Bank closing balance THOR acct ...0961 (Apr 30)", "", "", "", "", "", "", BANK_CLOSING_BALANCE_THOR])
    ws.append(["Bank closing balance HULK acct ...0881 (Apr 30)", "", "", "", "", "", "", BANK_CLOSING_BALANCE_HULK])
    ws.append(["Total bank balance", "", "", "", "", "", "", _bank_total])
    for c in ws[ws.max_row]:
        c.font = bold
    ws.append(["Cash in hand (physical)", "", "", "", "", "", "", "← confirm with Kiran"])
    ws.append([])
    ws.append(["Security deposits collected (refundable, active tenants)", "", "", "", "", "", "", _sec_collected])
    ws.append(["Less: deposits already refunded to exited tenants", "", "", "", "", "", "", -_sec_refunded])
    ws.append(["Net deposits still owed to active tenants (liability)", "", "", "", "", "", "", _sec_net_owed])
    for c in ws[ws.max_row]:
        c.font = Font(bold=True, color="9C0006")
    ws.append([])
    ws.append(["True free cash (bank − deposits owed) — excl. cash in hand", "", "", "", "", "", "", _bank_total - _sec_net_owed])
    for c in ws[ws.max_row]:
        c.font = Font(bold=True)
    ws.append(["NOTE: negative = deposit money was used to fund early operations (CAPEX+OPEX)", "", "", "", "", "", "", ""])
    ws.append(["As revenue grows, bank balance will recover and exceed deposit liability", "", "", "", "", "", "", ""])
    ws.append([])

    # 9. FLAGS
    ws.append(["⚠ ITEMS NEEDING KIRAN REVIEW"])
    ws[ws.max_row][0].font = Font(bold=True, color="FF0000")
    for f in [
        "1. Manoj water bill for April (paid in May — amount TBD). Add to Water line when known.",
        "2. Apr rent of Rs.21,32,000 paid in May is outside this P&L window — will appear in May P&L.",
    ]:
        ws.append([f])

    # Number format
    for row in ws.iter_rows(min_row=2, max_col=len(header)):
        for i, cell in enumerate(row):
            if i == 0 or cell.value is None or isinstance(cell.value, str):
                continue
            if isinstance(cell.value, (int, float)):
                cell.number_format = INR_NUMBER_FORMAT

    ws.column_dimensions["A"].width = 58
    for col_letter in "BCDEFGHI":
        ws.column_dimensions[col_letter].width = 14

    # Sheet 2: Sub-category detail from DB (dynamic — call build_pnl_workbook_with_subcats for this)
    ws2 = wb.create_sheet("Rules Applied")
    rules = [
        ("Basis", "Accrual — expense in month of service, not payment"),
        ("Income source", "Bank statement credits (verified). Cash from DB payments table."),
        ("Property Rent", "Rs.22,14,000/mo accrual (164 beds × Rs.13,500). Feb–Apr. Nov-Jan zero (notice period)."),
        ("Water — Manoj B (9535665407)", "Cash basis. Apr = tanker Rs.42,020 + Mar bill Rs.42,500."),
        ("Internet & WiFi", "Cash-basis. Jan: Airwire Rs.70,730. Feb: 8x Razorpay Rs.1,13,168. Mar-Dec: Rs.0 (prepaid)."),
        ("Police", "Rs.3,000/mo cash accrual Jan onwards."),
        ("Waste Disposal", "Rs.3,500/mo (Pavan 6366411789)."),
        ("Prabhakaran (9444296681)", "All payments = Staff & Labour salary."),
        ("CAPEX", "Furniture & Fittings + CCTV/8-Ball Pool. Chairs/kitchen/atta machine moved to Operational Expenses."),
        ("Excluded from opex", "Tenant Deposit Refunds (liability) + Loan Repayments (non-operating)."),
    ]
    ws2.append(["Rule", "Detail"])
    for c in ws2[1]:
        c.fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
        c.font = Font(bold=True, color="FFFFFF")
    for k, v in rules:
        ws2.append([k, v])
    ws2.column_dimensions["A"].width = 40
    ws2.column_dimensions["B"].width = 110
    for row in ws2.iter_rows():
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")

    return wb


def build_pnl_bytes() -> bytes:
    """Return the P&L workbook as bytes (for streaming from FastAPI)."""
    buf = io.BytesIO()
    build_pnl_workbook().save(buf)
    buf.seek(0)
    return buf.read()
