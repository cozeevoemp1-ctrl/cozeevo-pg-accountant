"""
src/reports/pnl_builder.py
---------------------------
Canonical P&L builder — single source of truth shared by:
  - scripts/export_pnl_2026_05_02.py  (local regeneration)
  - src/api/v2/finance.py  GET /finance/pnl/excel  (PWA download)

Both produce identical output. Verified figures as of 2026-05-17.
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
MONTHS = ["Oct'25", "Nov'25", "Dec'25", "Jan'26", "Feb'26", "Mar'26", "Apr'26", "May'26"]

INCOME = {
    # THOR building (acct ...0961) — UPI batch + direct NEFT merged
    # UPI batch: [0, 0, 0, 175596, 2091597, 2515275, 2834731]
    # Direct NEFT: [0, 723007, 1350547, 1083628, 420690, 385691, 226807]  # Mar: +160600 Chandra cash reclassified to bank (2026-05-12)
    "THOR — Bank Income (UPI + NEFT)":                     [0, 723007, 1350547, 1259224, 2512287, 2900966, 3061538, 1121748],
    "THOR — transferred to HULK acct (reclassification)": [0,      0,        0,       0,       0,       0, -500000, 0],
    "Cash (physical — both buildings combined)":           [0,      0,        0,  300572,  653300, 1094220, 1336283, 2484085],  # Bala uncle REMOVED from Jan (−25K), Feb (−3K), Apr (−23K net) — all moved to May. Mar: Chandra ₹1.60L moved to UPI (2026-05-12). Apr −19,500: dues reconciliation 2026-05-16 (Tanishka/Veena.T/Sachin/Preesha shared-room fix)
    # HULK building (acct ...0881) — live from Mar 2026; UPI + cheque merged
    # UPI batch: [0, 0, 0, 0, 0, 0, 247719]
    # Cheque/other: [0, 0, 0, 0, 0, 71550, 0]
    "HULK — Bank Income (UPI + cheque)":                   [0,      0,        0,       0,       0,   71550,  247719, 1418816],
    "HULK — received from THOR acct (reclassification)":   [0,      0,        0,       0,       0,       0,  500000, 0],
}

CAPITAL_CONTRIBUTIONS = {
    "Owner startup — Lakshmi SBI to Yes Bank (Oct 2025)": [500000,      0, 0,     0,     0,   0,    0, 0],
    "Owner startup — repaid via NEFT Nov (₹50K + ₹4.5L to Bharathi)": [0, -500000, 0, 0, 0, 0, 0, 0],
    "Kiran top-up transfer (Jan 2026)":                   [     0,      0, 0, 90000,     0,   0,    0, 0],
    # Partner personal advances (reimbursable — company owes Lakshmi this back)
    # Dec: ₹74,768 BESCOM via partner UPI 7358341775-2@ybl (moved to Electricity expense)
    # Jan–Apr: personal SBI 0167 payments matching OPEX Partner Reimbursable line
    "Partner advance — Lakshmi (personal UPI + SBI 0167, reimbursable)": [0, 0, 74768, 41899, 18264, 750, 6928, 0],
    # Chandra personal cash for PG operations — confirmed from handwritten notebook (2026-05-17)
    # Feb: Pradeep police ₹3,000
    # Mar: Police ₹3,000 + Diesel ₹6,370 + Cans ₹1,820 + Carpenter ₹1,000 + Generator ₹500 = ₹12,690
    # Apr: Dilip plumber ₹1,000 + Dilip brother ₹500 + Electrician Krishna ₹500+200+200 + Egg trays ₹875 = ₹3,275
    "Chandra advance — confirmed cash (police/diesel/plumber/carpenter/electrician)": [0, 0, 0, 0, 3000, 12690, 3275, 0],
    # Jitendra personal cash for PG ops (Jan 3 2026) — confirmed from handwritten notebook (2026-05-17)
    # BBMP ₹5,000 + Agreement ₹600 = ₹5,600 (personal funds; police ₹3K was from PG collections — excluded)
    # Matching OPEX: Govt & Regulatory Jan already includes BBMP+Agreement (₹99,673 total)
    "Jitendra advance — personal cash (BBMP Rs.5K + agreement Rs.600, Jan 3 2026)": [0, 0, 0, 5600, 0, 0, 0, 0],
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
    "Kiran advance — PhonePe/cash for PG ops": [0, 39001, 51517, 32045, 654, 0, 0, 0],
}

OPEX = {
    "Property Rent — Cash paid (Jan rent in Feb, Feb in Mar, Mar in Apr)": [0, 0, 0, 0, 1532000, 1290000, 1449100, 1532000],  # Feb+Apr Kiran confirmed; Mar corrected to 12,90,000 (Kiran 2026-05-12)
    "Property Rent — Bank UPI/RTGS paid":                                  [0, 0, 0, 0,  600000,  605140,  600000, 600000],  # Feb+Apr+Mar confirmed by Kiran (2026-05-12)
    "Electricity":                                                [0, 0, 74768,   131554,  134538,   96617,  140659, 196371],  # Dec: BESCOM via BBPSBP@ybl
    "Water (bank tankers + Manoj cash; Mar bill paid Apr)":       [0, 0, 0,            0,       0,    8000,   84520, 62900],
    "IT & Software":                                              [0, 0, 3480,     12068,     934,    1128,    2348, 876],  # Jan +948 office phone; Feb +934 mobile recharge; Mar +1128 paybil/payair; Apr +2348. Updated 2026-05-13
    "Internet & WiFi (cash — Jan Airwire UPI, Feb 8x Razorpay, Mar-Dec Rs.0)": [0, 0, 43946, 70730, 113168, 0, 0, 0],  # Dec +3000 wifi dongles (Kiran cash)
    "Food & Groceries":                                           [0, 33632, 113787, 217504,  115595,  240294,  239753, 278418],  # Apr +875 Chandra cash (egg trays). Jan +1086 Origin veg; Feb +792 Amazon food; Apr +756 Ratnadeep. 2026-05-17
    "Fuel & Diesel":                                              [0, 0, 1200,      9599,  105866,  364161,   61904, 134118],  # Mar +8190 Chandra cash (diesel 6370+cans 1820). Jan +500 Shell India; Apr +326 volipi.l. 2026-05-17
    "Staff & Labour":                                             [0, 1000, 135435, 116714, 171295,  217341,  193617, 76258],  # Feb -63000 (9342205440 gas pipeline welding reclassified to Maintenance; confirmed Kiran 2026-05-30). Jan +790 petty wages; Feb +580 petty wages; Mar +29000 volipi.l salary. Updated 2026-05-30
    "Maintenance & Repairs":                                      [0, 0, 1400,     22450,   64850,   23399,   39319, 18600],  # Feb +63000 (9342205440 gas pipeline welding; was Staff & Labour; confirmed Kiran 2026-05-30). Mar +1500 Chandra (carpenter 1000+generator 500); Apr +2400 Chandra (plumbers 1500+elec 900). Updated 2026-05-30
    "Cleaning Supplies":                                          [0, 0, 5674,       1880,    1200,   11272,   18315, 564],  # Jan +480 Hinglaj packaging; Apr +340 kastig soda. Updated 2026-05-13
    "Waste Disposal (Pavan Rs.3.5K/mo)":                         [0, 0, 0,          3000,    3500,    3500,    3500, 3500],
    # Shopping & Supplies — small operational purchases (akhil setup, misc UPI, nursery decor, CHANDRASEKHAR ops advance etc.)
    # Updated 2026-05-13: reclassified all items from Operational Expenses; Nov nursery; Dec: Chandra 70K+akhil 28.7K+cash 1.7K; Jan: akhil+Q531; Feb: SV251+paytm+ME+Global+paytmqr; Mar: 9902+volipi.l 444+balaji; Apr: volipi.l mirrors
    "Shopping & Supplies":                                        [0, 3048, 136960,  18323,   7662,    7770,   10258, 11817],
    # Furniture & Supplies — ALL furniture, equipment, Amazon purchases from PG bank (2026-05-13: CAPEX folded into OPEX per Kiran)
    # Old CAPEX (F&F + Capital Inv) + chairs ₹47K + atta machine ₹21K + kitchen vessels ₹37.5K + Amazon all months
    # Nov: F&F 125021 + CCTV/8-Ball 82000. Dec: F&F 167741 + CCTV 100000 + Amazon 19014. Jan: F&F 203815 + Amazon 8414 (4707+3707 cash-counter). Feb: F&F 1185597 + Amazon 2174. Mar: F&F 10761 + Amazon 3237. Apr: F&F 12363 + chairs 47000 + atta 21060 + kitchen 37500 + Amazon 30756
    "Furniture & Supplies":                                       [0, 207021, 286755, 212229, 1187771,  53998,  148679, 35860],  # Mar +40000: fire stove (shalu UPI Mar 15, id 1655 — was in EXCLUDED/Non-Op, reclassified to ops 2026-05-17)
    "Marketing":                                                  [0, 0, 81273,     35595,   7620,   27700,    1003, 0],  # Apr +1003 Naukri job posting. Updated 2026-05-13
    "Govt & Regulatory (incl Police Rs.3K accrual Jan+)":        [0, 0,  6948,     99673,   6000,    6000,    3000, 6500],  # Feb +3000 Chandra (Pradeep police); Mar +3000 Chandra (police). Jan Jitendra BBMP+Agreement. 2026-05-17
    "Bank Charges":                                               [0, 0, 0,           149,      0,       0,     100, 0],
    "Other Expenses":                                             [0, 15987, 2781,     700,       0,       0,       0, 34687],  # Chandra cash now in proper categories (Fuel/Govt/Maintenance/Food). Mar+Apr = 0.
    # HULK building operational expenses (bank withdrawals — Apr ₹4,328)
    "HULK — Operational Expenses":                               [0,     0,     0,     0,      0,       0,    4328, 0],
    # Partner personal SBI (0167) payments for PG business — reimbursable from company account
    # Detail: data/reports/SBI_0167_Reimbursement.xlsx
    "Partner Reimbursable (Personal Acct SBI 0167)":            [0,     0,     0, 41899,  18264,     750,    6928, 0],
}
# NOTE: CAPEX removed 2026-05-13 per Kiran — all furniture/equipment spent from PG bank account
# folded into OPEX as "Furniture & Supplies". No separate CAPEX section.

EXCLUDED = {
    # Tenant deposit refunds are balance-sheet items only (return of liability) — not operating costs
    "Tenant Deposit Refund (balance sheet)":  [0,  15000,  47344,  55944,  74532,  182441, 151163, 275800],  # Updated 2026-05-12
    # Cash-exchange repayments: someone gave physical cash → used for ops (already in OPEX) → repaid via bank RTGS
    # Feb: Sri Lakshmi Chandrasekar ₹6L (id 1885)
    # Mar: Sravani ₹7.5L (id 1714) + Sri Lakshmi ₹6L (id 1623) + Bharathi ₹2L (id 1652) = ₹15.5L
    #      ₹40K shalu.pravi2125@okicici MOVED to Furniture&Supplies (fire stove purchase, Mar 15, id 1655)
    # Apr: Prabhakaran borrow/return ₹20K (ids 1191+1175) + Amazon Pay Later ₹2,357 (ids 1179+1053+1006) = ₹22,357
    # Nov ₹5L REMOVED — startup capital repayment (Capital Contributions above), not a cash exchange.
    # Mar ₹5L Bharathi REMOVED — covered by THOR→HULK intercompany transfer, not a separate P&L item.
    # NOT an operating cost — the cash was already spent and counted in OPEX categories above.
    "Cash Exchange Repayments via Bank (non-op)": [0,      0,     0,      0,  600000, 1550000,  22357, 0],
}

# ── Deposit flows — queried from tenancies (security_deposit + maintenance_fee by check-in month)
# These are LIABILITY inflows — real cash but NOT revenue. Subtracted from gross income for True Revenue.
DEPOSIT_RECEIVED = [0, 448000, 838000, 1383000, 1074250, 1256450, 1161125, 616250]
# Deposit refunds = same figures as EXCLUDED["Tenant Deposit Refund"] — shown here for net calc
DEPOSIT_REFUNDED = [0, 10000,  21500,   55944,   74532,  160231,  139638, 184200]  # Mar +22000, Apr +9970 (personal SBI)

# Security deposits = active tenants only (what we owe back), split by check-in month
# Maintenance fees  = all non-no-show tenants (non-refundable, retained), by check-in month
# Source: DB query 2026-05-06
DEPOSITS = {
    # Pure refundable security only (combined total was ₹33,83,875 but included maintenance ₹10,68,700)
    # True refundable = combined − maintenance = ₹33,83,875 − ₹10,68,700 = ₹23,15,175
    "Security Deposits — refundable (must return to active tenants)": [0, 140000, 266500, 455500, 353000, 526550, 573625, 744534],
    "  Maintenance Fee retained (non-refundable, by check-in month)": [0,  53000, 120000, 178000, 145000, 285700, 287000, 0],
}

# Monthly bank balances — from Yes Bank statements (verified)
# THOR acct ...0961: Oct'25 statement + 2026 statement.csv
# HULK acct ...0881: AccountSummary Cozeevo hulk_formatted.xlsx (live from Mar 4 2026)
# Note: Dec'25 statement runs to Dec 30 only — Jan'26 opening reflects Dec 31 transactions (+₹61,515 gap)
# Tuple: (opening_balance, closing_balance) per month. None = account not yet open.
BANK_BALANCE_THOR: Dict[str, tuple] = {
    "Oct'25": (      0,   500000),
    "Nov'25": ( 500000,   616192),
    "Dec'25": ( 616192,  1437933),  # Dec 30 stmt showed 1376418; Dec 31 txns brought it to 1437933 (= Jan 1 opening)
    "Jan'26": (1437933,  1878517),
    "Feb'26": (1878517,  1250402),
    "Mar'26": (1250402,   205008),
    "Apr'26": ( 205008,  1373863),
    "May'26": (1321663,   914858),  # THOR May statement: open 1,321,662.65 → close 914,857.74
}

BANK_BALANCE_HULK: Dict[str, tuple] = {
    "Oct'25": (None, None),
    "Nov'25": (None, None),
    "Dec'25": (None, None),
    "Jan'26": (None, None),
    "Feb'26": (None, None),
    "Mar'26": (  10000,  571550),
    "Apr'26": ( 571550,  814941),  # verified Apr 30 figure
    "May'26": ( 814941, 2026041),  # HULK May statement: open 814,941 → close 2,026,040.66
}

BANK_CLOSING_BALANCE_THOR = BANK_BALANCE_THOR["Apr'26"][1]
BANK_CLOSING_BALANCE_HULK = BANK_BALANCE_HULK["Apr'26"][1]

CASH_IN_HAND = {
    "Lakshmi cash (Mar closing ₹2,42,617 → Apr closing)":  820883,  # Apr 30 confirmed 2026-05-13
    "Prabhakaran cash holding":                              524400,  # Apr 30 confirmed 2026-05-13
}

# ── Cash items to exclude for the Bank-Only tab ───────────────────────────────
# Income key containing this fragment is skipped
_CASH_INCOME_KEY  = "Cash (physical"
# OPEX key containing this fragment is skipped
_CASH_RENT_KEY    = "Property Rent — Cash paid"


# ── Dynamic-month translation (DB → SOP-format line keys) ─────────────────────
# When new months are appended from the DB, their values attach to these exact
# verified line keys so they land in the same rows as the hardcoded history.
_KEY_INCOME_THOR = "THOR — Bank Income (UPI + NEFT)"
_KEY_INCOME_HULK = "HULK — Bank Income (UPI + cheque)"
_KEY_INCOME_CASH = "Cash (physical — both buildings combined)"
_KEY_RENT_CASH   = "Property Rent — Cash paid (Jan rent in Feb, Feb in Mar, Mar in Apr)"
_KEY_CASH_EXP    = "Cash Expenses (paid in cash — manual entry)"
_KEY_EXCL_REFUND = "Tenant Deposit Refund (balance sheet)"
_KEY_EXCL_NONOP  = "Cash Exchange Repayments via Bank (non-op)"
_KEY_DEP_SEC     = "Security Deposits — refundable (must return to active tenants)"
_KEY_DEP_MAINT   = "  Maintenance Fee retained (non-refundable, by check-in month)"

# bank_transactions.category → verified OPEX line key
_DB_CAT_TO_OPEX_KEY = {
    "Property Rent":         "Property Rent — Bank UPI/RTGS paid",
    "Electricity":           "Electricity",
    "Water":                 "Water (bank tankers + Manoj cash; Mar bill paid Apr)",
    "IT & Software":         "IT & Software",
    "Internet & WiFi":       "Internet & WiFi (cash — Jan Airwire UPI, Feb 8x Razorpay, Mar-Dec Rs.0)",
    "Food & Groceries":      "Food & Groceries",
    "Fuel & Diesel":         "Fuel & Diesel",
    "Staff & Labour":        "Staff & Labour",
    "Maintenance & Repairs": "Maintenance & Repairs",
    "Cleaning Supplies":     "Cleaning Supplies",
    "Waste Disposal":        "Waste Disposal (Pavan Rs.3.5K/mo)",
    "Shopping & Supplies":   "Shopping & Supplies",
    "Furniture & Fittings":  "Furniture & Supplies",
    "Capital Investment":    "Furniture & Supplies",
    "Marketing":             "Marketing",
    "Govt & Regulatory":     "Govt & Regulatory (incl Police Rs.3K accrual Jan+)",
    "Bank Charges":          "Bank Charges",
    "Other Expenses":        "Other Expenses",
}


def _dynamic_line_values(d: dict):
    """Translate one DB-month record into (income, opex, excluded) contributions
    keyed by the verified SOP line names."""
    income = {
        _KEY_INCOME_THOR: d.get("income_thor", 0),
        _KEY_INCOME_HULK: d.get("income_hulk", 0),
        _KEY_INCOME_CASH: d.get("cash", 0),
    }
    opex: Dict[str, float] = {}
    for cat, amt in (d.get("opex_by_cat") or {}).items():
        key = _DB_CAT_TO_OPEX_KEY.get(cat, "Other Expenses")
        opex[key] = opex.get(key, 0) + amt
    if d.get("rent_paid_cash"):
        opex[_KEY_RENT_CASH] = opex.get(_KEY_RENT_CASH, 0) + d["rent_paid_cash"]
    if d.get("cash_expense"):
        opex[_KEY_CASH_EXP] = opex.get(_KEY_CASH_EXP, 0) + d["cash_expense"]
    excluded = {
        _KEY_EXCL_REFUND: d.get("dep_refunded", 0),
        _KEY_EXCL_NONOP:  d.get("non_op", 0),
    }
    return income, opex, excluded


def _extend_dict(base: Dict[str, List[int]], per_month: List[dict]) -> Dict[str, List[int]]:
    """Append one column per dynamic month to every verified line; add any
    dynamic-only keys as new rows (verified months = 0)."""
    n_verified = len(MONTHS)
    out: Dict[str, List[int]] = {k: list(v) + [pm.get(k, 0) for pm in per_month] for k, v in base.items()}
    extra: List[str] = []
    for pm in per_month:
        for k in pm:
            if k not in base and k not in extra:
                extra.append(k)
    for k in extra:
        out[k] = [0] * n_verified + [pm.get(k, 0) for pm in per_month]
    return out


# ── Shared P&L sheet writer ───────────────────────────────────────────────────

def _write_pnl_tab(
    ws: Worksheet,
    income_dict: Dict[str, List[int]],
    opex_dict: Dict[str, List[int]],
    tab_note: str = "",
    *,
    months: List[str] | None = None,
    deposits: Dict[str, List[int]] | None = None,
    excluded: Dict[str, List[int]] | None = None,
    capital: Dict[str, List[int]] | None = None,
    bank_thor_close: int | None = None,
    bank_hulk_close: int | None = None,
    cash_in_hand: Dict[str, int] | None = None,
    sec_owed: int = 2315175,
    snapshot_label: str = "Apr 30",
) -> None:
    """
    Render a complete P&L into *ws*.

    income_dict / opex_dict are the (possibly filtered) subsets of INCOME / OPEX.
    tab_note is shown in the top-left header cell when provided.

    All month-varying inputs default to the verified module globals, so calling
    with no keyword args reproduces the canonical Oct'25–May'26 report byte-for-byte.
    Pass extended dicts + a longer `months` list to append dynamic (DB) months.
    """
    months          = months          if months          is not None else MONTHS
    deposits        = deposits         if deposits        is not None else DEPOSITS
    excluded        = excluded         if excluded        is not None else EXCLUDED
    capital         = capital          if capital         is not None else CAPITAL_CONTRIBUTIONS
    bank_thor_close = bank_thor_close  if bank_thor_close is not None else BANK_CLOSING_BALANCE_THOR
    bank_hulk_close = bank_hulk_close  if bank_hulk_close is not None else BANK_CLOSING_BALANCE_HULK
    cash_in_hand    = cash_in_hand     if cash_in_hand    is not None else CASH_IN_HAND
    bold       = Font(bold=True)
    hdr_fill   = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
    hdr_font   = Font(bold=True, color="FFFFFF")
    total_fill = PatternFill(start_color="E7E6E6", end_color="E7E6E6", fill_type="solid")
    flag_fill  = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")
    ctr        = Alignment(horizontal="center")

    header = [tab_note or "", "Op"] + months + ["TOTAL"]
    ws.append(header)
    for c in ws[1]:
        c.fill = hdr_fill; c.font = hdr_font; c.alignment = ctr

    # ── 1. INCOME ──────────────────────────────────────────────────────────────
    acct_fill  = PatternFill(start_color="DEEAF1", end_color="DEEAF1", fill_type="solid")
    close_fill = PatternFill(start_color="BDD7EE", end_color="BDD7EE", fill_type="solid")
    acct_font  = Font(bold=True, color="1F4E78")

    def _acct_row(label, values, fill):
        ws.append([label, ""] + values + [None])
        for c in ws[ws.max_row]:
            c.fill = fill
            c.font = acct_font

    def _get(key):
        return income_dict.get(key, [0] * len(months))

    ws.append(["INCOME", ""])
    ws[ws.max_row][0].font = bold

    # ── THOR group (bank balances live only on the reconciliation tab) ────────
    row = _get("THOR — Bank Income (UPI + NEFT)")
    if row:
        ws.append(["THOR — Bank Income (UPI + NEFT)", "+"] + row + [sum(row)])
    row = _get("THOR — transferred to HULK acct (reclassification)")
    if any(row):
        ws.append(["  THOR — transferred to HULK acct (reclassification)", "−"] + row + [sum(row)])

    ws.append([])

    # ── Cash ──────────────────────────────────────────────────────────────────
    cash_key = "Cash (physical — both buildings combined)"
    if cash_key in income_dict:
        row = income_dict[cash_key]
        ws.append([cash_key, "+"] + row + [sum(row)])

    ws.append([])

    # ── HULK group ────────────────────────────────────────────────────────────
    row = _get("HULK — Bank Income (UPI + cheque)")
    if row:
        ws.append(["HULK — Bank Income (UPI + cheque)", "+"] + row + [sum(row)])
    row = _get("HULK — received from THOR acct (reclassification)")
    if any(row):
        ws.append(["HULK — received from THOR acct (reclassification)", "+"] + row + [sum(row)])

    ws.append([])

    rev_row = [sum(col) for col in zip(*income_dict.values())]
    ws.append(["Total Gross Inflows", "="] + rev_row + [sum(rev_row)])
    for c in ws[ws.max_row]:
        c.font = bold; c.fill = total_fill

    sec_dep_collected   = deposits["Security Deposits — refundable (must return to active tenants)"]
    maint_fee_collected = deposits["  Maintenance Fee retained (non-refundable, by check-in month)"]
    sec_dep_neg         = [-v for v in sec_dep_collected]
    # Each monthly column = deposits COLLECTED that month (a flow, not a stock).
    # TOTAL col = SUM of the monthly flows = total deposits collected/held over the period.
    dep_refunded     = excluded["Tenant Deposit Refund (balance sheet)"]
    dep_refunded_neg = [-v for v in dep_refunded]
    closing_sec_dep  = sum(sec_dep_neg)        # total refundable deposits collected
    closing_maint    = sum(maint_fee_collected)

    ws.append(["  Less: Security Deposits held (active tenants — must return at exit)", "−"]
              + sec_dep_neg + [closing_sec_dep])
    ws[ws.max_row][0].font = Font(italic=True)

    ws.append(["     └ Maintenance Fee retained from same tenants (non-refundable — yours to keep)", "(kept)"]
              + list(maint_fee_collected) + [closing_maint])
    ws[ws.max_row][0].font = Font(italic=True, color="375623")
    for c in ws[ws.max_row][1:]:
        if isinstance(c.value, (int, float)):
            c.font = Font(italic=True, color="375623")

    ws.append(["  Less: Deposits Refunded to Exited Tenants (already paid back)", "−"]
              + dep_refunded_neg + [sum(dep_refunded_neg)])
    ws[ws.max_row][0].font = Font(italic=True)

    true_rev_row = [r + s + d for r, s, d in zip(rev_row, sec_dep_neg, dep_refunded_neg)]
    # TOTAL col = sum of the monthly True Revenue figures
    true_rev_total = sum(true_rev_row)
    ws.append(["True Rent Revenue (excl. all deposit pass-throughs)", "="] + true_rev_row + [true_rev_total])
    for c in ws[ws.max_row]:
        c.font = Font(bold=True, color="375623")
    ws.append([])

    # ── 2. BORROWED MONEY / OWNER ADVANCES ────────────────────────────────────
    ws.append(["BORROWED MONEY — Owner loans & advances (to be repaid, not P&L)", ""])
    ws[ws.max_row][0].font = bold
    for label, row in capital.items():
        ws.append([label, "↑"] + row + [sum(row)])
    borrowed_row = [sum(col) for col in zip(*capital.values())]
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
    for label, row in excluded.items():
        ws.append(["  " + label, "(B/S)"] + row + [sum(row)])

    opex_row = [sum(col) for col in zip(*opex_dict.values())]
    ws.append(["Total Opex", "="] + opex_row + [sum(opex_row)])
    for c in ws[ws.max_row]:
        c.font = bold; c.fill = total_fill
    ws.append([])

    # ── 4. EBITDA ──────────────────────────────────────────────────────────────
    op_profit_row = [r - o for r, o in zip(true_rev_row, opex_row)]
    op_profit_total = true_rev_total - sum(opex_row)
    ws.append(["NET OPERATING PROFIT (True Revenue − All Opex incl. Furniture & Supplies)", "="] + op_profit_row + [op_profit_total])
    for c in ws[ws.max_row]:
        c.font = bold

    op_margin_row = [f"{(p/r*100):.1f}%" if r else "-" for p, r in zip(op_profit_row, true_rev_row)]
    ws.append(["Operating Margin %", ""] + op_margin_row
              + [f"{(op_profit_total/true_rev_total*100):.1f}%" if true_rev_total else "-"])
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
    adjusted_total = op_profit_total - sum(borrowed_row)
    ws.append(["ADJUSTED NET PROFIT (after repaying all owner loans)", "="]
              + adjusted_row + [adjusted_total])
    for c in ws[ws.max_row]:
        c.font = Font(bold=True, color="375623" if adjusted_total >= 0 else "9C0006")
        if isinstance(c.value, (int, float)):
            c.fill = PatternFill(start_color="E2EFDA" if adjusted_total >= 0 else "FCE4D6",
                                 end_color="E2EFDA" if adjusted_total >= 0 else "FCE4D6",
                                 fill_type="solid")
    ws.append([])

    # ── 7. BALANCE SHEET ITEMS ────────────────────────────────────────────────
    # Pure refundable security deposits owed to active tenants
    # Combined total ₹33,83,875 included maintenance ₹10,68,700 — maintenance is non-refundable
    # True refundable liability = ₹33,83,875 − ₹10,68,700 = ₹23,15,175
    _sec_collected = sec_owed
    _bank_total    = bank_thor_close + bank_hulk_close
    _cash_total    = sum(cash_in_hand.values())

    # value lands one column before TOTAL (matches verified layout for 8 months)
    def _bs_row(label, value):
        ws.append([label] + [""] * (len(months) - 1) + [value])

    ws.append([f"BALANCE SHEET ITEMS ({snapshot_label})", ""])
    ws[ws.max_row][0].font = bold
    _bs_row(f"Bank closing balance THOR acct ...0961 ({snapshot_label})", bank_thor_close)
    _bs_row(f"Bank closing balance HULK acct ...0881 ({snapshot_label})", bank_hulk_close)
    _bs_row("Total bank balance", _bank_total)
    for c in ws[ws.max_row]:
        c.font = bold
    ws.append([])
    ws.append(["Cash in hand (physical)", ""])
    ws[ws.max_row][0].font = bold
    for name, amt in cash_in_hand.items():
        _bs_row("  " + name, amt)
    _bs_row("Total cash in hand", _cash_total)
    for c in ws[ws.max_row]:
        c.font = bold
    ws.append([])
    _bs_row("Net deposits still owed to active tenants (liability)", _sec_collected)
    for c in ws[ws.max_row]:
        c.font = Font(bold=True, color="9C0006")
    ws.append([])
    _bs_row("True free cash (bank − deposits owed) — excl. cash in hand", _bank_total - _sec_collected)
    for c in ws[ws.max_row]:
        c.font = Font(bold=True)
    _bs_row("True free cash incl. cash in hand", _bank_total + _cash_total - _sec_collected)
    for c in ws[ws.max_row]:
        c.font = Font(bold=True)
    ws.append(["NOTE: negative = deposit money was used to fund early operations (CAPEX+OPEX)"])
    ws.append(["As revenue grows, bank balance will recover and exceed deposit liability"])
    ws.append([])

    # ── 8. FLAGS ───────────────────────────────────────────────────────────────
    ws.append(["⚠ ITEMS NEEDING KIRAN REVIEW", ""])
    ws[ws.max_row][0].font = Font(bold=True, color="FF0000")
    for f in [
        "1. Manoj water bill for April (paid in May — amount TBD). Add to Water line when known.",
        "2. Apr rent of Rs.20,49,100 paid in May is outside this P&L window — will appear in May P&L.",
        "3. Chandra advance Rs.18,965 confirmed from handwritten notebook (2026-05-17): Feb police Rs.3K, Mar diesel Rs.6,370+cans Rs.1,820+carpenter Rs.1K+generator Rs.500+police Rs.3K=Rs.12,690, Apr plumber Rs.1,500+elec Rs.900+egg trays Rs.875=Rs.3,275. Added to OPEX categories (Fuel/Govt/Maintenance/Food) and Capital Contributions.",
        "4. Cash Exchange Repayments (in EXCLUDED): Feb Rs.6L Sri Lakshmi, Mar Rs.15.5L (Sravani 7.5L+Sri Lakshmi 6L+Bharathi 2L), Apr Rs.22K (Prabhakaran+Amazon Pay Later). Rs.40K shalu (id 1655) confirmed fire stove purchase — moved to Furniture & Supplies Mar.",
        "5. bank_transactions id 1655 (shalu Rs.40K) category still shows Non-Operating in DB — update to Furniture & Fittings for live P&L endpoint to match this report.",
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
    from openpyxl.utils import get_column_letter as _gcl
    for _ci in range(3, 3 + len(months) + 1):  # month cols + TOTAL
        ws.column_dimensions[_gcl(_ci)].width = 14


def build_pnl_workbook(dynamic_data: List[dict] | None = None) -> openpyxl.Workbook:
    """
    Return the P&L workbook.

    With no argument → the canonical verified report (Oct'25 – May'26), byte-identical
    to before. With `dynamic_data` (a list of per-month DB records, oldest→newest) →
    those months are appended as extra columns in the same SOP format, on top of the
    verified history. Tabs 1 & 2 grow; the THOR reconciliation + rules tabs stay verified.

    Tabs:
      1. P&L — Full (incl Cash)   — all items including cash income + cash rent
      2. Bank — Digital Only       — same layout; cash income + cash rent excluded
      3. THOR Bank Reconciliation
      4. Rules Applied             — methodology notes
    """
    wb = openpyxl.Workbook()

    # Build the (possibly extended) line dicts + snapshot kwargs for tabs 1 & 2.
    if dynamic_data:
        # sanity: every translation key must still exist in the verified dicts
        for k in (_KEY_INCOME_THOR, _KEY_INCOME_HULK, _KEY_INCOME_CASH):
            assert k in INCOME, f"income key drift: {k!r}"
        assert _KEY_RENT_CASH in OPEX, "opex key drift (rent cash)"
        for k in (_KEY_EXCL_REFUND, _KEY_EXCL_NONOP):
            assert k in EXCLUDED, f"excluded key drift: {k!r}"
        for k in (_KEY_DEP_SEC, _KEY_DEP_MAINT):
            assert k in DEPOSITS, f"deposits key drift: {k!r}"

        inc_pm, opex_pm, excl_pm = [], [], []
        for d in dynamic_data:
            i, o, e = _dynamic_line_values(d)
            inc_pm.append(i); opex_pm.append(o); excl_pm.append(e)

        months   = MONTHS + [d["label"] for d in dynamic_data]
        income   = _extend_dict(INCOME, inc_pm)
        opex     = _extend_dict(OPEX,   opex_pm)
        excluded = _extend_dict(EXCLUDED, excl_pm)
        capital  = {k: list(v) + [0] * len(dynamic_data) for k, v in CAPITAL_CONTRIBUTIONS.items()}
        deposits = {
            _KEY_DEP_SEC:   list(DEPOSITS[_KEY_DEP_SEC])   + [d.get("sec_dep", 0) for d in dynamic_data],
            _KEY_DEP_MAINT: list(DEPOSITS[_KEY_DEP_MAINT]) + [d.get("maint", 0)   for d in dynamic_data],
        }
        last = dynamic_data[-1]
        dyn_kwargs = dict(
            months=months, deposits=deposits, excluded=excluded, capital=capital,
            bank_thor_close=last.get("bank_thor_close", 0),
            bank_hulk_close=last.get("bank_hulk_close", 0),
            cash_in_hand={"Cash in hand (physical count)": last.get("cash_holding", 0)},
            sec_owed=last.get("sec_owed_total", 0),
            snapshot_label=last["label"],
        )
    else:
        income, opex = INCOME, OPEX
        dyn_kwargs = {}

    # ── Tab 1: Full P&L (canonical — all items) ────────────────────────────────
    ws_full = wb.active
    assert ws_full is not None
    ws_full.title = "P&L — Full (incl Cash)"
    _write_pnl_tab(ws_full, income, opex, **dyn_kwargs)

    # ── Tab 2: Bank / Digital-only P&L ────────────────────────────────────────
    # Removes: cash income from tenants + cash rent paid to owners
    # Useful for: loan applications, bank-verified reporting, digital economy view
    ws_bank = wb.create_sheet("Bank — Digital Only")
    income_bank = {k: v for k, v in income.items() if _CASH_INCOME_KEY not in k}
    opex_bank   = {k: v for k, v in opex.items()
                   if _CASH_RENT_KEY not in k and "paid in cash" not in k}
    _write_pnl_tab(
        ws_bank,
        income_bank,
        opex_bank,
        tab_note="Bank / Digital Only — excl. cash income from tenants + cash rent paid to owners",
        **dyn_kwargs,
    )

    # ── Tab 3: THOR Bank Reconciliation ───────────────────────────────────────
    # Shows actual bank cash flow — Opening + bank credits - bank debits = Closing
    # Implied outflows = everything that left THOR bank acct (OPEX + refunds + repayments + withdrawals)
    ws_recon = wb.create_sheet("THOR Bank Reconciliation")

    # Capital flows that actually hit the THOR bank account (not cash/personal advances)
    _thor_cap_in  = [500000, 0,      0, 90000, 0, 0,      0, 0]  # Oct: startup ₹5L; Jan: Kiran top-up ₹90K
    _thor_cap_out = [0,      500000, 0, 0,     0, 0, 500000, 0]  # Nov: startup repaid ₹5L; Apr: transferred to HULK ₹5L

    _thor_income  = INCOME["THOR — Bank Income (UPI + NEFT)"]
    _thor_open    = [BANK_BALANCE_THOR[m][0] for m in MONTHS]
    _thor_close   = [BANK_BALANCE_THOR[m][1] for m in MONTHS]

    # Balancing figure — all debits from THOR bank (OPEX from bank + deposit refunds + repayments + withdrawals)
    _thor_out = [
        _thor_open[i] + _thor_income[i] + _thor_cap_in[i] - _thor_cap_out[i] - _thor_close[i]
        for i in range(len(MONTHS))
    ]

    R_HDR  = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
    R_OPEN = PatternFill(start_color="DEEAF1", end_color="DEEAF1", fill_type="solid")
    R_INC  = PatternFill(start_color="E2EFDA", end_color="E2EFDA", fill_type="solid")
    R_CAP  = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")
    R_OUT  = PatternFill(start_color="FCE4D6", end_color="FCE4D6", fill_type="solid")
    R_CLOSE= PatternFill(start_color="BDD7EE", end_color="BDD7EE", fill_type="solid")
    R_NOTE = PatternFill(start_color="F2F2F2", end_color="F2F2F2", fill_type="solid")
    WBOLD  = Font(bold=True, color="FFFFFF")

    def _recon_row(ws, label, sign, values, fill, bold=False, total=True):
        row_vals = [label, sign] + values + ([sum(v for v in values if v is not None)] if total else [None])
        ws.append(row_vals)
        for c in ws[ws.max_row]:
            c.fill = fill
            if bold:
                c.font = Font(bold=True)
        for i, c in enumerate(ws[ws.max_row]):
            if i > 1 and isinstance(c.value, (int, float)):
                c.number_format = INR_NUMBER_FORMAT

    # Header
    recon_hdr = ["THOR acct ...0961 — Bank Cash Flow Reconciliation", ""] + MONTHS + ["TOTAL"]
    ws_recon.append(recon_hdr)
    for c in ws_recon[1]:
        c.fill = R_HDR; c.font = WBOLD; c.alignment = Alignment(horizontal="center")

    ws_recon.append(["How the bank balance changed each month — Opening + Credits − Debits = Closing", ""] + [""] * (len(MONTHS) + 1))
    ws_recon[ws_recon.max_row][0].font = Font(italic=True, color="595959")
    ws_recon.append([])

    _recon_row(ws_recon, "Opening Balance",                   "",  _thor_open,   R_OPEN,  bold=True,  total=False)
    _recon_row(ws_recon, "+ Bank Income (UPI + NEFT)",        "+", _thor_income, R_INC,   bold=False)
    _recon_row(ws_recon, "+ Capital injected into bank",      "+", _thor_cap_in, R_CAP,   bold=False)
    _recon_row(ws_recon, "− Capital repaid / transferred out","−", _thor_cap_out,R_CAP,   bold=False)

    # Available subtotal
    _avail = [_thor_open[i] + _thor_income[i] + _thor_cap_in[i] - _thor_cap_out[i] for i in range(len(MONTHS))]
    _recon_row(ws_recon, "= Available before outflows",       "=", _avail,       R_OPEN,  bold=True)

    ws_recon.append([])
    _recon_row(ws_recon, "− Implied Bank Outflows (see note below)", "−", _thor_out, R_OUT, bold=True)
    ws_recon.append([])
    _recon_row(ws_recon, "= Closing Balance (verified from statement)", "=", _thor_close, R_CLOSE, bold=True, total=False)

    ws_recon.append([])
    ws_recon.append([])

    # Explanation note
    notes = [
        ("Why does P&L Gross Income ≠ bank balance change?", ""),
        ("The P&L is ACCRUAL-based and includes both bank and cash flows.", "The bank reconciliation above shows ONLY what moved through the bank account."),
        ("Cash income (physical rent collected)", "₹0 / ₹0 / ₹0 / ₹3.0L / ₹6.5L / ₹10.9L / ₹13.4L  — collected in cash, never deposited to bank"),
        ("Cash expenses (property rent paid cash)", "₹0 / ₹0 / ₹0 / ₹0 / ₹15.3L / ₹12.9L / ₹14.5L  — paid in cash, never leaves bank"),
        ("Net cash items (income − expense)", "Both are roughly equal, so they largely cancel in profit — but neither affects the bank balance"),
        ("", ""),
        ("Implied Bank Outflows includes:", "All actual debits from THOR bank account:"),
        ("  • OPEX paid via UPI/RTGS (electricity, food, staff, furniture, marketing, WiFi…)", ""),
        ("  • Property rent paid via UPI/RTGS", ""),
        ("  • Tenant deposit refunds sent from bank", ""),
        ("  • Cash exchange repayments (non-operating: Sri Lakshmi ₹6L Feb, Sravani ₹7.5L Mar, etc.)", ""),
        ("  • Capital repayments (above, separated out)", ""),
        ("  • Any other bank withdrawals / debits", ""),
    ]
    for label, detail in notes:
        ws_recon.append([label, detail])
        row = ws_recon[ws_recon.max_row]
        row[0].fill = R_NOTE
        row[1].fill = R_NOTE
        if label.startswith("Why") or label.startswith("Implied"):
            row[0].font = Font(bold=True)

    ws_recon.column_dimensions["A"].width = 55
    ws_recon.column_dimensions["B"].width = 6
    for i, col in enumerate("CDEFGHIJ"):
        ws_recon.column_dimensions[col].width = 14
    ws_recon.row_dimensions[1].height = 20
    ws_recon.freeze_panes = "C2"

    # ── Tab 4: Rules Applied ───────────────────────────────────────────────────
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


def build_pnl_bytes(dynamic_data: List[dict] | None = None) -> bytes:
    """Return the P&L workbook as bytes (for streaming from FastAPI).

    Pass `dynamic_data` (per-month DB records) to append new months in SOP format."""
    buf = io.BytesIO()
    build_pnl_workbook(dynamic_data).save(buf)
    buf.seek(0)
    return buf.read()
