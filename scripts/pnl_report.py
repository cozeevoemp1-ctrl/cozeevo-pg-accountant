"""
P&L Report — Income vs Expenses, classified and categorised by month.
"""
import re
import pandas as pd
from pathlib import Path
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

SRC = "Statement-124563400000961-03-10-2026-20-15-08 (1)_extracted.xlsx"
OUT = "PnL_Report.xlsx"

MONTHS = ['Dec 2025', 'Jan 2026', 'Feb 2026', 'Mar 2026']

# ── Classify expenses ─────────────────────────────────────────────────────────
EXPENSE_RULES = [
    # ── PROPERTY RENT ──────────────────────────────────────────────────────────
    ("Property Rent",        "Vakkal Sravani",               ["vakkal", "sravani"]),
    ("Property Rent",        "R Suma",                       ["r suma", "rsuma"]),
    ("Property Rent",        "Raghu Nandha Mandadi",         ["raghu nandha"]),
    ("Property Rent",        "Sri Lakshmi Chandrasekhar",    ["lakshmi chandrasekhar"]),
    ("_income_",             "Bharathi (shown as Other Income)",  ["bharathi"]),
    ("Property Rent",        "Other Rent Payments",          ["jan rent","feb rent","mar rent","rent pay"]),

    # ── ELECTRICITY ────────────────────────────────────────────────────────────
    ("Electricity",          "BESCOM Bill",                  ["bescom","besco"]),

    # ── INTERNET & WIFI ────────────────────────────────────────────────────────
    ("Internet & WiFi",      "Airwire Broadband",            ["airwire"]),
    ("Internet & WiFi",      "KIPINN (ISP)",                 ["kipinn","kipnn","kipi nn","kipin"]),
    ("Internet & WiFi",      "WiFi Vendor",                  ["wifi","wi-fi","broadband"]),

    # ── FURNITURE & FITTINGS ───────────────────────────────────────────────────
    ("Furniture & Fittings", "Wakefit - Mattresses",         ["wakefit"]),
    ("Furniture & Fittings", "Bedsheets / Linen",            ["bedsheet","bed sheet"]),
    ("Furniture & Fittings", "Shoe Rack / Rack",             ["shoe rack","rack balance","9108617776"]),
    ("Furniture & Fittings", "Curtains",                     ["curtain"]),
    ("Furniture & Fittings", "Bedframes (Grace Traders)",    ["grace trader","bedframe","bed frame"]),
    ("Furniture & Fittings", "Usha Trading (TV/Equipment)",  ["usha trading","usha t rading"]),
    ("Furniture & Fittings", "Cot Placement / Labour",       ["cot placement","cot place","cot plac","jubair"]),
    ("Furniture & Fittings", "Porter / Delivery",            ["porter fee","porter","bed frames porter"]),
    ("Furniture & Fittings", "Other Furniture / Fittings",   ["furniture","refurbish","3d bo","laughing bud"]),

    # ── FOOD & GROCERIES ───────────────────────────────────────────────────────
    ("Food & Groceries",     "Grocery - Virani Trading",     ["virani"]),
    ("Food & Groceries",     "Food Supplies - Vyapar",       ["vyapar"]),
    ("Food & Groceries",     "Gas Cylinders (DRP Ent.)",     ["cylinder","lpg","drp enterprise","9880707836"]),
    ("Food & Groceries",     "Chicken / Meat",               ["chicken","biryani","meat","q858145123","paytmqr6li6zl","paytmqr6wro5d","paytmqr6pxr4","q213610007","q494874704","q457756301","q236290371","q067427224"]),
    ("Food & Groceries",     "Eggs",                         ["eggs","egg trays","9900343230-2@axl/eggs","9900343230","prakash 6 trays"]),
    ("Food & Groceries",     "Vegetables & Greens",          ["vegetable","veggies","veggie","greens","tomato","chilli","chillies","cucumber","lemon","coriander","pudina","paneer","curd","vangi","bellandur veg","aftabaftabpasha","vasanthaomkar","paytmqr15d86eyq1b@paytm/paneer","paytmqr15d86eyq1b@paytm/lemon","paytm.s1insnj@pty/chilli","paytm.s1insnj@pty/green","paytmqr6yextn@ptys","q858145123@ybl/chicken","paytmqr5kbzg9"]),
    ("Food & Groceries",     "Ninjacart (Veg Supplier)",     ["ninjacart","ninja kart","ninjakart","ninja cart","paytm-7102662","paytm-30461933","payt m-30461933","oidninj"]),
    ("Food & Groceries",     "Zepto / Blinkit / Swiggy",     ["zepto","zept o","zeptoma","blinkit","blinki t","swiggystores","swiggy484","s wiggy","swiggyu","swigg y","wiggy484","swiggy","instamart","zeptonow"]),
    ("Food & Groceries",     "WholesaleMandi / Origin",      ["wholesalemandi","wholesale mandi","origin903039","origin108856"]),
    ("Food & Groceries",     "D-Mart / Retail",              ["dmart","d-mart","innovdmart"]),
    ("Food & Groceries",     "Cooking Oil / Masala",         ["oil","ruchi gold","cooleant oil","basmati rice","rice"]),
    ("Food & Groceries",     "Icecream / Beverages",         ["icecream","ice cream"]),
    ("Food & Groceries",     "HP Gas",                       ["hp gas","q947171136"]),
    ("Food & Groceries",     "Milk / Curd Bulk (M036TPQEK)", ["m036tpqek"]),
    ("Food & Groceries",     "Other Groceries / Provisions", ["grocer","kirana","milk","food","provision","veggies","veggie"]),

    # ── FUEL & DIESEL ──────────────────────────────────────────────────────────
    ("Fuel & Diesel",        "DG Rent / Generator",          ["sunilgn8834","dg rent"]),
    ("Fuel & Diesel",        "Diesel - deepu.1222",          ["deepu.1222","d eepu.1222","eepu.1222","diesel","litres","150 litre","170 litre","100 litre"]),
    ("Fuel & Diesel",        "Diesel Vendor (9888751222)",   ["9888751222"]),
    ("Fuel & Diesel",        "Diesel Vendor (7411535239)",   ["7411535239"]),
    ("Fuel & Diesel",        "Petrol / Fuel",                ["petrol","fuel"]),

    # ── STAFF & LABOUR ─────────────────────────────────────────────────────────
    ("Staff & Labour",       "Salary - Arjun (NEFT)",        ["joshi arjun","net-neft-yes","yesob6021"]),
    ("Staff & Labour",       "Salary - Arjun (UPI batches)", ["arjun"]),
    ("Staff & Labour",       "Salary - Phiros / Phirose",    ["phiros","phirose"]),
    ("Staff & Labour",       "Salary - Lokesh",              ["lokesh"]),
    ("Staff & Labour",       "Salary - Ram Bilas",           ["ram bilas"]),
    ("Staff & Labour",       "Salary - Krishnaveni",         ["krishnaveni"]),
    ("Staff & Labour",       "Salary - Other Staff",         ["salary","saurav","kalyani","nikhil","bikey","abhishek"]),
    ("Staff & Labour",       "Staff - 7680814628 (Regular)", ["7680814628"]),
    ("Staff & Labour",       "Staff - 9110460729",           ["9110460729"]),
    ("Staff & Labour",       "Staff - 9102937483",           ["9102937483"]),
    ("Staff & Labour",       "Staff - 9342205440 (Vendor)",  ["9342205440"]),
    ("Staff & Labour",       "Advance for Cook (Rampukar)",  ["rampukar","advance for cook","cooking t"]),
    ("Staff & Labour",       "WorkIndia (Recruitment)",      ["workindia","work india"]),
    ("Staff & Labour",       "Staff - kn.ravikumar (Vendor)",["kn.ravikumar","ravikumar80"]),
    ("Staff & Labour",       "Staff - sachindivya (Regular)",["sachindivya"]),
    ("Staff & Labour",       "Staff - 8073343903",           ["8073343903"]),
    ("Staff & Labour",       "Staff - 6366411789",           ["6366411789"]),
    ("Staff & Labour",       "Sanket (Person Transfer)",     ["sanket.wankhede","sanket"]),
    ("Staff & Labour",       "Biplab (Contractor/Vendor)",   ["biplab"]),
    ("Staff & Labour",       "Housekeeping / Cleaning Staff",["housekeep","salamtajamul","sarojrout","dilliprout","swamisarang","manisha","t.srinivasa","9398545495","9611622637","9071242117","8837062479","837062479"]),
    ("Staff & Labour",       "Urban Company (Cleaning Svc)", ["urbancompany","urban company"]),
    ("Staff & Labour",       "Salary - Vivek (Helper)",      ["6202601070","vivek"]),
    ("Staff & Labour",       "Labour / Helpers",             ["helper","labour","kshitij"]),
    ("Staff & Labour",       "Staff - 9880401360 (Regular)", ["9880401360"]),
    ("Staff & Labour",       "Staff - gudadesh (Contractor)",["gudadesh","udadesh"]),
    ("Staff & Labour",       "Staff - sandeepgowda",         ["sandeepgowda"]),
    ("Staff & Labour",       "Staff - akmalakmal",           ["akmalakmal"]),
    ("Staff & Labour",       "Staff - kutubuddinku",         ["kutubuddinku"]),
    ("Staff & Labour",       "Staff - vishal521",            ["vishal521"]),

    # ── GOVT & REGULATORY ──────────────────────────────────────────────────────
    ("Govt & Regulatory",    "BBMP Tax / Property Bill",     ["bbmp","bbpsbp"]),
    ("Govt & Regulatory",    "Directorate / Reg Fees",       ["edcs","directorate"]),
    ("Govt & Regulatory",    "GST Charges",                  ["sdb_gst","gst"]),

    # ── TENANT DEPOSIT REFUND ──────────────────────────────────────────────────
    ("Tenant Deposit Refund","Anurag - Checkout Refund",     ["anurag checkout","anurag.cerpa"]),
    ("Tenant Deposit Refund","Sameer & Rishika Refund",      ["sameer and rishika","sameer rishika"]),
    ("Tenant Deposit Refund","Akshay Refund",                ["akshay refund","akshaybhagat"]),
    ("Tenant Deposit Refund","Yogeshwaran Exit Refund",      ["yogeshwaran refund","kiyogesh"]),
    ("Tenant Deposit Refund","Booking Cancellation Refund",  ["booking cancellation","nitinkalburgi"]),
    ("Tenant Deposit Refund","Rent Refund (Sourabh)",        ["rent refund","sourabh"]),
    ("Tenant Deposit Refund","Omkar Refund",                 ["refund omkar","omtpkjh456"]),
    ("Tenant Deposit Refund","Ankitdude Refund",             ["refund amount","ankitdude"]),
    ("Tenant Deposit Refund","Other Refund / Exit",          ["refund","exit refund","checkout refund","9518874547"]),
    ("Other Expenses",       "Akhilreddy (Unknown)",         ["akhilreddy007420","akhilreddy","khilreddy"]),

    # ── MARKETING ──────────────────────────────────────────────────────────────
    ("Marketing",            "Logo T-shirts",                ["logo tshirt","logo t-shirt","tshirt"]),
    ("Marketing",            "Ad Board / Sun Boards",        ["9845068141","sun board","sunboard"]),
    ("Marketing",            "Flyers / Banners",             ["flyers","flyer","hulk banner","banner","flags","kalpanakannan"]),
    ("Marketing",            "Marketing / Promotions",       ["marketing","advertisement"]),

    # ── CLEANING & HOUSEKEEPING SUPPLIES ───────────────────────────────────────
    ("Cleaning Supplies",    "Garbage Bags / Bins",          ["garbage bag","garbage","paytmqr6fhib2@ptys/garbage"]),
    ("Cleaning Supplies",    "Phenyl / Disinfectant",        ["phenyl","disinfect","toilet adour","toilet filter","paytmqr60o1ob@ptys/toilet"]),
    ("Cleaning Supplies",    "Mop / Cleaning Tools",         ["mop","broom","knife sharpen","knife"]),
    ("Cleaning Supplies",    "Room Freshener / Hooks",       ["room freshner","freshner","hooks"]),
    ("Cleaning Supplies",    "AdBlue (DG Exhaust Fluid)",    ["adblue","ad blu"]),

    # ── SHOPPING & SUPPLIES ────────────────────────────────────────────────────
    ("Shopping & Supplies",  "Amazon",                       ["amazon"]),
    ("Shopping & Supplies",  "Flipkart",                     ["flipkart","flipkar t","flipk art"]),
    ("Shopping & Supplies",  "BharatPE (POS Payments)",      ["bharatpe","haratpe","bharat pe"]),
    ("Shopping & Supplies",  "Pine Labs (POS Terminal)",     ["pinelab","pi nelabs","pin elabs","nelabs.1"]),
    ("Shopping & Supplies",  "Rapido (Transport)",           ["rapido"]),
    ("Shopping & Supplies",  "Mosquito / Pest Supplies",     ["mosquito","mosquitos","pest"]),
    ("Shopping & Supplies",  "Hardware / Granite",           ["hardware","granite"]),
    ("Shopping & Supplies",  "Printing / Xerox",             ["printout","xerox","print"]),
    ("Shopping & Supplies",  "Other Online / Misc",          ["meesho","myntra","paytm-56505013","zepto.payu","jio","airtel","a irtelpredirect","irtelpredirect","viinapp","phegade","airtelpredirect"]),

    # ── MAINTENANCE & REPAIRS ──────────────────────────────────────────────────
    ("Maintenance & Repairs","Plumbing",                     ["plumbing","plumber","dilliprout1383@ybl/plumb","chandan865858"]),
    ("Maintenance & Repairs","Electrician / Electrical",     ["electrician","electrical"]),
    ("Maintenance & Repairs","Repairs / Handyman",           ["repair","handyman"]),
    ("Maintenance & Repairs","Key Duplicate / Locks",        ["/keys","key duplicate","locksmith"]),
    ("Maintenance & Repairs","General Maintenance",          ["maintenance","maintain"]),

    # ── BANK CHARGES ───────────────────────────────────────────────────────────
    ("Bank Charges",         "Debit Card Fee",               ["debit card replacement","debit card replace","card replace"]),
    ("Bank Charges",         "Bank Transfer / IMPS / NEFT",  ["imps","rtgs","neft","yib-neft","net-neft"]),

    # ── UNCLASSIFIED (catch-all) ───────────────────────────────────────────────
    ("Other Expenses",       "Misc UPI Payments",            []),
]

# ── Manual entries (not in bank statement) ────────────────────────────────────
# Format: (Category, Sub-category, Month, Amount, Note)
MANUAL_ENTRIES = [
    # Add entries here only when confirmed by user with exact amounts — never guess
]

# ── Manual income entries (not in bank statement) ─────────────────────────────
# Format: (Category, Sub-category, Month, Amount, Note)
MANUAL_INCOME_ENTRIES = [
    # Add entries here only when confirmed by user with exact amounts — never guess
]

INCOME_RULES = [
    ("Rent Income",     "UPI Collection Settlement",  ["upi collection settlement","115063600001082"]),
    ("Rent Income",     "Direct UPI from Tenants",    ["upi/"]),
    ("Other Income",    "NEFT / RTGS Inward",         ["neft","rtgs","imps"]),
    ("Other Income",    "Cashback / Refund",          ["refund","cashback","reversal"]),
    ("Other Income",    "Other Inward",               []),
]


def classify(desc, rules):
    d = (desc or "").lower()
    for cat, sub, keywords in rules:
        if not keywords:
            continue
        for kw in keywords:
            if kw in d:
                return cat, sub
    return rules[-1][0], rules[-1][1]


# ── Styling helpers ───────────────────────────────────────────────────────────
HDR  = "1F497D"
GRN  = "1A5276"   # income header
RED  = "922B21"   # expense header
THIN = Side(style="thin", color="CCCCCC")
MED  = Side(style="medium", color="666666")
B    = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
BM   = Border(left=THIN, right=THIN, top=THIN, bottom=MED)

INC_BG  = "D5F5E3"   # light green
EXP_BG  = "FDEDEC"   # light red
TTL_BG  = "D6EAF8"   # blue total
NET_BG_P= "A9DFBF"   # net positive
NET_BG_N= "F1948A"   # net negative
CAT_SHADES = [
    "FDFEFE","F9EBEA","EBF5FB","E8F8F5","FEF9E7","F5EEF8","E8F8F5","FDFEFE"
]

def fw(bold=False, size=10, color="000000", italic=False):
    return Font(name="Calibri", bold=bold, size=size, color=color, italic=italic)

def fill(hex):
    return PatternFill("solid", fgColor=hex)

def aln(h="left", wrap=False):
    return Alignment(horizontal=h, vertical="center", wrap_text=wrap)

def hcell(ws, r, c, v, bg=HDR, color="FFFFFF", bold=True, size=10, align="center"):
    cell = ws.cell(r, c, v)
    cell.font      = Font(name="Calibri", bold=bold, color=color, size=size)
    cell.fill      = PatternFill("solid", fgColor=bg)
    cell.alignment = Alignment(horizontal=align, vertical="center", wrap_text=True)
    cell.border    = B
    return cell

def dcell(ws, r, c, v, bg, bold=False, color="000000", align="left", fmt=None):
    cell = ws.cell(r, c, v if v != 0 else None)
    cell.font      = Font(name="Calibri", bold=bold, color=color, size=9)
    cell.fill      = PatternFill("solid", fgColor=bg)
    cell.alignment = Alignment(horizontal=align, vertical="center")
    cell.border    = B
    if fmt:
        cell.number_format = fmt
    return cell

def widths(ws, w):
    for i, x in enumerate(w, 1):
        ws.column_dimensions[get_column_letter(i)].width = x


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    df = pd.read_excel(SRC)
    df['Withdrawals'] = df['Withdrawals'].apply(lambda x: x if isinstance(x, float) else 0)
    df['Deposits']    = df['Deposits'].apply(lambda x: x if isinstance(x, float) else 0)
    df['_date']       = pd.to_datetime(df['Transaction Date'], format='%Y-%m-%d', errors='coerce')
    df['Month']       = pd.Categorical(df['_date'].dt.strftime('%b %Y'), categories=MONTHS, ordered=True)

    # Classify
    exp_df = df[df['Withdrawals'] > 0].copy()
    exp_df[['Cat','Sub']] = pd.DataFrame(
        [classify(d, EXPENSE_RULES) for d in exp_df['Description']], index=exp_df.index)

    # Drop transactions reclassified as income (tagged _income_)
    exp_df = exp_df[exp_df['Cat'] != '_income_']

    # Inject manual entries (payments not in bank statement)
    if MANUAL_ENTRIES:
        manual_rows = pd.DataFrame([{
            'Transaction Date': f"[Manual] {note}",
            'Description':      f"[Manual] {note}",
            'Withdrawals':      amt,
            'Deposits':         0,
            'Month':            pd.Categorical([month], categories=MONTHS, ordered=True)[0],
            'Cat':              cat,
            'Sub':              sub,
            '_date':            pd.NaT,
        } for cat, sub, month, amt, note in MANUAL_ENTRIES])
        exp_df = pd.concat([exp_df, manual_rows], ignore_index=True)

    inc_df = df[df['Deposits'] > 0].copy()
    inc_df[['Cat','Sub']] = pd.DataFrame(
        [classify(d, INCOME_RULES) for d in inc_df['Description']], index=inc_df.index)

    # Inject manual income entries (receipts not in bank statement)
    if MANUAL_INCOME_ENTRIES:
        manual_inc_rows = pd.DataFrame([{
            'Transaction Date': f"[Manual] {note}",
            'Description':      f"[Manual] {note}",
            'Withdrawals':      0,
            'Deposits':         amt,
            'Month':            pd.Categorical([month], categories=MONTHS, ordered=True)[0],
            'Cat':              cat,
            'Sub':              sub,
            '_date':            pd.NaT,
        } for cat, sub, month, amt, note in MANUAL_INCOME_ENTRIES])
        inc_df = pd.concat([inc_df, manual_inc_rows], ignore_index=True)

    wb = Workbook()
    wb.remove(wb.active)

    # ════════════════════════════════════════════════════════════════════════════
    # SHEET 1 — P&L SUMMARY
    # ════════════════════════════════════════════════════════════════════════════
    ws = wb.create_sheet("P&L Summary")

    # Title
    ncols = 2 + len(MONTHS) + 1
    ws.merge_cells(f"A1:{get_column_letter(ncols)}1")
    c = ws["A1"]
    c.value     = "Profit & Loss Statement — LAKSHMI GORJALA / YES Bank (Dec 2025 – Mar 2026)"
    c.font      = Font(name="Calibri", bold=True, size=14, color="FFFFFF")
    c.fill      = PatternFill("solid", fgColor=HDR)
    c.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 26

    # Column headers
    hcell(ws, 2, 1, "Section",          HDR)
    hcell(ws, 2, 2, "Category",         HDR)
    for i, m in enumerate(MONTHS, 3):
        hcell(ws, 2, i, m, HDR)
    hcell(ws, 2, ncols, "TOTAL",        HDR)
    ws.row_dimensions[2].height = 22

    row = 3

    def section_header(label, bg):
        ws.merge_cells(f"A{row}:{get_column_letter(ncols)}{row}")
        c2 = ws.cell(row, 1, label)
        c2.font      = Font(name="Calibri", bold=True, size=11, color="FFFFFF")
        c2.fill      = PatternFill("solid", fgColor=bg)
        c2.alignment = Alignment(horizontal="left", vertical="center")
        c2.border    = B
        ws.row_dimensions[row].height = 18

    # ── INCOME section ─────────────────────────────────────────────────────────
    section_header("  INCOME", GRN)
    row += 1

    inc_pivot = inc_df.pivot_table(index='Cat', columns='Month', values='Deposits',
                                    aggfunc='sum', fill_value=0, observed=True)
    inc_pivot['TOTAL'] = inc_pivot.sum(axis=1)
    inc_pivot = inc_pivot.sort_values('TOTAL', ascending=False)

    inc_section_total = {m: 0.0 for m in MONTHS}; inc_section_total['TOTAL'] = 0.0

    for cat, pivot_row in inc_pivot.iterrows():
        bg = INC_BG
        ws.cell(row, 1, "").fill = PatternFill("solid", fgColor=bg); ws.cell(row,1).border=B
        dcell(ws, row, 2, str(cat), bg, bold=True, color="1A5276")
        for i, m in enumerate(MONTHS, 3):
            v = pivot_row.get(m, 0)
            dcell(ws, row, i, v if v else None, bg, align="right", fmt="#,##0", color="1A5276")
            inc_section_total[m] += v
        dcell(ws, row, ncols, pivot_row['TOTAL'], bg, bold=True, align="right", fmt="#,##0", color="1A5276")
        inc_section_total['TOTAL'] += pivot_row['TOTAL']
        row += 1

    # Income total
    dcell(ws, row, 1, "TOTAL INCOME", TTL_BG, bold=True, color="1A5276")
    ws.cell(row, 1).border = BM
    ws.merge_cells(f"A{row}:B{row}")
    for i, m in enumerate(MONTHS, 3):
        c2 = dcell(ws, row, i, inc_section_total[m], TTL_BG, bold=True, align="right", fmt="#,##0", color="1A5276")
        c2.border = BM
    c2 = dcell(ws, row, ncols, inc_section_total['TOTAL'], TTL_BG, bold=True, align="right", fmt="#,##0", color="1A5276")
    c2.border = BM
    ws.row_dimensions[row].height = 16
    row += 2

    # ── EXPENSES section ───────────────────────────────────────────────────────
    section_header("  EXPENSES", RED)
    row += 1

    exp_pivot = exp_df.pivot_table(index='Cat', columns='Month', values='Withdrawals',
                                    aggfunc='sum', fill_value=0, observed=True)
    exp_pivot['TOTAL'] = exp_pivot.sum(axis=1)
    exp_pivot = exp_pivot.sort_values('TOTAL', ascending=False)

    exp_section_total = {m: 0.0 for m in MONTHS}; exp_section_total['TOTAL'] = 0.0

    for cat, pivot_row in exp_pivot.iterrows():
        bg = EXP_BG
        ws.cell(row, 1, "").fill = PatternFill("solid", fgColor=bg); ws.cell(row,1).border=B
        dcell(ws, row, 2, str(cat), bg, bold=True, color="922B21")
        for i, m in enumerate(MONTHS, 3):
            v = pivot_row.get(m, 0)
            dcell(ws, row, i, v if v else None, bg, align="right", fmt="#,##0", color="922B21")
            exp_section_total[m] += v
        dcell(ws, row, ncols, pivot_row['TOTAL'], bg, bold=True, align="right", fmt="#,##0", color="922B21")
        exp_section_total['TOTAL'] += pivot_row['TOTAL']
        row += 1

    # Expense total
    dcell(ws, row, 1, "TOTAL EXPENSES", TTL_BG, bold=True, color="922B21")
    ws.cell(row, 1).border = BM
    ws.merge_cells(f"A{row}:B{row}")
    for i, m in enumerate(MONTHS, 3):
        c2 = dcell(ws, row, i, exp_section_total[m], TTL_BG, bold=True, align="right", fmt="#,##0", color="922B21")
        c2.border = BM
    c2 = dcell(ws, row, ncols, exp_section_total['TOTAL'], TTL_BG, bold=True, align="right", fmt="#,##0", color="922B21")
    c2.border = BM
    ws.row_dimensions[row].height = 16
    row += 2

    # ── NET PROFIT / LOSS ──────────────────────────────────────────────────────
    ws.merge_cells(f"A{row}:{get_column_letter(ncols)}{row}")
    c3 = ws.cell(row, 1, "NET PROFIT / LOSS")
    c3.font      = Font(name="Calibri", bold=True, size=11, color="FFFFFF")
    c3.fill      = PatternFill("solid", fgColor="1A5276")
    c3.alignment = Alignment(horizontal="left", vertical="center")
    c3.border    = B
    ws.row_dimensions[row].height = 18
    row += 1

    for i, m in enumerate(MONTHS, 3):
        net = inc_section_total[m] - exp_section_total[m]
        bg  = NET_BG_P if net >= 0 else NET_BG_N
        col_str = "1A5276" if net >= 0 else "922B21"
        label = f"+Rs {net:,.0f}" if net >= 0 else f"-Rs {abs(net):,.0f}"
        ws.cell(row, 1, "").fill = PatternFill("solid", fgColor="FFFFFF"); ws.cell(row,1).border=B
        ws.cell(row, 2, m).font = Font(name="Calibri", bold=True, size=10)
        ws.cell(row, 2).fill = PatternFill("solid", fgColor="FFFFFF"); ws.cell(row,2).border=B
        dcell(ws, row, i, net, bg, bold=True, align="right", fmt="#,##0", color=col_str)

    total_net = inc_section_total['TOTAL'] - exp_section_total['TOTAL']
    bg_net    = NET_BG_P if total_net >= 0 else NET_BG_N
    c4 = dcell(ws, row, ncols, total_net, bg_net, bold=True, align="right", fmt="#,##0",
               color="1A5276" if total_net >= 0 else "922B21")
    ws.row_dimensions[row].height = 18
    row += 1

    widths(ws, [20, 28] + [14]*len(MONTHS) + [14])
    ws.freeze_panes = "A3"
    ws.column_dimensions['A'].width = 20
    ws.column_dimensions['B'].width = 28

    # ════════════════════════════════════════════════════════════════════════════
    # SHEET 2 — INCOME DETAIL
    # ════════════════════════════════════════════════════════════════════════════
    ws_inc = wb.create_sheet("Income Detail")
    ws_inc.merge_cells("A1:G1")
    h = ws_inc["A1"]
    h.value = "Income Transactions Detail"
    h.font = Font(name="Calibri", bold=True, size=13, color="FFFFFF")
    h.fill = PatternFill("solid", fgColor=GRN)
    h.alignment = Alignment(horizontal="center")

    for c2, hd in enumerate(["#","Date","Amount (Rs)","Category","Sub-Category","Description","Month"],1):
        hcell(ws_inc, 2, c2, hd, GRN)

    inc_sorted = inc_df.sort_values('_date').reset_index(drop=True)
    for i, (_, r2) in enumerate(inc_sorted.iterrows(), 1):
        ro = i + 2
        dcell(ws_inc, ro, 1, i,                        INC_BG, align="center")
        dcell(ws_inc, ro, 2, r2['Transaction Date'],   INC_BG)
        dcell(ws_inc, ro, 3, r2['Deposits'],            INC_BG, bold=True, align="right", fmt="#,##0.00", color="1A5276")
        dcell(ws_inc, ro, 4, r2['Cat'],                INC_BG, bold=True)
        dcell(ws_inc, ro, 5, r2['Sub'],                INC_BG)
        dcell(ws_inc, ro, 6, str(r2['Description'])[:100], INC_BG)
        dcell(ws_inc, ro, 7, str(r2.get('Month','')), INC_BG, align="center")

    tr = len(inc_sorted) + 3
    ws_inc.cell(tr, 4, "TOTAL INCOME").font = Font(bold=True, name="Calibri")
    c5 = ws_inc.cell(tr, 3, inc_sorted['Deposits'].sum())
    c5.number_format = "#,##0.00"; c5.font = Font(bold=True, name="Calibri", color="1A5276")
    c5.alignment = Alignment(horizontal="right")
    for col in range(1, 8):
        ws_inc.cell(tr, col).fill   = PatternFill("solid", fgColor="D5F5E3")
        ws_inc.cell(tr, col).border = B

    widths(ws_inc, [4, 12, 14, 22, 30, 60, 10])
    ws_inc.freeze_panes = "A3"

    # ════════════════════════════════════════════════════════════════════════════
    # SHEET 3 — EXPENSE DETAIL
    # ════════════════════════════════════════════════════════════════════════════
    ws_exp = wb.create_sheet("Expense Detail")
    ws_exp.merge_cells("A1:G1")
    h2 = ws_exp["A1"]
    h2.value = "Expense Transactions Detail"
    h2.font = Font(name="Calibri", bold=True, size=13, color="FFFFFF")
    h2.fill = PatternFill("solid", fgColor=RED)
    h2.alignment = Alignment(horizontal="center")

    for c2, hd in enumerate(["#","Date","Amount (Rs)","Category","Sub-Category","Description","Month"],1):
        hcell(ws_exp, 2, c2, hd, RED)

    exp_sorted = exp_df.sort_values('_date').reset_index(drop=True)
    for i, (_, r2) in enumerate(exp_sorted.iterrows(), 1):
        ro = i + 2
        dcell(ws_exp, ro, 1, i,                        EXP_BG, align="center")
        dcell(ws_exp, ro, 2, r2['Transaction Date'],   EXP_BG)
        dcell(ws_exp, ro, 3, r2['Withdrawals'],         EXP_BG, bold=True, align="right", fmt="#,##0.00", color="922B21")
        dcell(ws_exp, ro, 4, r2['Cat'],                EXP_BG, bold=True)
        dcell(ws_exp, ro, 5, r2['Sub'],                EXP_BG)
        dcell(ws_exp, ro, 6, str(r2['Description'])[:100], EXP_BG)
        dcell(ws_exp, ro, 7, str(r2.get('Month','')), EXP_BG, align="center")

    tr2 = len(exp_sorted) + 3
    ws_exp.cell(tr2, 4, "TOTAL EXPENSES").font = Font(bold=True, name="Calibri")
    c6 = ws_exp.cell(tr2, 3, exp_sorted['Withdrawals'].sum())
    c6.number_format = "#,##0.00"; c6.font = Font(bold=True, name="Calibri", color="922B21")
    c6.alignment = Alignment(horizontal="right")
    for col in range(1, 8):
        ws_exp.cell(tr2, col).fill   = PatternFill("solid", fgColor="FADBD8")
        ws_exp.cell(tr2, col).border = B

    widths(ws_exp, [4, 12, 14, 22, 30, 60, 10])
    ws_exp.freeze_panes = "A3"

    wb.save(OUT)

    # ── Console P&L ───────────────────────────────────────────────────────────
    tot_inc = inc_sorted['Deposits'].sum()
    tot_exp = exp_sorted['Withdrawals'].sum()
    net     = tot_inc - tot_exp

    W = 14  # column width per month

    def mrow(label, vals):
        line = "  " + label[:34].ljust(34)
        for m in MONTHS:
            v = vals.get(m, 0)
            cell = ("Rs " + f"{v:,.0f}") if v else "-"
            line += "  " + cell.rjust(W)
        tot = vals.get("TOTAL", 0)
        line += "  " + ("Rs " + f"{tot:,.0f}").rjust(W)
        print(line)

    SEP = "=" * (36 + (W+2)*(len(MONTHS)+1))
    print()
    print(SEP)
    print("  MONTH-BY-MONTH P&L  -  YES Bank / LAKSHMI GORJALA")
    print(SEP)

    # Header
    hdr = f"  {'Category':<34}"
    for m in MONTHS:
        hdr += f"  {m:>{W}}"
    hdr += f"  {'TOTAL':>{W}}"
    print(hdr)
    print("-" * len(hdr))

    # ── INCOME ──
    print("  INCOME")
    inc_pivot2 = inc_df.pivot_table(index='Cat', columns='Month', values='Deposits',
                                     aggfunc='sum', fill_value=0, observed=True)
    inc_pivot2['TOTAL'] = inc_pivot2.sum(axis=1)
    inc_m_totals = {m: inc_df[inc_df['Month']==m]['Deposits'].sum() for m in MONTHS}
    inc_m_totals['TOTAL'] = tot_inc
    for cat in inc_pivot2.index:
        row_vals = {m: inc_pivot2.loc[cat, m] if m in inc_pivot2.columns else 0 for m in MONTHS}
        row_vals['TOTAL'] = inc_pivot2.loc[cat, 'TOTAL']
        mrow(f"  {cat}", row_vals)
    print("-" * len(hdr))
    mrow("  TOTAL INCOME", inc_m_totals)

    print()
    # ── EXPENSES ──
    print("  EXPENSES")
    exp_pivot2 = exp_df.pivot_table(index='Cat', columns='Month', values='Withdrawals',
                                     aggfunc='sum', fill_value=0, observed=True)
    exp_pivot2['TOTAL'] = exp_pivot2.sum(axis=1)
    exp_pivot2 = exp_pivot2.sort_values('TOTAL', ascending=False)
    exp_m_totals = {m: exp_df[exp_df['Month']==m]['Withdrawals'].sum() for m in MONTHS}
    exp_m_totals['TOTAL'] = tot_exp
    for cat in exp_pivot2.index:
        row_vals = {m: exp_pivot2.loc[cat, m] if m in exp_pivot2.columns else 0 for m in MONTHS}
        row_vals['TOTAL'] = exp_pivot2.loc[cat, 'TOTAL']
        mrow(f"  {cat}", row_vals)
    print("-" * len(hdr))
    mrow("  TOTAL EXPENSES", exp_m_totals)

    print()
    # ── NET ──
    net_vals = {m: inc_m_totals[m] - exp_m_totals[m] for m in MONTHS}
    net_vals['TOTAL'] = tot_inc - tot_exp
    mrow("  NET PROFIT / (LOSS)", net_vals)
    print("=" * (36 + (W+2)*(len(MONTHS)+1)))
    print(f"  File saved: {OUT}")


if __name__ == "__main__":
    main()
