"""
src/reports/pnl_builder.py
---------------------------
Canonical P&L builder — single source of truth shared by:
  - scripts/export_pnl_2026_05_02.py  (local regeneration)
  - src/api/v2/finance.py  GET /finance/pnl/excel  (PWA download)

Both produce identical output. Verified figures as of 2026-05-12.
See memory/sop_pnl.md for full methodology.

Workbook tabs:
  1. P&L — Full (incl Cash)   — all items, canonical report
  2. Bank — Digital Only       — same layout; cash income + cash rent excluded
  3. Rules Applied             — methodology notes
"""
from __future__ import annotations

import io
from typing import Dict, List

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.worksheet import Worksheet

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
    "Cash (physical — both buildings combined)":           [0,      0,        0,  325572,  656300, 1094220, 1378783],  # Jan +25000 Bala uncle; Feb +3000 Bala uncle; Apr +35000 Bala uncle (−12000 moved to May — collected in May). Mar: Chandra ₹1.60L moved to UPI (2026-05-12)
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
    #      Cash  — BBMP garbage fine ₹6,000, PG marketing 3rd payment ₹7,500 + marketing ₹7,500
    #      NOTE: Unisol CCTV ₹1,00,000 tracked in CAPEX only — not duplicated here
    # Jan: PhonePe — BBMP fine ₹6K, SN Shop first-aid ₹2,250, ninjacart ₹5,965, Dhanalakshmi hardware ₹450, Shrinivas IT ₹500, ADARSH E V porter ₹760, KAIZEN Engineering ₹30, RADHAKRISHNAN E ₹700 (Other Expense)
    #      Cash  — WorkIndia sub ₹2,773 (Dec charge/Jan sub), plants porter ₹857, 3 wifi recharges ₹3,000, 2 gas cylinders ₹8,000, ₹200 lost, invertor return ₹560
    # Feb: PhonePe — Zepto ₹654
    # Ignored (personal): 9444448314 Dec ₹5,000 + Apr ₹5,000
    "Kiran advance — PhonePe/cash for PG ops": [0, 39001, 51517, 32045, 654, 0, 0],
}

OPEX = {
    "Property Rent — Cash paid (Jan rent in Feb, Feb in Mar, Mar in Apr)": [0, 0, 0, 0, 1532000, 1290000, 1449100],  # Feb+Apr Kiran confirmed; Mar corrected to 12,90,000 (Kiran 2026-05-12)
    "Property Rent — Bank UPI/RTGS paid":                                  [0, 0, 0, 0,  600000,  605140,  600000],  # Feb+Apr+Mar confirmed by Kiran (2026-05-12)
    "Electricity":                                                [0, 0, 74768,   131554,  134538,   96617,  140659],  # Dec: BESCOM via BBPSBP@ybl
    "Water (bank tankers + Manoj cash; Mar bill paid Apr)":       [0, 0, 0,            0,       0,    8000,   84520],
    "IT & Software":                                              [0, 0, 3480,     12068,     934,    1128,    2348],  # Jan +948 office phone; Feb +934 mobile recharge; Mar +1128 paybil/payair; Apr +2348. Updated 2026-05-13
    "Internet & WiFi (cash — Jan Airwire UPI, Feb 8x Razorpay, Mar-Dec Rs.0)": [0, 0, 43946, 70730, 113168, 0, 0],  # Dec +3000 wifi dongles (Kiran cash)
    "Food & Groceries":                                           [0, 33632, 113787, 217504,  115595,  240294,  238878],  # Jan +1086 Origin veg; Feb +792 Amazon India food; Apr +756 Ratnadeep fruits. Updated 2026-05-13
    "Fuel & Diesel":                                              [0, 0, 1200,      9599,  105866,  355971,   61904],  # Jan +500 Shell India; Apr +326 volipi.l bus ticket. Updated 2026-05-13
    "Staff & Labour":                                             [0, 1000, 135435, 116714, 234295,  217341,  193617],  # Jan +790 petty wages; Feb +580 petty wages; Mar +29000 volipi.l salary. Updated 2026-05-13
    "Maintenance & Repairs":                                      [0, 0, 1400,     22450,    1850,   21899,   36919],
    "Cleaning Supplies":                                          [0, 0, 5674,       1880,    1200,   11272,   18315],  # Jan +480 Hinglaj packaging; Apr +340 kastig soda. Updated 2026-05-13
    "Waste Disposal (Pavan Rs.3.5K/mo)":                         [0, 0, 0,          3000,    3500,    3500,    3500],
    # Shopping & Supplies — small operational purchases (akhil setup, misc UPI, nursery decor, CHANDRASEKHAR ops advance etc.)
    # Updated 2026-05-13: reclassified all items from Operational Expenses; Nov nursery; Dec: Chandra 70K+akhil 28.7K+cash 1.7K; Jan: akhil+Q531; Feb: SV251+paytm+ME+Global+paytmqr; Mar: 9902+volipi.l 444+balaji; Apr: volipi.l mirrors
    "Shopping & Supplies":                                        [0, 3048, 136960,  18323,   7662,    7770,   10258],
    # Furniture & Supplies — ALL furniture, equipment, Amazon purchases from PG bank (2026-05-13: CAPEX folded into OPEX per Kiran)
    # Old CAPEX (F&F + Capital Inv) + chairs ₹47K + atta machine ₹21K + kitchen vessels ₹37.5K + Amazon all months
    # Nov: F&F 125021 + CCTV/8-Ball 82000. Dec: F&F 167741 + CCTV 100000 + Amazon 19014. Jan: F&F 203815 + Amazon 8414 (4707+3707 cash-counter). Feb: F&F 1185597 + Amazon 2174. Mar: F&F 10761 + Amazon 3237. Apr: F&F 12363 + chairs 47000 + atta 21060 + kitchen 37500 + Amazon 30756
    "Furniture & Supplies":                                       [0, 207021, 286755, 212229, 1187771,  13998,  148679],
    "Marketing":                                                  [0, 0, 81273,     35595,   7620,   27700,    1003],  # Apr +1003 Naukri job posting. Updated 2026-05-13
    "Govt & Regulatory (incl Police Rs.3K accrual Jan+)":        [0, 0,  6948,     99673,   3000,    3000,    3000],  # Jan +5600: Jitendra cash — BBMP ₹5K + Agreement ₹600 (police ₹3K was already in accrual). 2026-05-14
    "Bank Charges":                                               [0, 0, 0,           149,      0,       0,     100],
    "Other Expenses":                                             [0, 15987, 2781,     700,       0,   32789,   38111],  # Feb: paytmqr ₹200 reclassified to Shopping & Supplies. Updated 2026-05-13
    # HULK building operational expenses (bank withdrawals — Apr ₹4,328)
    "HULK — Operational Expenses":                               [0,     0,     0,     0,      0,       0,    4328],
    # Partner personal SBI (0167) payments for PG business — reimbursable from company account
    # Detail: data/reports/SBI_0167_Reimbursement.xlsx
    "Partner Reimbursable (Personal Acct SBI 0167)":            [0,     0,     0, 41899,  18264,     750,    6928],
}
# NOTE: CAPEX removed 2026-05-13 per Kiran — all furniture/equipment spent from PG bank account
# folded into OPEX as "Furniture & Supplies". No separate CAPEX section.

EXCLUDED = {
    # Tenant deposit refunds are balance-sheet items only (return of liability) — not operating costs
    "Tenant Deposit Refund (balance sheet)":  [0,  15000,  47344,  55944,  74532,  182441, 151163],  # Updated 2026-05-12
    # Cash-exchange repayments: someone gave physical cash → used for ops (already in OPEX) → repaid via bank RTGS
    # Feb: Sri Lakshmi Chandrasekar ₹6L. Mar: YESMIDAS + Sravani + Sri Lakshmi etc. ₹15.9L. Apr: ₹22K misc.
    # Nov ₹5L REMOVED — startup capital repayment (Capital Contributions above), not a cash exchange.
    # Mar ₹5L Bharathi REMOVED — covered by THOR→HULK intercompany transfer, not a separate P&L item.
    # NOT an operating cost — the cash was already spent and counted in OPEX categories above.
    "Cash Exchange Repayments via Bank (non-op)": [0,      0,     0,      0,  600000, 1590000,  22357],
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
    # Pure refundable security only (combined total was ₹33,83,875 but included maintenance ₹10,68,700)
    # True refundable = combined − maintenance = ₹33,83,875 − ₹10,68,700 = ₹23,15,175
    "Security Deposits — refundable (must return to active tenants)": [0, 140000, 266500, 455500, 353000, 526550, 573625],
    "  Maintenance Fee retained (non-refundable, by check-in month)": [0,  53000, 120000, 178000, 145000, 285700, 287000],
}

BANK_CLOSING_BALANCE_THOR = 1373863   # THOR acct ...0961 Apr 30
BANK_CLOSING_BALANCE_HULK =  814941   # HULK acct ...0881 Apr 30

CASH_IN_HAND = {
    "Lakshmi cash (Mar closing ₹2,42,617 → Apr closing)":  820883,  # Apr 30 confirmed 2026-05-13
    "Prabhakaran cash holding":                              524400,  # Apr 30 confirmed 2026-05-13
}

# ── Cash items to exclude for the Bank-Only tab ───────────────────────────────
# Income key containing this fragment is skipped
_CASH_INCOME_KEY  = "Cash (physical"
# OPEX key containing this fragment is skipped
_CASH_RENT_KEY    = "Property Rent — Cash paid"


# ── Shared P&L sheet writer ───────────────────────────────────────────────────

def _write_pnl_tab(
    ws: Worksheet,
    income_dict: Dict[str, List[int]],
    opex_dict: Dict[str, List[int]],
    tab_note: str = "",
) -> None:
    """
    Render a complete P&L into *ws*.

    income_dict / opex_dict are the (possibly filtered) subsets of INCOME / OPEX.
    tab_note is shown in the top-left header cell when provided.
    """
    bold       = Font(bold=True)
    hdr_fill   = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
    hdr_font   = Font(bold=True, color="FFFFFF")
    total_fill = PatternFill(start_color="E7E6E6", end_color="E7E6E6", fill_type="solid")
    flag_fill  = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")
    ctr        = Alignment(horizontal="center")

    header = [tab_note or "", "Op"] + MONTHS + ["TOTAL"]
    ws.append(header)
    for c in ws[1]:
        c.fill = hdr_fill; c.font = hdr_font; c.alignment = ctr

    # ── 1. INCOME ──────────────────────────────────────────────────────────────
    ws.append(["INCOME", ""])
    ws[ws.max_row][0].font = bold
    for label, row in income_dict.items():
        sign = "−" if "transferred to HULK" in label else "+"
        ws.append([label, sign] + row + [sum(row)])
    rev_row = [sum(col) for col in zip(*income_dict.values())]
    ws.append(["Total Gross Inflows", "="] + rev_row + [sum(rev_row)])
    for c in ws[ws.max_row]:
        c.font = bold; c.fill = total_fill

    sec_dep_collected   = DEPOSITS["Security Deposits — refundable (must return to active tenants)"]
    maint_fee_collected = DEPOSITS["  Maintenance Fee retained (non-refundable, by check-in month)"]
    sec_dep_neg         = [-v for v in sec_dep_collected]
    ws.append(["  Less: Security Deposits held (active tenants — must return at exit)", "−"]
              + sec_dep_neg + [sum(sec_dep_neg)])
    ws[ws.max_row][0].font = Font(italic=True)

    ws.append(["     └ Maintenance Fee retained from same tenants (non-refundable — yours to keep)", "(kept)"]
              + list(maint_fee_collected) + [sum(maint_fee_collected)])
    ws[ws.max_row][0].font = Font(italic=True, color="375623")
    for c in ws[ws.max_row][1:]:
        if isinstance(c.value, (int, float)):
            c.font = Font(italic=True, color="375623")

    dep_refunded     = EXCLUDED["Tenant Deposit Refund (balance sheet)"]
    dep_refunded_neg = [-v for v in dep_refunded]
    ws.append(["  Less: Deposits Refunded to Exited Tenants (already paid back)", "−"]
              + dep_refunded_neg + [sum(dep_refunded_neg)])
    ws[ws.max_row][0].font = Font(italic=True)

    true_rev_row = [r + s + d for r, s, d in zip(rev_row, sec_dep_neg, dep_refunded_neg)]
    ws.append(["True Rent Revenue (excl. all deposit pass-throughs)", "="] + true_rev_row + [sum(true_rev_row)])
    for c in ws[ws.max_row]:
        c.font = Font(bold=True, color="375623")
    ws.append([])

    # ── 2. BORROWED MONEY / OWNER ADVANCES ────────────────────────────────────
    ws.append(["BORROWED MONEY — Owner loans & advances (to be repaid, not P&L)", ""])
    ws[ws.max_row][0].font = bold
    for label, row in CAPITAL_CONTRIBUTIONS.items():
        ws.append([label, "↑"] + row + [sum(row)])
    borrowed_row = [sum(col) for col in zip(*CAPITAL_CONTRIBUTIONS.values())]
    ws.append(["Total Borrowed Money (owners must be repaid this)", "="] + borrowed_row + [sum(borrowed_row)])
    for c in ws[ws.max_row]:
        c.font = Font(bold=True, color="9C0006")
        if isinstance(c.value, (int, float)):
            c.fill = PatternFill(start_color="FCE4D6", end_color="FCE4D6", fill_type="solid")
    ws.append([])

    # ── 3. OPERATING EXPENSES ──────────────────────────────────────────────────
    ws.append(["OPERATING EXPENSES (accrual)", ""])
    ws[ws.max_row][0].font = bold
    for label, row in opex_dict.items():
        ws.append([label, "−"] + row + [sum(row)])
        if "TBD" in label or "⚠" in label:
            for c in ws[ws.max_row]:
                c.fill = flag_fill

    ws.append(["EXCLUDED FROM OPEX (balance sheet items — not costs)", ""])
    ws[ws.max_row][0].font = Font(italic=True)
    for label, row in EXCLUDED.items():
        ws.append(["  " + label, "(B/S)"] + row + [sum(row)])

    opex_row = [sum(col) for col in zip(*opex_dict.values())]
    ws.append(["Total Opex", "="] + opex_row + [sum(opex_row)])
    for c in ws[ws.max_row]:
        c.font = bold; c.fill = total_fill
    ws.append([])

    # ── 4. EBITDA ──────────────────────────────────────────────────────────────
    op_profit_row = [r - o for r, o in zip(true_rev_row, opex_row)]
    ws.append(["NET OPERATING PROFIT (True Revenue − All Opex incl. Furniture & Supplies)", "="] + op_profit_row + [sum(op_profit_row)])
    for c in ws[ws.max_row]:
        c.font = bold

    op_margin_row = [f"{(p/r*100):.1f}%" if r else "-" for p, r in zip(op_profit_row, true_rev_row)]
    ws.append(["Operating Margin %", ""] + op_margin_row
              + [f"{(sum(op_profit_row)/sum(true_rev_row)*100):.1f}%" if sum(true_rev_row) else "-"])
    ws.append([])

    # ── 5. ADJUSTED PROFIT (after deducting borrowed money) ───────────────────
    borrowed_neg = [-v for v in borrowed_row]
    ws.append(["  Less: Borrowed Money to repay (owner loans — must be paid back)", "−"]
              + borrowed_neg + [sum(borrowed_neg)])
    ws[ws.max_row][0].font = Font(italic=True, color="9C0006")
    for c in ws[ws.max_row][2:]:
        if isinstance(c.value, (int, float)):
            c.font = Font(italic=True, color="9C0006")

    adjusted_row = [p - b for p, b in zip(op_profit_row, borrowed_row)]
    ws.append(["ADJUSTED NET PROFIT (after repaying all owner loans)", "="]
              + adjusted_row + [sum(adjusted_row)])
    for c in ws[ws.max_row]:
        c.font = Font(bold=True, color="375623" if sum(adjusted_row) >= 0 else "9C0006")
        if isinstance(c.value, (int, float)):
            c.fill = PatternFill(start_color="E2EFDA" if sum(adjusted_row) >= 0 else "FCE4D6",
                                 end_color="E2EFDA" if sum(adjusted_row) >= 0 else "FCE4D6",
                                 fill_type="solid")
    ws.append([])

    # ── 7. CASH POSITION ───────────────────────────────────────────────────────
    # Pure refundable security deposits owed to active tenants
    # Combined total ₹33,83,875 included maintenance ₹10,68,700 — maintenance is non-refundable
    # True refundable liability = ₹33,83,875 − ₹10,68,700 = ₹23,15,175
    _sec_collected = 2315175
    _bank_total    = BANK_CLOSING_BALANCE_THOR + BANK_CLOSING_BALANCE_HULK
    _cash_total    = sum(CASH_IN_HAND.values())

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

    # ── 8. FLAGS ───────────────────────────────────────────────────────────────
    ws.append(["⚠ ITEMS NEEDING KIRAN REVIEW", ""])
    ws[ws.max_row][0].font = Font(bold=True, color="FF0000")
    for f in [
        "1. Manoj water bill for April (paid in May — amount TBD). Add to Water line when known.",
        "2. Apr rent of Rs.20,49,100 paid in May is outside this P&L window — will appear in May P&L.",
        "3. Chandra advance (Mar Rs.32,789 + Apr Rs.38,111) — confirm these are Chandra's personal cash advances for PG ops, not company-paid cash already counted above.",
        "4. Cash Exchange Repayments (in EXCLUDED): Feb Rs.6L Sri Lakshmi Chandrasekar, Mar Rs.15.9L (YESMIDAS+Sravani+Sri Lakshmi; Bharathi Rs.5L excluded — covered by THOR→HULK intercompany transfer), Apr Rs.22K.",
    ]:
        ws.append([f, ""])

    # ── Formatting ─────────────────────────────────────────────────────────────
    for row in ws.iter_rows(min_row=2, max_col=len(header)):
        for i, cell in enumerate(row):
            if i == 0 or cell.value is None or isinstance(cell.value, str):
                continue
            if isinstance(cell.value, (int, float)):
                cell.number_format = INR_NUMBER_FORMAT

    for row in ws.iter_rows(min_row=1, min_col=2, max_col=2):
        for cell in row:
            cell.alignment = Alignment(horizontal="center")

    ws.column_dimensions["A"].width = 62
    ws.column_dimensions["B"].width = 6
    for col_letter in "CDEFGHIJ":
        ws.column_dimensions[col_letter].width = 14


def build_pnl_workbook() -> openpyxl.Workbook:
    """
    Return the canonical P&L workbook (Oct'25 – Apr'26).

    Tabs:
      1. P&L — Full (incl Cash)   — all items including cash income + cash rent
      2. Bank — Digital Only       — same layout; cash income + cash rent excluded
      3. Rules Applied             — methodology notes
    """
    wb = openpyxl.Workbook()

    # ── Tab 1: Full P&L (canonical — all items) ────────────────────────────────
    ws_full = wb.active
    assert ws_full is not None
    ws_full.title = "P&L — Full (incl Cash)"
    _write_pnl_tab(ws_full, INCOME, OPEX)

    # ── Tab 2: Bank / Digital-only P&L ────────────────────────────────────────
    # Removes: cash income from tenants + cash rent paid to owners
    # Useful for: loan applications, bank-verified reporting, digital economy view
    ws_bank = wb.create_sheet("Bank — Digital Only")
    income_bank = {k: v for k, v in INCOME.items() if _CASH_INCOME_KEY not in k}
    opex_bank   = {k: v for k, v in OPEX.items()   if _CASH_RENT_KEY   not in k}
    _write_pnl_tab(
        ws_bank,
        income_bank,
        opex_bank,
        tab_note="Bank / Digital Only — excl. cash income from tenants + cash rent paid to owners",
    )

    # ── Tab 3: Rules Applied ───────────────────────────────────────────────────
    ws_rules = wb.create_sheet("Rules Applied")
    rules = [
        ("Basis", "Accrual — expense in month of service, not payment"),
        ("Income source", "Bank statement credits (verified). Cash from DB payments table."),
        ("Property Rent", "Rs.13,000 × 164 beds = Rs.21,32,000/mo (Jan–Jun 2026). Rs.13,500 × 164 = Rs.22,14,000/mo from Jul 2026."),
        ("Water — Manoj B (9535665407)", "Cash basis. Apr = tanker Rs.42,020 + Mar bill Rs.42,500."),
        ("Internet & WiFi", "Cash-basis. Jan: Airwire Rs.70,730. Feb: 8x Razorpay Rs.1,13,168. Mar-Dec: Rs.0 (prepaid)."),
        ("Police", "Rs.3,000/mo cash accrual Jan onwards."),
        ("Waste Disposal", "Rs.3,500/mo (Pavan 6366411789)."),
        ("Prabhakaran (9444296681)", "All payments = Staff & Labour salary."),
        ("CAPEX", "Furniture & Fittings + CCTV/8-Ball Pool. Chairs/kitchen/atta machine moved to Operational Expenses."),
        ("Excluded from opex", "Tenant Deposit Refunds (liability) + Cash Exchange Repayments (non-operating)."),
        ("Bank-Only tab", "Removes 'Cash (physical)' from income and 'Property Rent — Cash paid' from OPEX. Net effect: cash in ~= cash out so EBITDA is similar; useful for bank-verified view."),
        ("Rent Jan-Jun", "Rs.21,32,000/mo fixed (Rs.13,000 × 164 beds). From Jul: Rs.22,14,000/mo (Rs.13,500 × 164)."),
        ("Variable ops benchmark", "Non-rent OPEX ~Rs.9L/mo at 270 beds (91% occ). Variable cost ~Rs.3,333/bed. Fixed staff/contracts ~Rs.2.7L."),
    ]
    ws_rules.append(["Rule", "Detail"])
    for c in ws_rules[1]:
        c.fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
        c.font = Font(bold=True, color="FFFFFF")
    for k, v in rules:
        ws_rules.append([k, v])
    ws_rules.column_dimensions["A"].width = 40
    ws_rules.column_dimensions["B"].width = 120
    for row in ws_rules.iter_rows():
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")

    return wb


def build_pnl_bytes() -> bytes:
    """Return the P&L workbook as bytes (for streaming from FastAPI)."""
    buf = io.BytesIO()
    build_pnl_workbook().save(buf)
    buf.seek(0)
    return buf.read()
