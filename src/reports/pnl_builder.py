"""
src/reports/pnl_builder.py
---------------------------
Canonical P&L builder — single source of truth shared by:
  - scripts/export_pnl_2026_05_02.py  (local regeneration)
  - src/api/v2/finance.py  GET /finance/pnl/excel  (PWA download)

Both produce identical output. Verified figures as of 2026-05-12.
See memory/sop_pnl.md for full methodology.
"""
from __future__ import annotations

import io

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill

from src.utils.inr_format import INR_NUMBER_FORMAT

# ── Verified income figures (bank statement primary source) ───────────────────
# THOR = original building (Yes Bank acct 124563400000961)
# HULK = second building (Yes Bank acct 124563400000881, live from Mar 2026)
MONTHS = ["Oct'25", "Nov'25", "Dec'25", "Jan'26", "Feb'26", "Mar'26", "Apr'26"]

INCOME = {
    # THOR building (acct ...0961)
    "THOR — UPI batch settlements (merchant QR)":          [0,      0,        0,  175596, 2091597, 2515275, 2834731],
    "THOR — individual direct payments + NEFT":            [0, 723007, 1350547, 1083628,  420690,  385691,  226807],  # Mar: +160600 Chandra cash collection reclassified to bank (2026-05-12)
    "THOR — transferred to HULK acct (reclassification)": [0,      0,        0,       0,       0,       0, -500000],
    "Cash (physical — both buildings combined)":           [0,      0,        0,  325572,  656300, 1094220, 1390783],  # Jan +25000 Bala uncle; Feb +3000 Bala uncle; Apr +35000 Bala uncle + 12000 cash exchanges. Mar: Chandra ₹1.60L moved to UPI (2026-05-12)
    # HULK building (acct ...0881) — live from Mar 2026
    "HULK — UPI batch settlements (merchant QR)":          [0,      0,        0,       0,       0,       0,  247719],
    "HULK — received from THOR acct (reclassification)":   [0,      0,        0,       0,       0,       0,  500000],
    "HULK — cheque / other deposits":                      [0,      0,        0,       0,       0,   71550,       0],
}

CAPITAL_CONTRIBUTIONS = {
    "Owner startup — Lakshmi SBI to Yes Bank (Oct 2025)": [500000,      0, 0,     0,     0,   0,    0],
    "Owner startup — repaid via NEFT Nov (₹50K + ₹4.5L to Bharathi)": [0, -500000, 0, 0, 0, 0, 0],
    "Kiran top-up transfer (Jan 2026)":                   [     0,      0, 0, 90000,     0,   0,    0],
    # Partner personal advances (reimbursable — company owes Lakshmi this back)
    # Dec: ₹74,768 BESCOM via partner UPI 7358341775-2@ybl (moved to Electricity expense)
    # Jan–Apr: personal SBI 0167 payments matching OPEX Partner Reimbursable line
    "Partner advance — Lakshmi (personal UPI + SBI 0167, reimbursable)": [0, 0, 74768, 41899, 18264, 750, 6928],
    # Chandra personal cash for PG operations — "Other Expenses" cash residual (untracked ops spend)
    # ⚠ TBD — confirm with Chandra that these are his personal cash advances (not already paid by company)
    "Chandra advance — operational cash (TBD confirm)":             [0,     0,      0,     0,     0, 32789, 38111],
    # Kiran PhonePe/cash for PG ops — company owes Kiran back (equity injection)
    # Nov: PhonePe — Sachin C porter, Jaya Thyagaraj, somanath, VENKATA SAI ALUMINIUM, SAMPATH R, D BABULAL, Dinesh K R, C A Enterprises, Rafeeq, MAURYA AGENCIES, RAM KHILADI, SADAF MOHAMMAD, Mr V AKIL ₹10,669 (Other Expense)
    # Dec: PhonePe — WorkIndia ₹2,773, SLN Packaging ₹760, BIPLAB SINGHA ×2 ₹15,000, Zepto ₹135, Printout ₹663, Shashikala S ₹200
    #      Cash  — fire extinguisher ₹1,700, curtains ₹970, HP cylinders ₹6,616, kitchen porter ₹500, cooker lock ₹80, stickers ₹1,020
    #      Cash  — Unisol CCTV system ₹1,00,000, BBMP garbage fine ₹6,000
    # Jan: PhonePe — BBMP fine ₹6K, SN Shop first-aid ₹2,250, ninjacart ₹5,965, Dhanalakshmi hardware ₹450, Shrinivas IT ₹500, ADARSH E V porter ₹760, KAIZEN Engineering ₹30, RADHAKRISHNAN E ₹700 (Other Expense)
    #      Cash  — WorkIndia sub ₹2,773 (Dec charge/Jan sub), plants porter ₹857, 3 wifi recharges ₹3,000, 2 gas cylinders ₹8,000, ₹200 lost, invertor return ₹560
    # Feb: PhonePe — Zepto ₹654
    # Ignored (personal): 9444448314 Dec ₹5,000 + Apr ₹5,000
    "Kiran advance — PhonePe/cash for PG ops": [0, 39001, 136517, 32045, 654, 0, 0],
}

OPEX = {
    "Property Rent — Cash paid (Jan rent in Feb, Feb in Mar, Mar in Apr)": [0, 0, 0, 0, 1532000, 1290000, 1449100],  # Feb+Apr Kiran confirmed; Mar corrected to 12,90,000 (Kiran 2026-05-12)
    "Property Rent — Bank UPI/RTGS paid":                                  [0, 0, 0, 0,  600000,  605140,  600000],  # Feb+Apr+Mar confirmed by Kiran (2026-05-12)
    "Electricity":                                                [0, 0, 74768,   131554,  134538,   96617,  140659],  # Dec: BESCOM via BBPSBP@ybl (was misclassified as BBMP Tax)
    "Water (bank tankers + Manoj cash; Mar bill paid Apr)":       [0, 0, 0,            0,       0,    8000,   84520],
    "IT & Software":                                              [0, 0, 3480,     11120,       0,       0,       0],  # Jan +500 Shrinivas IT band (Kiran PhonePe Jan 6)
    "Internet & WiFi (cash — Jan Airwire UPI, Feb 8x Razorpay, Mar-Dec Rs.0)": [0, 0, 43946, 70730, 113168, 0, 0],  # Dec +3000 wifi dongles (Kiran cash)
    "Food & Groceries":                                           [0, 33632, 113787, 216418,  114803,  240294,  238122],  # Dec +6616 HP gas cash; Feb +2195 Chandra cash. Updated 2026-05-12 (DB+cash reconcile, prev+this session reclassify)
    "Fuel & Diesel":                                              [0, 0, 1200,      9099,  105866,  355971,   61578],  # Dec +1000 HP Auto cash; Feb +1500 Chandra; Mar +6370 Chandra diesel. Apr: 8951297583 diesel ₹49679 reclassified from Other
    "Staff & Labour":                                             [0, 1000, 135435, 115924, 233715,  188341,  193617],  # Dec +500 cash porter; Mar +32600 cash labour. Updated 2026-05-12 (Vivek+Bhukesh reclassified from Other)
    "Maintenance & Repairs":                                      [0, 0, 1400,     22450,    1850,   21899,   36919],  # Jan +22450 cash (KAIZEN+Chandra); Mar +900 Chandra elec. Dec: key maker+carpenter from Other
    "Cleaning Supplies":                                          [0, 0, 5674,       1400,    1200,   11272,   17975],  # Dec +760 SLN cash. Triveni (9448259556/9989000250) + Wellcare reclassified from Other
    "Waste Disposal (Pavan Rs.3.5K/mo)":                         [0, 0, 0,          3000,    3500,    3500,    3500],
    "Shopping & Supplies":                                        [0, 2730, 35548,  12153,   6127,    6184,    9858],  # Dec +1020 stickers cash; Dec D-Mart ₹23998 (tpasha638) reclassified from Other
    "Operational Expenses":                                       [0, 318, 121970,  18388,   5815,   34950,  146594],  # Dec +1713 cash. Updated 2026-05-12 (volipi, PERSONAL_SBI, Chandra advances, mobile recharges from Other)
    "Marketing":                                                  [0, 0, 66273,     35595,   7620,   27700,       0],  # Dec +17773 cash. Jan: ₹17700 reclassified from Other (prev session). Feb: Saurav flyers ₹4000
    "Govt & Regulatory (incl Police Rs.3K accrual Jan+)":        [0, 0,  6948,     94073,   3000,    3000,    3000],  # Dec: 948 BBMP + 6000 garbage fine cash (74768 BESCOM moved to Electricity); Jan +6000 BBMP cash
    "Bank Charges":                                               [0, 0, 0,           149,      0,       0,     100],
    "Other Expenses":                                             [0, 15987, 2781,     700,     200,   32789,   38111],  # Nov +10669 Mr V AKIL (Kiran PhonePe); Jan +700 RADHAKRISHNAN E (Kiran PhonePe). Updated 2026-05-12
    # HULK building operational expenses (bank withdrawals — Apr ₹4,328)
    "HULK — Operational Expenses":                               [0,     0,     0,     0,      0,       0,    4328],
    # Partner personal SBI (0167) payments for PG business — reimbursable from company account
    # Detail: data/reports/SBI_0167_Reimbursement.xlsx
    "Partner Reimbursable (Personal Acct SBI 0167)":            [0,     0,     0, 41899,  18264,     750,    6928],
}

CAPEX = {
    # THOR/HULK Yes Bank + Lakshmi SBI direct vendor payments combined
    "Furniture & Fittings":                    [0, 125021, 167741, 203815, 1185597,  10761,  12363],  # Nov: -24800 Lavanya (net). Updated 2026-05-12: porter charges (bed frames, shoe racks, study tables) + photo frame reclassified from Other
    "Capital Investment (CCTV, 8 Ball Pool)":  [0,  82000, 100000,      0,       0,     0,      0],  # Dec +100000 Unisol CCTV system (Kiran cash Dec 2025)
}

EXCLUDED = {
    # Tenant deposit refunds are balance-sheet items only (return of liability) — not operating costs
    "Tenant Deposit Refund (balance sheet)":  [0,  15000,  47344,  55944,  74532,  182441, 151163],  # Updated 2026-05-12
    # Cash-exchange repayments: someone gave physical cash → used for ops (already in OPEX) → repaid via bank RTGS
    # Feb: Sri Lakshmi Chandrasekar ₹6L. Mar: YESMIDAS + Sravani + Sri Lakshmi etc. ₹20.9L. Apr: ₹22K misc.
    # Nov ₹5L REMOVED — that was the startup capital repayment (shown in Capital Contributions above), not a cash exchange.
    # NOT an operating cost — the cash was already spent and counted in OPEX categories above.
    "Cash Exchange Repayments via Bank (non-op)": [0,      0,     0,      0,  600000, 2090000,  22357],
}

# ── Deposit flows — queried from tenancies (security_deposit + maintenance_fee by check-in month)
# These are LIABILITY inflows — real cash but NOT revenue. Subtracted from gross income for True Revenue.
DEPOSIT_RECEIVED = [0, 448000, 838000, 1383000, 1074250, 1256450, 1161125]
# Deposit refunds = same figures as EXCLUDED["Tenant Deposit Refund"] — shown here for net calc
DEPOSIT_REFUNDED = [0, 10000,  21500,   55944,   74532,  160231,  139638]  # Mar +22000, Apr +9970 (personal SBI)

# Security deposits = active tenants only (what we owe back), split by check-in month
# Maintenance fees  = all non-no-show tenants (non-refundable, retained), by check-in month
# Source: DB query 2026-05-06
DEPOSITS = {
    "Security Deposits — refundable (must return to active tenants)": [0, 193000, 386500, 633500, 498000, 812250, 860625],  # Apr updated: +62500 to match Kiran's confirmed total ₹33,83,875 (was ₹33,21,375)
    "  Maintenance Fee retained (non-refundable, by check-in month)": [0,  53000, 120000, 178000, 145000, 285700, 287000],
}

BANK_CLOSING_BALANCE_THOR = 1373863   # THOR acct ...0961 Apr 30
BANK_CLOSING_BALANCE_HULK =  814941   # HULK acct ...0881 Apr 30

CASH_IN_HAND = {
    "Lakshmi cash":             1063500,  # Apr 30 confirmed
    "Prabhakaran cash holding":  823350,  # Apr 30 confirmed
}


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
    assert ws is not None
    ws.title = "P&L Summary"

    # Op column (B) shows +/−/= for each row so the P&L flow is unambiguous
    header = ["", "Op"] + MONTHS + ["TOTAL"]
    ws.append(header)
    for c in ws[1]:
        c.fill = hdr_fill; c.font = hdr_font; c.alignment = ctr

    # 1. INCOME
    ws.append(["INCOME", ""])
    ws[ws.max_row][0].font = bold
    for label, row in INCOME.items():
        sign = "−" if "transferred to HULK" in label else "+"
        ws.append([label, sign] + row + [sum(row)])
    rev_row = [sum(col) for col in zip(*INCOME.values())]
    ws.append(["Total Gross Inflows", "="] + rev_row + [sum(rev_row)])
    for c in ws[ws.max_row]:
        c.font = bold; c.fill = total_fill

    # Deduct 1: active tenant deposits — liability, still owe back at exit
    sec_dep_collected = DEPOSITS["Security Deposits — refundable (must return to active tenants)"]
    maint_fee_collected = DEPOSITS["  Maintenance Fee retained (non-refundable, by check-in month)"]
    sec_dep_neg = [-v for v in sec_dep_collected]
    ws.append(["  Less: Security Deposits held (active tenants — must return at exit)", "−"]
              + sec_dep_neg + [sum(sec_dep_neg)])
    ws[ws.max_row][0].font = Font(italic=True)

    # Informational sub-row: maintenance fee retained alongside security deposit (not deducted — it's income)
    ws.append(["     └ Maintenance Fee retained from same tenants (non-refundable — yours to keep)", "(kept)"]
              + list(maint_fee_collected) + [sum(maint_fee_collected)])
    ws[ws.max_row][0].font = Font(italic=True, color="375623")
    for c in ws[ws.max_row][1:]:
        if isinstance(c.value, (int, float)):
            c.font = Font(italic=True, color="375623")

    # Deduct 2: deposits already refunded to exited tenants — collected but paid back (pass-through)
    dep_refunded = EXCLUDED["Tenant Deposit Refund (balance sheet)"]
    dep_refunded_neg = [-v for v in dep_refunded]
    ws.append(["  Less: Deposits Refunded to Exited Tenants (already paid back)", "−"]
              + dep_refunded_neg + [sum(dep_refunded_neg)])
    ws[ws.max_row][0].font = Font(italic=True)

    true_rev_row = [r + s + d for r, s, d in zip(rev_row, sec_dep_neg, dep_refunded_neg)]
    ws.append(["True Rent Revenue (excl. all deposit pass-throughs)", "="] + true_rev_row + [sum(true_rev_row)])
    for c in ws[ws.max_row]:
        c.font = Font(bold=True, color="375623")
    ws.append([])

    # 3. CAPITAL CONTRIBUTIONS
    ws.append(["CAPITAL CONTRIBUTIONS (not P&L — owner's equity injections)", ""])
    ws[ws.max_row][0].font = bold
    for label, row in CAPITAL_CONTRIBUTIONS.items():
        ws.append([label, "↑"] + row + [sum(row)])
    ws.append([])

    # 4. OPERATING EXPENSES
    ws.append(["OPERATING EXPENSES (accrual)", ""])
    ws[ws.max_row][0].font = bold
    for label, row in OPEX.items():
        ws.append([label, "−"] + row + [sum(row)])
        if "TBD" in label or "⚠" in label:
            for c in ws[ws.max_row]:
                c.fill = flag_fill

    ws.append(["EXCLUDED FROM OPEX (balance sheet items — not costs)", ""])
    ws[ws.max_row][0].font = Font(italic=True)
    for label, row in EXCLUDED.items():
        ws.append(["  " + label, "(B/S)"] + row + [sum(row)])

    opex_row = [sum(col) for col in zip(*OPEX.values())]
    ws.append(["Total Opex", "="] + opex_row + [sum(opex_row)])
    for c in ws[ws.max_row]:
        c.font = bold; c.fill = total_fill
    ws.append([])

    # 5. EBITDA / OPERATING PROFIT (true rent revenue − opex)
    op_profit_row = [r - o for r, o in zip(true_rev_row, opex_row)]
    ws.append(["EBITDA / OPERATING PROFIT (on True Revenue)", "="] + op_profit_row + [sum(op_profit_row)])
    for c in ws[ws.max_row]:
        c.font = bold

    op_margin_row = [f"{(p/r*100):.1f}%" if r else "-" for p, r in zip(op_profit_row, true_rev_row)]
    ws.append(["Operating Margin %", ""] + op_margin_row
              + [f"{(sum(op_profit_row)/sum(true_rev_row)*100):.1f}%" if sum(true_rev_row) else "-"])
    ws.append([])

    # 6. CAPEX
    ws.append(["CAPEX — ONE-TIME INVESTMENTS", ""])
    ws[ws.max_row][0].font = Font(bold=True, color="FFFFFF")
    ws[ws.max_row][0].fill = capex_fill
    for ci in range(2, len(header) + 1):
        ws.cell(ws.max_row, ci).fill = capex_fill
    for label, row in CAPEX.items():
        ws.append([label, "−"] + row + [sum(row)])
    capex_row = [sum(col) for col in zip(*CAPEX.values())]
    ws.append(["Total CAPEX", "="] + capex_row + [sum(capex_row)])
    for c in ws[ws.max_row]:
        c.font = bold; c.fill = total_fill
    ws.append([])

    # 7. NET PROFIT AFTER CAPEX
    profit_row = [op - cx for op, cx in zip(op_profit_row, capex_row)]
    ws.append(["NET PROFIT AFTER CAPEX", "="] + profit_row + [sum(profit_row)])
    for c in ws[ws.max_row]:
        c.font = bold

    margin_row = [f"{(p/r*100):.1f}%" if r else "-" for p, r in zip(profit_row, true_rev_row)]
    ws.append(["Net Margin %", ""] + margin_row
              + [f"{(sum(profit_row)/sum(true_rev_row)*100):.1f}%" if sum(true_rev_row) else "-"])
    ws.append([])

    # 8. CASH POSITION
    # _sec_collected = from operational Excel: sum of security_deposit column for all tenants checked in ≤ Apr 30
    # Updated 2026-05-12: Kiran confirmed ₹33,83,875 from source Excel (screenshot verification)
    _sec_collected  = 3383875
    _bank_total     = BANK_CLOSING_BALANCE_THOR + BANK_CLOSING_BALANCE_HULK

    _cash_total = sum(CASH_IN_HAND.values())

    # Cash position rows show a single snapshot figure — placed in the Apr'26 column (position 8)
    ws.append(["CASH POSITION (Apr 30)", ""])
    ws[ws.max_row][0].font = bold
    ws.append(["Bank closing balance THOR acct ...0961 (Apr 30)", "", "", "", "", "", "", "", BANK_CLOSING_BALANCE_THOR])
    ws.append(["Bank closing balance HULK acct ...0881 (Apr 30)", "", "", "", "", "", "", "", BANK_CLOSING_BALANCE_HULK])
    ws.append(["Total bank balance", "", "", "", "", "", "", "", _bank_total])
    for c in ws[ws.max_row]:
        c.font = bold
    ws.append([])
    ws.append(["Cash in hand (physical)", ""])
    ws[ws.max_row][0].font = bold
    for name, amt in CASH_IN_HAND.items():
        ws.append(["  " + name, "", "", "", "", "", "", "", amt])
    ws.append(["Total cash in hand", "", "", "", "", "", "", "", _cash_total])
    for c in ws[ws.max_row]:
        c.font = bold
    ws.append([])
    ws.append(["Net deposits still owed to active tenants (liability)", "", "", "", "", "", "", "", _sec_collected])
    for c in ws[ws.max_row]:
        c.font = Font(bold=True, color="9C0006")
    ws.append([])
    ws.append(["True free cash (bank − deposits owed) — excl. cash in hand", "", "", "", "", "", "", "", _bank_total - _sec_collected])
    for c in ws[ws.max_row]:
        c.font = Font(bold=True)
    ws.append(["True free cash incl. cash in hand", "", "", "", "", "", "", "", _bank_total + _cash_total - _sec_collected])
    for c in ws[ws.max_row]:
        c.font = Font(bold=True)
    ws.append(["NOTE: negative = deposit money was used to fund early operations (CAPEX+OPEX)", "", "", "", "", "", "", "", ""])
    ws.append(["As revenue grows, bank balance will recover and exceed deposit liability", "", "", "", "", "", "", "", ""])
    ws.append([])

    # 9. FLAGS
    ws.append(["⚠ ITEMS NEEDING KIRAN REVIEW", ""])
    ws[ws.max_row][0].font = Font(bold=True, color="FF0000")
    for f in [
        "1. Manoj water bill for April (paid in May — amount TBD). Add to Water line when known.",
        "2. Apr rent of Rs.21,32,000 paid in May is outside this P&L window — will appear in May P&L.",
        "3. Chandra advance (Mar Rs.32,789 + Apr Rs.38,111) — confirm these are Chandra's personal cash advances for PG ops, not company-paid cash already counted above.",
        "4. Kiran advance ~Rs.1,10,897 total (Staff Rs.33K, Maint Rs.23K, Mktg Rs.18K, Govt Rs.12K, Food Rs.9K, Fuel Rs.9K, Internet Rs.3K, Operational Rs.2K, Shopping Rs.1K, IT Rs.500, Cleaning Rs.760). Provide month-by-month split to fill the Capital Contributions row.",
        "5. Cash Exchange Repayments (in EXCLUDED): Nov Rs.5L Bharathi, Feb Rs.6L Sri Lakshmi Chandrasekar, Mar Rs.20.9L (YESMIDAS+Sravani+Sri Lakshmi), Apr Rs.22K. Bank RTGS repaid to people who gave you cash for ops — underlying spending already in OPEX above.",
    ]:
        ws.append([f, ""])

    # Number format — skip col A (i=0) and Op col B (strings are skipped automatically)
    for row in ws.iter_rows(min_row=2, max_col=len(header)):
        for i, cell in enumerate(row):
            if i == 0 or cell.value is None or isinstance(cell.value, str):
                continue
            if isinstance(cell.value, (int, float)):
                cell.number_format = INR_NUMBER_FORMAT

    # Centre-align the Op column
    for row in ws.iter_rows(min_row=1, min_col=2, max_col=2):
        for cell in row:
            cell.alignment = Alignment(horizontal="center")

    ws.column_dimensions["A"].width = 58
    ws.column_dimensions["B"].width = 6   # Op column
    for col_letter in "CDEFGHIJ":
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
