"""
src/reports/pnl_verified_data.py
---------------------------------
Pure data module — every hardcoded real-business constant used by the canonical
P&L (src/reports/pnl_builder.py): verified monthly income/opex/deposit/bank-balance
figures, plus the literal text blocks for the THOR Bank Reconciliation and Rules
Applied tabs (real bank account numbers, staff/vendor names, phone numbers).

No logic lives here — only data. pnl_builder.py imports these names and renders
them; a demo deployment can ship src/reports/pnl_verified_data_stub.py (same
public names, empty values) in place of this file to carry zero real financials
or names in source.

Verified figures as of 2026-05-17. See memory/sop_pnl.md for full methodology.
"""
from __future__ import annotations

from typing import Dict, List

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

# Line-key strings that embed real vendor names, re-used verbatim by the
# DB-category → verified-line translation map in pnl_builder.py (kept as
# named constants here so pnl_builder.py never has to spell the name out).
KEY_OPEX_WATER = "Water (bank tankers + Manoj cash; Mar bill paid Apr)"
KEY_OPEX_WASTE = "Waste Disposal (Pavan Rs.3.5K/mo)"

OPEX = {
    "Property Rent — Cash paid (Jan rent in Feb, Feb in Mar, Mar in Apr)": [0, 0, 0, 0, 1532000, 1290000, 1449100, 1532000],  # Feb+Apr Kiran confirmed; Mar corrected to 12,90,000 (Kiran 2026-05-12)
    "Property Rent — Bank UPI/RTGS paid":                                  [0, 0, 0, 0,  600000,  605140,  600000, 600000],  # Feb+Apr+Mar confirmed by Kiran (2026-05-12)
    "Electricity":                                                [0, 0, 74768,   131554,  134538,   96617,  140659, 196371],  # Dec: BESCOM via BBPSBP@ybl
    KEY_OPEX_WATER:       [0, 0, 0,            0,       0,    8000,   84520, 62900],
    "IT & Software":                                              [0, 0, 3480,     12068,     934,    1128,    2348, 876],  # Jan +948 office phone; Feb +934 mobile recharge; Mar +1128 paybil/payair; Apr +2348. Updated 2026-05-13
    "Internet & WiFi (cash — Jan Airwire UPI, Feb 8x Razorpay, Mar-Dec Rs.0)": [0, 0, 43946, 70730, 113168, 0, 0, 0],  # Dec +3000 wifi dongles (Kiran cash)
    "Food & Groceries":                                           [0, 33632, 113787, 217504,  115595,  240294,  239753, 278418],  # Apr +875 Chandra cash (egg trays). Jan +1086 Origin veg; Feb +792 Amazon food; Apr +756 Ratnadeep. 2026-05-17
    "Fuel & Diesel":                                              [0, 0, 1200,      9599,  105866,  364161,   61904, 134118],  # Mar +8190 Chandra cash (diesel 6370+cans 1820). Jan +500 Shell India; Apr +326 volipi.l. 2026-05-17
    "Staff & Labour":                                             [0, 1000, 135435, 116714, 171295,  217341,  193617, 76258],  # Feb -63000 (9342205440 gas pipeline welding reclassified to Maintenance; confirmed Kiran 2026-05-30). Jan +790 petty wages; Feb +580 petty wages; Mar +29000 volipi.l salary. Updated 2026-05-30
    "Maintenance & Repairs":                                      [0, 0, 1400,     22450,   64850,   23399,   39319, 18600],  # Feb +63000 (9342205440 gas pipeline welding; was Staff & Labour; confirmed Kiran 2026-05-30). Mar +1500 Chandra (carpenter 1000+generator 500); Apr +2400 Chandra (plumbers 1500+elec 900). Updated 2026-05-30
    "Cleaning Supplies":                                          [0, 0, 5674,       1880,    1200,   11272,   18315, 564],  # Jan +480 Hinglaj packaging; Apr +340 kastig soda. Updated 2026-05-13
    KEY_OPEX_WASTE:                                               [0, 0, 0,          3000,    3500,    3500,    3500, 3500],
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
# Source: DB query 2026-05-06
DEPOSITS = {
    # Pure refundable security only (combined total was ₹33,83,875 but included maintenance ₹10,68,700)
    # True refundable = combined − maintenance = ₹33,83,875 − ₹10,68,700 = ₹23,15,175
    "Security Deposits — refundable (must return to active tenants)": [0, 140000, 266500, 455500, 353000, 526550, 573625, 744534],
    # Maintenance retained = by EXIT month (Kiran directive 2026-07-11): the fee stands
    # finally kept when the tenant checks out. DB has no exit records before Mar'26
    # (pre-live window), so Oct–Feb show 0. Display-only — never in True Revenue math.
    "  Maintenance Fee retained (non-refundable, by exit month)": [0, 0, 0, 0, 0, 34500, 108500, 95500],
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

# ── THOR Bank Reconciliation tab (Tab 3) — capital flows that actually hit the
# THOR bank account (not cash/personal advances)
THOR_CAP_IN  = [500000, 0,      0, 90000, 0, 0,      0, 0]  # Oct: startup ₹5L; Jan: Kiran top-up ₹90K
THOR_CAP_OUT = [0,      500000, 0, 0,     0, 0, 500000, 0]  # Nov: startup repaid ₹5L; Apr: transferred to HULK ₹5L

# Explanation note block rendered under the THOR reconciliation (real cash figures
# and vendor names — Sri Lakshmi, Sravani, etc.)
RECON_NOTES: List[tuple] = [
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

# ── "⚠ ITEMS NEEDING KIRAN REVIEW" flags — rendered on tabs 1 & 2. Contains real
# names (Chandra, Sri Lakshmi, Sravani, Bharathi, Prabhakaran, Manoj) and amounts.
KIRAN_REVIEW_FLAGS: List[str] = [
    "1. Manoj water bill for April (paid in May — amount TBD). Add to Water line when known.",
    "2. Apr rent of Rs.20,49,100 paid in May is outside this P&L window — will appear in May P&L.",
    "3. Chandra advance Rs.18,965 confirmed from handwritten notebook (2026-05-17): Feb police Rs.3K, Mar diesel Rs.6,370+cans Rs.1,820+carpenter Rs.1K+generator Rs.500+police Rs.3K=Rs.12,690, Apr plumber Rs.1,500+elec Rs.900+egg trays Rs.875=Rs.3,275. Added to OPEX categories (Fuel/Govt/Maintenance/Food) and Capital Contributions.",
    "4. Cash Exchange Repayments (in EXCLUDED): Feb Rs.6L Sri Lakshmi, Mar Rs.15.5L (Sravani 7.5L+Sri Lakshmi 6L+Bharathi 2L), Apr Rs.22K (Prabhakaran+Amazon Pay Later). Rs.40K shalu (id 1655) confirmed fire stove purchase — moved to Furniture & Supplies Mar.",
    "5. bank_transactions id 1655 (shalu Rs.40K) category still shows Non-Operating in DB — update to Furniture & Fittings for live P&L endpoint to match this report.",
]

# ── Rules Applied tab (Tab 4) — methodology notes with real staff/vendor names,
# phone numbers, and rent rates.
RULES_APPLIED: List[tuple] = [
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
