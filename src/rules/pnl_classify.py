"""
src/rules/pnl_classify.py
──────────────────────────
Cozeevo-specific P&L classification rules.
Extracted from scripts/pnl_report.py so both the script and the
WhatsApp finance_handler can share the same vendor/keyword rules.

Usage:
    from src.rules.pnl_classify import classify_txn

    cat, sub = classify_txn("Virani Trading", "expense")  # → ("Food & Groceries", "Grocery - Virani Trading")
"""
from __future__ import annotations

# ── EXPENSE rules ─────────────────────────────────────────────────────────────
# Format: (Category, Sub-category, [keywords…])  — first keyword match wins.
# Empty keywords list = catch-all (used as last rule in the list).

EXPENSE_RULES: list[tuple[str, str, list[str]]] = [
    # ── CAPITAL INVESTMENT — must be FIRST so CCTV cheque doesn't land in Misc ──
    ("Capital Investment",   "CCTV Installation",            ["chq w/l_kiran kumar pemma","cctv install","cctv"]),

    # ── NON-OPERATING — must be FIRST so loan names don't match other rules ──
    # Description-based overrides: the SAME person can receive rent OR a loan;
    # trust the memo keyword. These run BEFORE the landlord-name matches below.
    ("Non-Operating",        "Cash Borrow / Exchange",       ["money exchange","cash borrow","cash borrows","money borrow"]),
    ("Non-Operating",        "Advance / Loan to Staff",      ["/borrow"]),
    ("Non-Operating",        "Trial / Test Payment",         ["trial","yespay.ypbsm","yespay.bizsbiz"]),
    ("Non-Operating",        "Self Transfer",                ["from:7358341775-2@ybl/to:7358341775@ybl"]),
    ("Non-Operating",        "Repayment",                    ["repaymen","repayment","loan repay"]),
    ("Non-Operating",        "Borrowed From",                ["borrowed f","borrowed from"]),
    ("Non-Operating",        "Loan Repayment (Bharathi)",    ["bharathi prabhakaran"]),
    ("Non-Operating",        "Unknown Transfer (shalu)",     ["shalu.pravi"]),

    # ── PROPERTY RENT ─────────────────────────────────────────────────────────
    ("Property Rent",        "Vakkal Sravani",               ["vakkal", "sravani"]),
    ("Property Rent",        "R Suma",                       ["r suma", "rsuma"]),
    ("Property Rent",        "Raghu Nandha Mandadi",         ["raghu nandha"]),
    ("Property Rent",        "Sri Lakshmi Chandrasekhar",    ["lakshmi chandrasekhar","lakshmi chandrasekar"]),
    ("Property Rent",        "Other Rent Payments",          ["jan rent","feb rent","mar rent","rent pay"]),

    # ── ELECTRICITY ───────────────────────────────────────────────────────────
    ("Electricity",          "BESCOM Bill",                  ["bescom","besco","eb bill","eb payment"," eb "]),

    # ── WATER ─────────────────────────────────────────────────────────────────
    ("Water",                "BWSSB (Govt Supply)",          ["bwssb","bwssb bill","bwssb payment"]),
    ("Water",                "Water Tanker",                 ["water tanker","tanker","water lorry","water supply","water vendor"]),
    ("Water",                "Water Bill / Charges",         ["water bill","water charge","water tax"]),
    ("Water",                "Water Barrels / Drums",        ["barrels","water barrel","water drum"]),
    # Manoj B — UPI 9535665407@ybl. Paid monthly, cycle = one month behind
    # (April payment = March bill). Confirmed vendor by Kiran 2026-04-22.
    ("Water",                "Manoj B (Water Vendor)",       ["manojb","9535665407","manoj b","manoj bharath"]),

    # ── IT & SOFTWARE ─────────────────────────────────────────────────────────
    ("IT & Software",        "Hostinger (VPS Hosting)",      ["hostinger","hostingerpteltd"]),
    ("IT & Software",        "Think Straight (Software)",    ["think straight","thinkstraight"]),
    ("IT & Software",        "KIPINN (Software/ISP)",        ["kipinn","kipnn","kipi nn","kipin"]),

    # ── INTERNET & WIFI ───────────────────────────────────────────────────────
    # Keep Airtel/Jio/Vi as specific merchant strings only — raw "airtel"/"jio" matches
    # Razorpay/PayU payment rails (e.g. *.rzp@rxairtel = Zepto, *.payu@mairtel = Flipkart)
    ("Internet & WiFi",      "Airwire Broadband",            ["airwire"]),
    ("Internet & WiFi",      "Airtel Recharge (Direct)",     ["airtelpredirect"]),
    ("Internet & WiFi",      "WiFi Vendor",                  ["wifi","wi-fi","broadband"]),

    # ── FURNITURE & FITTINGS ──────────────────────────────────────────────────
    ("Furniture & Fittings", "Wakefit - Mattresses",         ["wakefit"]),
    # Lakshmi SBI direct vendor payments (initial setup — never through THOR/HULK)
    ("Furniture & Fittings", "Griham Decor (Furniture)",         ["griham decor","griham"]),
    ("Furniture & Fittings", "Naveen Kumar (Gym Setup)",         ["naveen kumar"]),
    ("Furniture & Fittings", "Lavanya Ravishankar (Fittings)",   ["lavanya ravishankar","lavanya"]),
    ("Furniture & Fittings", "Kumar UC (Fittings)",              ["kumar.u.c","kumar uc"]),
    ("Furniture & Fittings", "Carpets / Flooring",               ["floors and carpet","carpet"]),
    ("Furniture & Fittings", "Decor Studio (Plants/Decor)",      ["decor studio"]),
    ("Furniture & Fittings", "Plants / Nursery (SBI)",           ["madeena nursery","amartradingco","amar trading"]),
    ("Furniture & Fittings", "Kaizen (Fire Extinguishers)",      ["kaizen"]),
    ("Furniture & Fittings", "Architect Fee",                    ["architect"]),
    ("Marketing",            "Signs & Signages",                 ["signs and signages","signage"]),
    ("Furniture & Fittings", "Bedsheets / Linen",            ["bedsheet","bed sheet"]),
    ("Furniture & Fittings", "Shoe Rack / Rack",             ["shoe rack","rack balance","9108617776"]),
    ("Furniture & Fittings", "Curtains",                     ["curtain"]),
    ("Furniture & Fittings", "Bedframes (Grace Traders)",    ["grace trader","bedframe","bed frame"]),
    ("Furniture & Fittings", "Usha Trading (TV/Equipment)",  ["usha trading","usha t rading"]),
    ("Furniture & Fittings", "Cot Placement / Labour",       ["cot placement","cot place","cot plac","jubair"]),
    ("Furniture & Fittings", "Porter / Delivery",            ["porter fee","porter","bed frames porter"]),
    ("Furniture & Fittings", "Wardrobes",                    ["wardrobe","mahinmeman7705","sungle wardrobe"]),
    ("Furniture & Fittings", "3-Sharing Beds",               ["3 sharing bed","9035767529"]),
    ("Furniture & Fittings", "Mirrors",                      ["q411763249","mirrors"]),
    ("Furniture & Fittings", "Mixer (Kitchen)",              ["q566549919"]),
    ("Furniture & Fittings", "Other Furniture / Fittings",   ["furniture","refurbish","3d bo","laughing bud"]),

    # ── FOOD & GROCERIES ──────────────────────────────────────────────────────
    ("Food & Groceries",     "Grocery - Virani Trading",     ["virani"]),
    ("Food & Groceries",     "Food Supplies - Vyapar",       ["vyapar"]),
    ("Food & Groceries",     "Gas Cylinders (DRP Ent.)",     ["cylinder","lpg","drp enterprise","9880707836","gas advance"]),
    ("Food & Groceries",     "Chicken / Meat",               ["chicken","biryani","meat","q858145123","paytmqr6li6zl","paytmqr6wro5d","paytmqr6pxr4","q213610007","q494874704","q457756301","q236290371","q067427224"]),
    ("Food & Groceries",     "Eggs",                         ["eggs","egg trays","9900343230"]),
    ("Food & Groceries",     "Vegetables & Greens",          ["vegetable","veggies","veggie","greens","tomato","chilli","cucumber","lemon","coriander","pudina","paneer","curd","vangi"]),
    ("Food & Groceries",     "Ninjacart (Veg Supplier)",     ["ninjacart","ninja kart","ninjakart","ninja cart","paytm-7102662","paytm-30461933","oidninj"]),
    ("Food & Groceries",     "Zepto / Blinkit / Swiggy",     ["zepto","blinkit","swiggystores","swiggy484","swiggy","instamart","zeptonow"]),
    ("Food & Groceries",     "WholesaleMandi / Origin",      ["wholesalemandi","wholesale mandi","origin903039","origin108856"]),
    ("Food & Groceries",     "D-Mart / Retail",              ["dmart","d-mart","innovdmart"]),
    ("Food & Groceries",     "Cooking Oil / Masala",         ["oil","ruchi gold","basmati rice","rice"]),
    ("Food & Groceries",     "HP Gas",                       ["hp gas","q947171136"]),
    ("Food & Groceries",     "Drumstick / Fresh Veg",        ["drumstick"]),
    ("Food & Groceries",     "Batter / Idli Mix",            ["batter","idli"]),
    ("Food & Groceries",     "Star Bazaar / Ratnadeep",      ["star bazaar","ratnadeep"]),
    ("Food & Groceries",     "Flowers / Pooja",              ["pooja flower","flowers","flower"]),
    ("Food & Groceries",     "Other Groceries / Provisions", ["grocer","kirana","milk","food","provision"]),

    # ── FUEL & DIESEL ─────────────────────────────────────────────────────────
    ("Fuel & Diesel",        "DG Rent / Generator",          ["sunilgn8834","dg rent"]),
    ("Fuel & Diesel",        "Diesel - deepu.1222",          ["deepu.1222","diesel","litres"]),
    ("Fuel & Diesel",        "Diesel Vendor (9888751222)",   ["9888751222"]),
    ("Fuel & Diesel",        "Diesel Vendor (7411535239)",   ["7411535239"]),
    ("Fuel & Diesel",        "Petrol / Fuel",                ["petrol","fuel"]),
    ("Fuel & Diesel",        "Bus Tickets (PayBus)",         ["paybus8261"]),
    ("Fuel & Diesel",        "Travel / Bus (Paytm)",         ["travel1paytm","paytm bus: "]),

    # ── STAFF & LABOUR ────────────────────────────────────────────────────────
    ("Staff & Labour",       "Salary - Arjun (NEFT)",        ["joshi arjun","yesob6021"]),
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
    ("Staff & Labour",       "Cleaners Advance",             ["cleaners advance","cleaner advance","8787621802"]),
    ("Staff & Labour",       "WorkIndia (Recruitment)",      ["workindia","work india"]),
    ("Staff & Labour",       "Staff - kn.ravikumar",         ["kn.ravikumar","ravikumar80"]),
    ("Staff & Labour",       "Staff - sachindivya",          ["sachindivya"]),
    ("Staff & Labour",       "Housekeeping / Cleaning Staff",["housekeep","salamtajamul","sarojrout","dilliprout","swamisarang","manisha","9398545495","9611622637","9071242117","8837062479","imranaaazmi58","rabhasoma4"]),
    ("Staff & Labour",       "Urban Company (Cleaning Svc)", ["urbancompany","urban company"]),
    ("Staff & Labour",       "Labour / Helpers",             ["helper","labour","kshitij","vivek"]),
    ("Staff & Labour",       "Staff - 9880401360 (Regular)", ["9880401360"]),
    ("Staff & Labour",       "Salary - Prabhakaran",         ["9444296681"]),
    ("Staff & Labour",       "Staff - gudadesh (Contractor)",["gudadesh","udadesh"]),
    ("Staff & Labour",       "Staff - sandeepgowda",         ["sandeepgowda"]),
    ("Staff & Labour",       "Staff - Various UPI",          ["akmalakmal","kutubuddinku","vishal521","sanket","biplab"]),
    ("Staff & Labour",       "Staff Mobile Recharge (Jio)",  ["jioinappdirect"]),
    ("Staff & Labour",       "Staff Mobile Recharge (Vi)",   ["viinappguj"]),
    ("Staff & Labour",       "Labour - Cash Exchange (ESOB Tanti)", ["7993273966"]),

    # ── GOVT & REGULATORY ─────────────────────────────────────────────────────
    ("Govt & Regulatory",    "BBMP Tax / Property Bill",     ["bbmp","bbpsbp"]),
    ("Govt & Regulatory",    "Directorate / Reg Fees",       ["edcs","directorate"]),
    ("Govt & Regulatory",    "GST Charges",                  ["sdb_gst","gst"]),
    ("Govt & Regulatory",    "Police / Station",             ["police"]),

    # ── TENANT DEPOSIT REFUND ─────────────────────────────────────────────────
    ("Tenant Deposit Refund","Booking Cancellation Refund",  ["booking cancellation"]),
    ("Tenant Deposit Refund","Refund - Chandrasekhar",       ["chandrasekhar1996krish"]),
    ("Tenant Deposit Refund","Refund - Amal",                ["amalsreenimj"]),
    ("Tenant Deposit Refund","Refund - Adithya",             ["adithya3sri"]),
    ("Tenant Deposit Refund","Refund - Kuhan Mohan",         ["kuhanmohan123"]),
    ("Tenant Deposit Refund","Refund - T Srinivasa",         ["t.srinivasa34"]),
    ("Tenant Deposit Refund","Refund - Swami Venkatesh",     ["swamivenkatesh264"]),
    ("Tenant Deposit Refund","Refund - K S Shyam Reddy",     ["ksshyamreddy"]),
    ("Tenant Deposit Refund","Refund - Siva Kumar",          ["7842266579"]),
    ("Tenant Deposit Refund","Refund - Shaurya Shah",        ["9099913969"]),
    ("Tenant Deposit Refund","Refund - Mohammed Umar",       ["umar1256"]),
    ("Tenant Deposit Refund","Refund - Vijay Kumar",         ["9390933531"]),
    ("Tenant Deposit Refund","Refund - Shubhi Vishnoi",     ["6391679333"]),
    ("Tenant Deposit Refund","Refund - Bharath (cancelled)", ["6379442910"]),
    ("Tenant Deposit Refund","Refund - Shashank B V",       ["9482874334"]),
    ("Tenant Deposit Refund","Other Refund / Exit",          ["refund","exit refund","checkout refund","rishwanth refund","hafiz refund","gotham refund","lakshmi priya refund"]),

    # ── MARKETING ─────────────────────────────────────────────────────────────
    ("Marketing",            "Logo T-shirts",                ["logo tshirt","logo t-shirt","tshirt"]),
    ("Marketing",            "Ad Board / Sun Boards",        ["9845068141","sun board","sunboard"]),
    ("Marketing",            "Flyers / Banners",             ["flyers","flyer","banner","flags"]),
    ("Marketing",            "FindMyPG Listing",             ["find my pg","findmypg"]),
    ("Marketing",            "Marketing / Promotions",       ["marketing","advertisement"]),

    # ── WASTE DISPOSAL ────────────────────────────────────────────────────────
    ("Waste Disposal",       "Pavan (6366411789)",           ["6366411789","garbage collection"]),

    # ── CLEANING & HOUSEKEEPING SUPPLIES ──────────────────────────────────────
    ("Cleaning Supplies",    "Garbage Bags / Bins",          ["garbage bag"]),
    ("Cleaning Supplies",    "Phenyl / Disinfectant",        ["phenyl","disinfect","toilet adour","toilet filter","bleaching powder"]),
    ("Cleaning Supplies",    "Mop / Cleaning Tools",         ["mop","broom","knife sharpen"]),
    ("Cleaning Supplies",    "Room Freshener / Hooks",       ["room freshner","freshner","hooks"]),
    ("Cleaning Supplies",    "AdBlue (DG Exhaust Fluid)",    ["adblue","ad blu","as blue"]),

    # ── SHOPPING & SUPPLIES ───────────────────────────────────────────────────
    ("Furniture & Fittings", "Elgis Fitness — Gym CAPEX",     ["elgis"]),
    # Amazon goes to Operational Expenses per Kiran's rule
    ("Operational Expenses", "Amazon",                       ["amazon"]),
    ("Operational Expenses", "Job Posting - Naukri",         ["naukri.qr8"]),
    ("Operational Expenses", "Atta Mixing Machine",          ["naveenmanly100100"]),
    ("Operational Expenses", "Chairs & Study Tables",        ["q962933392"]),
    ("Operational Expenses", "Kitchen Equipment",            ["9844532900"]),
    ("Operational Expenses", "Misc - akhilreddy007420",      ["akhilreddy007420"]),
    ("Operational Expenses", "Volipi - Ops Vendor",          ["volipi.l"]),
    ("Operational Expenses", "Staff Medical",                ["rxdxwhitefield","medical for loki","medicine for loki"]),
    ("Operational Expenses", "Staff Mobile / Recharge",      ["recharge of jio mobile","recharge of airtel mobile","bill paid - post paid","paid - mobile recharge","hinglaj packaging","shell india markets"]),
    ("Operational Expenses", "Nursery / Plants",             ["nursery","madeena nursery","madhu — nursery"]),
    ("Shopping & Supplies",  "Myntra",                       ["paytm-950206","myntra order"]),
    ("Shopping & Supplies",  "Flipkart",                     ["flipkart"]),
    ("Shopping & Supplies",  "BharatPE (POS Payments)",      ["bharatpe","bharat pe"]),
    ("Shopping & Supplies",  "Pine Labs (POS Terminal)",     ["pinelab","pi nelabs"]),
    ("Shopping & Supplies",  "Rapido (Transport)",           ["rapido"]),
    ("Shopping & Supplies",  "Mosquito / Pest Supplies",     ["mosquito","pest"]),
    ("Shopping & Supplies",  "Hardware / Granite",           ["hardware","granite"]),
    ("Shopping & Supplies",  "Printing / Xerox",             ["printout","xerox","print"]),

    # ── MAINTENANCE & REPAIRS ─────────────────────────────────────────────────
    ("Maintenance & Repairs","Plumbing",                     ["plumbing","plumber","chandan865858","kumar.ranjan7828"]),
    ("Maintenance & Repairs","Electrician / Electrical",     ["electrician","electrical","electric"]),
    ("Maintenance & Repairs","EB Panel Board - Basavaraju",  ["bn.basavaraju"]),
    ("Maintenance & Repairs","Carpenter",                    ["carpenter","r61865951"]),
    ("Maintenance & Repairs","Repairs / Handyman",           ["repair","handyman"]),
    ("Maintenance & Repairs","Key Duplicate / Locks",        ["/keys","key duplicate","locksmith","seals"]),
    ("Maintenance & Repairs","Fridge Delivery / Appliance",  ["fridge delivery","fridge"]),
    ("Maintenance & Repairs","General Maintenance",          ["maintenance","maintain"]),

    # ── BANK CHARGES ──────────────────────────────────────────────────────────
    ("Bank Charges",         "Debit Card Fee",               ["debit card replacement","card replace"]),
    ("Bank Charges",         "Bank Transfer / IMPS / NEFT",  ["imps","rtgs","neft","yib-neft","net-neft"]),

    # ── NON-OPERATING (defined at top of file now) ────────────────────────────

    # ── UNCLASSIFIED (catch-all) ───────────────────────────────────────────────
    ("Other Expenses",       "Misc UPI Payments",            []),
]

# ── INCOME rules ──────────────────────────────────────────────────────────────
INCOME_RULES: list[tuple[str, str, list[str]]] = [
    ("Rent Income",     "UPI Collection Settlement",  ["upi collection settlement","115063600001082"]),
    ("Rent Income",     "Direct UPI from Tenants",    ["upi/"]),
    ("Other Income",    "NEFT / RTGS Inward",         ["neft","rtgs","imps"]),
    ("Other Income",    "Cashback / Refund",          ["refund","cashback","reversal"]),
    # Possible advance / security deposit payments
    ("Advance Deposit", "Security Deposit Received",  ["advance","deposit","security"]),
    ("Other Income",    "Other Inward",               []),
]


def classify_txn(description: str, txn_type: str) -> tuple[str, str]:
    """
    Classify one transaction.

    Args:
        description: raw description / narration string
        txn_type:    "income" or "expense"

    Returns:
        (category, sub_category) tuple
    """
    rules = INCOME_RULES if txn_type == "income" else EXPENSE_RULES
    d = (description or "").lower()
    for cat, sub, keywords in rules:
        if not keywords:
            # catch-all — return this if nothing else matched
            return cat, sub
        for kw in keywords:
            if kw in d:
                return cat, sub
    # Shouldn't reach here — every rule list ends with empty-keywords catch-all
    return ("Other Income" if txn_type == "income" else "Other Expenses"), ""
