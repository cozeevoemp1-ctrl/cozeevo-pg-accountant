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
    ("IT & Software",        "Mobile Bill (paybil3066)",     ["paybil3066"]),
    ("IT & Software",        "Mobile Bill (payair7673)",     ["payair7673"]),
    ("IT & Software",        "Office Phone Bill",            ["bill paid - post paid","paid - mobile recharge","recharge of jio mobile"]),

    # ── INTERNET & WIFI ───────────────────────────────────────────────────────
    # Keep Airtel/Jio/Vi as specific merchant strings only — raw "airtel"/"jio" matches
    # Razorpay/PayU payment rails (e.g. *.rzp@rxairtel = Zepto, *.payu@mairtel = Flipkart)
    ("Internet & WiFi",      "Airwire Broadband",            ["airwire"]),
    ("Internet & WiFi",      "Airtel Recharge (Direct)",     ["airtelpredirect"]),
    ("Internet & WiFi",      "WiFi Vendor",                  ["wifi","wi-fi","broadband"]),

    # ── FURNITURE & SUPPLIES — all furniture/equipment from PG bank (2026-05-13: CAPEX folded into OPEX) ─────
    ("Furniture & Supplies", "Wakefit - Mattresses",         ["wakefit"]),
    # Lakshmi SBI direct vendor payments (initial setup — never through THOR/HULK)
    ("Furniture & Supplies", "Griham Decor (Furniture)",         ["griham decor","griham"]),
    ("Furniture & Supplies", "Naveen Kumar (Gym Setup)",         ["naveen kumar"]),
    ("Furniture & Supplies", "Lavanya Ravishankar (Fittings)",   ["lavanya ravishankar","lavanya"]),
    ("Furniture & Supplies", "Kumar UC (Fittings)",              ["kumar.u.c","kumar uc"]),
    ("Furniture & Supplies", "Carpets / Flooring",               ["floors and carpet","carpet"]),
    ("Furniture & Supplies", "Decor Studio (Plants/Decor)",      ["decor studio"]),
    ("Furniture & Supplies", "Plants / Nursery (SBI)",           ["madeena nursery","amartradingco","amar trading"]),
    ("Furniture & Supplies", "Kaizen (Fire Extinguishers)",      ["kaizen"]),
    ("Furniture & Supplies", "Architect Fee",                    ["architect"]),
    ("Marketing",            "Signs & Signages",                 ["signs and signages","signage"]),
    ("Furniture & Supplies", "Bedsheets / Linen",            ["bedsheet","bed sheet"]),
    ("Furniture & Supplies", "Shoe Rack / Rack",             ["shoe rack","rack balance","9108617776"]),
    ("Furniture & Supplies", "Curtains",                     ["curtain"]),
    ("Furniture & Supplies", "Bedframes (Grace Traders)",    ["grace trader","bedframe","bed frame"]),
    ("Furniture & Supplies", "Usha Trading (TV/Equipment)",  ["usha trading","usha t rading"]),
    ("Furniture & Supplies", "Cot Placement / Labour",       ["cot placement","cot place","cot plac","jubair"]),
    ("Furniture & Supplies", "Porter / Delivery",            ["porter fee","porter","bed frames porter"]),
    ("Furniture & Supplies", "Wardrobes",                    ["wardrobe","mahinmeman7705","sungle wardrobe"]),
    ("Furniture & Supplies", "3-Sharing Beds",               ["3 sharing bed","9035767529"]),
    ("Shopping & Supplies",  "Mirrors — Small Purchase",     ["mirrors porte"]),   # volipi.l small buy; before generic mirrors
    ("Furniture & Supplies", "Mirrors",                      ["q411763249","mirrors"]),
    ("Furniture & Supplies", "Mixer (Kitchen)",              ["q566549919"]),
    ("Furniture & Supplies", "Atta Mixing Machine",          ["naveenmanly100100"]),
    ("Furniture & Supplies", "Chairs & Study Tables",        ["q962933392"]),
    ("Furniture & Supplies", "Kitchen Equipment / Vessels",  ["9844532900"]),
    ("Furniture & Supplies", "Wooden Stove / Kitchen Items (shalu.pravi)", ["shalu.pravi"]),
    ("Furniture & Supplies", "Other Furniture / Supplies",   ["furniture","refurbish","3d bo","laughing bud"]),

    # ── FOOD & GROCERIES ──────────────────────────────────────────────────────
    ("Food & Groceries",     "Grocery - Virani Trading",     ["virani"]),
    ("Food & Groceries",     "Food Supplies - Vyapar",       ["vyapar"]),
    ("Food & Groceries",     "Gas Cylinders (DRP Ent.)",     ["cylinder","lpg","drp enterprise","9880707836","gas advance"]),
    ("Food & Groceries",     "Chicken / Meat",               ["chicken","biryani","meat","q858145123","paytmqr6li6zl","paytmqr6wro5d","paytmqr6pxr4","q213610007","q494874704","q457756301","q236290371","q067427224"]),
    ("Food & Groceries",     "Eggs",                         ["eggs","egg trays","9900343230"]),
    ("Food & Groceries",     "Vegetables & Greens",          ["vegetable","veggies","veggie","greens","tomato","chilli","cucumber","lemon","coriander","pudina","paneer","curd","vangi"]),
    ("Food & Groceries",     "Ninjacart (Veg Supplier)",     ["ninjacart","ninja kart","ninjakart","ninja cart","paytm-7102662","paytm-30461933","oidninj"]),
    ("Food & Groceries",     "Zepto / Blinkit / Swiggy",     ["zepto","blinkit","swiggystores","swiggy484","swiggy","instamart","zeptonow"]),
    ("Food & Groceries",     "Amazon Grocery / India",       ["amazon pay groceries","amazon india"]),  # must be before generic amazon→F&S
    ("Food & Groceries",     "WholesaleMandi / Origin",      ["wholesalemandi","wholesale mandi","origin903039","origin108856","paid to origin"]),
    ("Food & Groceries",     "D-Mart / Retail",              ["dmart","d-mart","innovdmart"]),
    ("Food & Groceries",     "Cooking Oil / Masala",         ["oil","ruchi gold","basmati rice","rice"]),
    ("Food & Groceries",     "HP Gas",                       ["hp gas","q947171136"]),
    ("Food & Groceries",     "Drumstick / Fresh Veg",        ["drumstick"]),
    ("Food & Groceries",     "Batter / Idli Mix",            ["batter","idli"]),
    ("Food & Groceries",     "Star Bazaar / Ratnadeep",      ["star bazaar","ratnadeep"]),
    ("Food & Groceries",     "Flowers / Pooja",              ["pooja flower","flowers","flower"]),
    ("Food & Groceries",     "Flipkart Groceries (Paytm)",   ["paytm-56505013"]),
    ("Food & Groceries",     "Vegetables - Jaydev",          ["jaydevjena73"]),
    ("Food & Groceries",     "Vegetables - Shahbaz",         ["shahbaz80508637"]),
    ("Food & Groceries",     "Vegetables (9663049651)",      ["9663049651"]),
    ("Food & Groceries",     "Other Groceries / Provisions", ["grocer","kirana","milk","food","provision"]),

    # ── FUEL & DIESEL ─────────────────────────────────────────────────────────
    ("Fuel & Diesel",        "DG Rent / Generator",          ["sunilgn8834","dg rent"]),
    ("Fuel & Diesel",        "Diesel - deepu.1222",          ["deepu.1222","diesel","litres"]),
    ("Fuel & Diesel",        "Diesel Vendor (9888751222)",   ["9888751222"]),
    ("Fuel & Diesel",        "Diesel Vendor (7411535239)",   ["7411535239"]),
    ("Fuel & Diesel",        "Petrol / Fuel",                ["petrol","fuel"]),
    ("Fuel & Diesel",        "Diesel (8951297583)",           ["8951297583"]),
    ("Fuel & Diesel",        "Bus Tickets (PayBus)",         ["paybus8261"]),
    ("Fuel & Diesel",        "Travel / Bus (Paytm)",         ["travel1paytm","paytm bus: "]),
    ("Fuel & Diesel",        "Petrol / Shell India",         ["shell india"]),
    ("Fuel & Diesel",        "Bus Ticket (Staff Travel)",    ["bus ticket"]),

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
    ("Staff & Labour",       "Salary - Vivek",               ["6202601070","6287677379"]),
    ("Staff & Labour",       "Salary - Bhukesh",             ["bn895975"]),
    ("Staff & Labour",       "Labour / Helpers",             ["helper","labour","kshitij","vivek"]),
    ("Staff & Labour",       "Staff - 9880401360 (Regular)", ["9880401360"]),
    ("Staff & Labour",       "Salary - Prabhakaran",         ["9444296681"]),
    ("Staff & Labour",       "Staff - gudadesh (Contractor)",["gudadesh","udadesh"]),
    ("Staff & Labour",       "Staff - sandeepgowda",         ["sandeepgowda"]),
    ("Staff & Labour",       "Staff - Various UPI",          ["akmalakmal","kutubuddinku","vishal521","sanket","biplab"]),
    ("Staff & Labour",       "Staff Mobile Recharge (Jio)",  ["jioinappdirect"]),
    ("Staff & Labour",       "Staff Mobile Recharge (Vi)",   ["viinappguj"]),
    ("Staff & Labour",       "Labour - Cash Exchange (ESOB Tanti)", ["7993273966"]),
    # volipi.l — ops vendor; specific description overrides must come first
    ("Cleaning Supplies",    "Kastig Soda (volipi.l)",       ["kastig soda"]),          # before generic volipi.l rule
    ("Staff & Labour",       "Staff - volipi.l (Salary)",    ["volipi.l"]),
    # Small person-name payments — Jan/Feb confirmed staff wages by Kiran 2026-05-13
    ("Staff & Labour",       "Staff - Petty Wages",          ["paid to lucky","muni arun k s","venkatachala","mishrilal","annayappa"]),
    ("Staff & Labour",       "Staff Medical",                ["rxdxwhitefield","medical for loki","medicine for loki"]),

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
    ("Marketing",            "Job Posting - Naukri",         ["naukri.qr8"]),
    ("Marketing",            "Marketing / Promotions",       ["marketing","advertisement"]),

    # ── WASTE DISPOSAL ────────────────────────────────────────────────────────
    ("Waste Disposal",       "Pavan (6366411789)",           ["6366411789","garbage collection"]),

    # ── CLEANING & HOUSEKEEPING SUPPLIES ──────────────────────────────────────
    ("Cleaning Supplies",    "Triveni Soap & Oil",           ["9448259556","9989000250","triveni"]),
    ("Cleaning Supplies",    "Garbage Bags / Bins",          ["garbage bag"]),
    ("Cleaning Supplies",    "Phenyl / Disinfectant",        ["phenyl","disinfect","toilet adour","toilet filter","bleaching powder"]),
    ("Cleaning Supplies",    "Mop / Cleaning Tools",         ["mop","broom","knife sharpen"]),
    ("Cleaning Supplies",    "Room Freshener / Hooks",       ["room freshner","freshner","hooks"]),
    ("Cleaning Supplies",    "AdBlue (DG Exhaust Fluid)",    ["adblue","ad blu","as blue"]),
    ("Cleaning Supplies",    "Hinglaj Packaging (Supplies)", ["hinglaj packaging"]),

    # ── SHOPPING & SUPPLIES ───────────────────────────────────────────────────
    # ── FURNITURE & SUPPLIES (continued — Amazon for PG, Elgis gym) ─────────────
    ("Furniture & Supplies", "Elgis Fitness — Gym CAPEX",    ["elgis"]),
    ("Furniture & Supplies", "Amazon (PG Purchases)",        ["amazon"]),             # generic Amazon after F&G override above
    # ── SHOPPING & SUPPLIES ───────────────────────────────────────────────────
    ("Shopping & Supplies",  "Akhil Reddy (PG Setup Purchases)", ["akhilreddy007420"]),
    ("Shopping & Supplies",  "Sansar Centre (Office Supplies)",  ["sansar centre"]),
    ("Shopping & Supplies",  "Ops UPI (7829264915)",         ["7829264915"]),
    ("Shopping & Supplies",  "Ops UPI (Q531)",               ["q531107921"]),
    ("Shopping & Supplies",  "Ops UPI (9902278720)",         ["9902278720"]),
    ("Shopping & Supplies",  "Ops UPI (SV2512)",             ["sv2512112238"]),
    ("Shopping & Supplies",  "Paytm Autopay (Ops)",          ["paytm-64646105"]),
    ("Shopping & Supplies",  "ME Services",                  ["me services"]),
    ("Shopping & Supplies",  "Global Enterprises",           ["global enterprises"]),
    ("Shopping & Supplies",  "Nursery / Plants (Ops Decor)", ["madhu — nursery"]),
    ("Shopping & Supplies",  "Chandrasekhar PG Expense",     ["chandrasekhar — pg expenses","chandrasekhar — 1 lakh"]),
    ("Shopping & Supplies",  "Paytm QR Merchant",            ["paytmqr2810050501"]),
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
    ("Maintenance & Repairs","Key Maker (9148809732)",        ["9148809732"]),
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
