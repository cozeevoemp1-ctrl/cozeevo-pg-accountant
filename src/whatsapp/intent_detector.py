"""
Intent detection for WhatsApp messages.
Rules-first: 97% of messages classified without AI.
AI fallback only for ambiguous owner commands.

Intent taxonomy by role:
  ADMIN / POWER_USER:
    PAYMENT_LOG       "Raj paid 15000", "received 8k from room 203"
    QUERY_DUES        "who hasn't paid", "pending this month", "dues"
    QUERY_TENANT      "Raj balance", "room 203 details"
    ADD_TENANT        "add tenant", "new checkin", "joining"
    CHECKOUT          "checkout Raj", "Raj leaving", "vacate room 3"
    ADD_EXPENSE       "electricity 4500", "paid salary 12000"
    REPORT            "monthly report", "summary", "P&L"
    ADD_PARTNER       "add partner +91...", "add power user"
    REMINDER_SET      "remind Raj tomorrow", "set reminder"
    HELP              "help", "menu", "commands"

  TENANT (read-only):
    MY_BALANCE        "my balance", "how much do I owe", "dues"
    MY_PAYMENTS       "my payments", "payment history", "receipt"
    MY_DETAILS        "my room", "my details", "checkin date"
    HELP              "help", "hi", "hello"

  LEAD (room enquiry):
    ROOM_PRICE        "price", "rent", "cost", "how much", "rates"
    AVAILABILITY      "available", "vacancy", "empty room"
    ROOM_TYPE         "single", "double", "sharing", "private"
    VISIT_REQUEST     "visit", "tour", "come see", "show room"
    GENERAL           everything else → natural conversation
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ── Learned-rules file cache ──────────────────────────────────────────────────
# Written by the !learn command; read here without touching the DB.
_LEARNED_RULES_FILE = Path(__file__).parent.parent.parent / "data" / "learned_rules.json"
_learned_cache: list[tuple[re.Pattern, str, float, str]] = []  # (pattern, intent, conf, applies_to)
_learned_mtime: float = 0.0


def _load_learned_rules() -> list[tuple[re.Pattern, str, float, str]]:
    """Return compiled learned rules, refreshing from disk when the file changes."""
    global _learned_cache, _learned_mtime
    try:
        mtime = _LEARNED_RULES_FILE.stat().st_mtime
        if mtime == _learned_mtime:
            return _learned_cache
        rows = json.loads(_LEARNED_RULES_FILE.read_text(encoding="utf-8"))
        _learned_cache = [
            (re.compile(r["pattern"], re.I), r["intent"], float(r["confidence"]), r.get("applies_to", "all"))
            for r in rows
            if r.get("active", True) and r.get("pattern") and r.get("intent")
        ]
        _learned_mtime = mtime
    except (FileNotFoundError, json.JSONDecodeError, KeyError, OSError):
        _learned_cache = []
    return _learned_cache


@dataclass
class IntentResult:
    intent:       str
    confidence:   float
    entities:     dict       = field(default_factory=dict)   # e.g. {name, amount, room, month}
    alternatives: list[str]  = field(default_factory=list)   # set when intent == "AMBIGUOUS"


# ── Owner / Power-user intents ────────────────────────────────────────────────

_OWNER_RULES: list[tuple[re.Pattern, str, float]] = [
    # Start onboarding / KYC for a new tenant (must be first — very specific)
    (re.compile(r"(?:start onboarding|begin onboarding|start kyc|begin kyc|start checkin|begin checkin|onboard\s+\w+|kyc for|checkin for\s+\w+|onboarding\s+for\s+\w+|start\s+registration|registration\s+(?:for|of)\s+\w+)", re.I), "START_ONBOARDING", 0.96),
    # Record checkout / offboarding form
    (re.compile(r"(?:record checkout|offboard|checkout form|fill checkout|checkout record|handover|keys? (?:returned?|handed?)|mark checkout complete|complete checkout|process checkout|do checkout|finalize checkout|close checkout|checkout process for|start checkout for|begin checkout|checkout\s+process\s+\w+|do\s+\w+\s+checkout|\w+\s+ka\s+checkout|checkout\s+karo|chekout\s+\w+)", re.I), "RECORD_CHECKOUT", 0.95),
    # Void / reverse payment
    (re.compile(r"(?:void|cancel|reverse|undo payment|mark void|failed payment|payment failed|wrong payment|duplicate payment)", re.I), "VOID_PAYMENT", 0.93),
    # Void / reverse expense
    (re.compile(r"(?:void expense|cancel expense|reverse expense|undo expense|wrong expense|delete expense|remove expense|expense (?:void|cancel|wrong|mistake|error))", re.I), "VOID_EXPENSE", 0.93),
    # Room transfer — move tenant from one room to another
    (re.compile(r"(?:move|shift|transfer|relocate|change room for|room change for|room\s+(?:transfer|change|shift|move))\s+\w+.{0,30}(?:to|into)\s+(?:room\s+)?[\w-]+|(?:move|shift|transfer)\s+(?:room\s+)?[\w-]+\s+to\s+(?:room\s+)?[\w-]+|\w+\s+(?:ko\s+)?(?:room\s+)?[\w-]+\s+(?:mein|me)\s+(?:move|shift|transfer)\s+karo?", re.I), "ROOM_TRANSFER", 0.93),
    # Deposit change
    (re.compile(r"(?:change|update|set|modify|correct)\s+deposit|deposit\s+(?:change|update|correction|set|for\s+\w+\s+is|\w+\s+\d{3,})|(?:increase|decrease|hike|reduce)\s+deposit", re.I), "DEPOSIT_CHANGE", 0.91),
    # Send reminder to ALL tenants
    (re.compile(r"(?:send reminder(?:s)? to all|send\s+(?:rent\s+|dues?\s+)?reminders?(?:\s+to\s+all)?$|send\s+all\s+reminders?|remind all|remind everyone|blast reminder|mass reminder|send dues reminder|nudge all|sabko reminder|sabko\s+(?:bhejo|send)|sabko\s+\S+.*?reminder|bulk reminder|remind all tenants?)", re.I), "SEND_REMINDER_ALL", 0.95),
    # ADD_REFUND with amount (has a number → action, not query) — MUST come before QUERY_REFUNDS
    (re.compile(r"(?:add\s+refund|return\s+deposit|give\s+back\s+deposit|deposit\s+(?:back|refund)|repay\s+deposit|disburse\s+deposit|pay\s*back\s+deposit|deposit\s+wapas|wapas\s+karo\b).*\d", re.I), "ADD_REFUND", 0.93),
    (re.compile(r"(?:refund|deposit\s+refund)\s+\w+\s+\d|refund\s+\d[\d,k]+\s+(?:to|for)\s+\w+|\w+\s+deposit\s+refund\s+\d", re.I), "ADD_REFUND", 0.93),
    # Query refunds (MUST come after amount-bearing ADD_REFUND patterns above)
    (re.compile(r"(?:pending refunds?|refunds? due|who needs? refund|deposits? to return|list (?:all )?refunds?|show refunds?|refund history|refund summary|refund status|refunds? this|refunds? for\s+\w+|all refunds?|\w+\s+refunds?)", re.I), "QUERY_REFUNDS", 0.91),
    # Refund / deposit return (generic — matches after QUERY_REFUNDS above)
    (re.compile(r"(?:refund|return deposit|give back deposit|deposit back|repay deposit|disburse deposit|pay\s*back\s+deposit|deposit\s+wapas|wapas\s+karo\b)", re.I), "ADD_REFUND", 0.92),
    # Floor plan / room layout — "thor floor plan", "hulk layout", "room diagram"
    (re.compile(r"(?:floor\s*plan|room\s*layout|room\s*diagram|block\s*layout|layout\s*of\s*(?:thor|hulk)|(?:thor|hulk)\s*(?:layout|diagram|floors?|rooms?|beds?)|beds?\s*per\s*floor|rooms?\s*per\s*floor|show\s*(?:me\s*)?(?:all\s*)?(?:thor|hulk|block)\s*rooms?)", re.I), "ROOM_LAYOUT", 0.95),
    # Activity query — "activity today", "show activity", "activity log today", "activity this week"
    (re.compile(r"(?:activity\s+(?:log\s+)?(?:today|yesterday|this\s+week|last\s+\d+\s+days?|room\s+[\w-]+)|show\s+activit(?:y|ies)|activit(?:y|ies)\s+(?:today|yesterday|this\s+week|log)|^activit(?:y|ies)$|^activity\s+log$)", re.I), "QUERY_ACTIVITY", 0.94),
    # Activity log — "log ...", "note ...", "log received ...", "log delivered ...", bare "log"
    (re.compile(r"(?:^log\s*$|^log\s+\S|^note\s+\S|^activity\s+log\s+\S|^logged?\s+(?:received|delivered|got|bought|purchased|fixed|repaired|plumber|electrician|water|generator)|^received\s+\d+\s+\w+|^delivered\s+\d+\s+\w+)", re.I), "ACTIVITY_LOG", 0.93),
    # Room status — who's in / status of a specific room (incl bare "room 205" and "room X details")
    (re.compile(r"(?:who(?:'?s| is)(?: living| staying)? in room|room\s+[\w-]+\s+(?:who|occupant|tenant|person|status|details?)|who (?:lives?|stays?|is living|is staying) in|status\s+of\s+room\s+[\w-]+|is\s+room\s+[\w-]+\s+(?:occupied|free|vacant|empty|available)|room\s+[\w-]+\s+occupied|^room\s+[\d\w-]+\s*$)", re.I), "ROOM_STATUS", 0.94),
    # Vacant rooms
    (re.compile(r"(?:vacant rooms?|vacnt\s+rooms?|vacent\s+rooms?|empty rooms?|available rooms?|which rooms? (?:are |is )?(?:empty|free|vacant|available)|free rooms?|unoccupied|vacancy\b|khali\s+(?:rooms?|kamre)|rooms?\s+(?:empty|free|vacant|available)\b|how\s+many\s+rooms?\s+(?:are\s+)?empty|\bany\s+(?:vacant\s+|free\s+|empty\s+)?rooms?\b|kaun\s+se\s+rooms?\s+(?:khali|free))", re.I), "QUERY_VACANT_ROOMS", 0.94),
    # Occupancy overview
    (re.compile(r"(?:occu?pa?ncy(?!\s+report)|ocupancy|how full|how many (?:rooms|tenants?)|total rooms|occupied rooms|capacity|fill(?:ed)? (?:rooms?|up)|kitne\s+(?:log|tenants?)\b|rooms?\s+occupied\b)", re.I), "QUERY_OCCUPANCY", 0.91),
    # Early UPDATE_CHECKIN — "Name checkin Month Day" pattern (must be before QUERY_CHECKINS & SCHEDULE_CHECKOUT)
    (re.compile(r"\b[A-Za-z]+\s+check.?in\s+(?:was\s+)?(?:on\s+)?(?:\d|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec))", re.I), "UPDATE_CHECKIN", 0.94),
    # Expiring tenancies / upcoming checkouts
    (re.compile(r"(?:expir(?:ing|es?)|agreements? ending|who(?:'s| is) (?:leaving|vacating) (?:this|next) month|upcoming checkout|checkouts? (?:this|next) month|notice (?:this|next) month|end of (?:lease|stay|tenancy)|who\s+is\s+vacating|tenants?\s+leaving|end\s+of\s+(?:the\s+)?month\s+checkout|checkouts?\s+coming\s+up|expiring\s+tenancies|who\s+is\s+leaving\b|is\s+mahine\s+kaun\s+ja\s+raha)", re.I), "QUERY_EXPIRING", 0.92),
    # Checkins this month
    (re.compile(r"(?:who checked? ?in|new arrivals?|new tenants? (?:this|in|for)|new joinings?|checkins? (?:this|for) month|joined (?:this|recently)|recent checkins?|who joined|recent\s+admissions?|checkins?\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)|is\s+mahine\s+kaun\s+aaya|kaun\s+aaya\s+(?:is|this)\s+mahine)", re.I), "QUERY_CHECKINS", 0.91),
    # Checkouts this month
    (re.compile(r"(?:who checked? ?out|checkouts? this month|who left|who vacated|exits? this month|move(?:d)? out this month|recent checkouts?|who left recently|checkouts?\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s+mein\s+kaun\s+gaya|March\s+mein\s+kaun\s+gaya)", re.I), "QUERY_CHECKOUTS", 0.91),
    # Expense query (before ADD_EXPENSE so "what did we spend" goes here)
    (re.compile(r"(?:what did we spend|expense report|total expenses?|expneses?\b|expenes?\b|expenses? (?:for|in|this|last|summary|breakdown|detail)|how much (?:spent|spend|expense)|list expenses?|show expenses?|monthly expenses?|expense\s+(?:summary|breakdown|analysis)|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+expenses?|expenses?\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec))", re.I), "QUERY_EXPENSES", 0.91),
    # QUERY_DUES — who hasn't paid (specific: must come before REPORT catches "report" at end of message)
    (re.compile(r"(?:who\s+(?:hasn.?t|haven.?t|has\s+not|have\s+not)\s+p[ai]{1,2}d?|which\s+tenants?\s+(?:hasn.?t|haven.?t|has\s+not|have\s+not)\s+paid|(?:have|has)\s+not\s+paid\s+(?:their|the|this|rent)|who\s+owes?\b|pending\s+(?:dues|rent|payments?)\s+(?:this|last)\s+month|dues\s+this\s+month|defaulters?\b|list\s+of\s+defaulters?)", re.I), "QUERY_DUES", 0.92),
    # QUERY_CONTACTS — vendor/supplier/service contact lookup
    (re.compile(r"(?:(?:give|get|show|find|list|who\s+is)\s+(?:me\s+)?(?:the\s+)?(?:our\s+)?(?:plumber|electrician|carpenter|painter|vendor|supplier|contact|wifi|internet|gas|diesel|cleaner|housekeep|manpower|security|cctv|lift|water\s+tank|furniture|chair|mattress|gym|signage|plant)s?\b|(?:plumber|electrician|carpenter|painter|vendor|supplier|wifi|internet|gas|diesel|cleaner|housekeep|manpower|security|cctv|lift|water\s+tank|furniture|chair|mattress|gym|signage|plant)s?\s+(?:contact|number|phone|details?|vendor|guy)\b|(?:all|list|show)\s+(?:contacts?|vendors?|suppliers?)\b|vendor\s+(?:list|directory|contacts?)|contacts?\s+(?:list|for|of)\b|who\s+(?:do|did)\s+we\s+(?:call|use)\s+for\s+\w+|who\s+is\s+(?:the|our)\s+\w+\s+(?:vendor|supplier|guy|contact)|\w+\s+(?:number|contact|phone)\s*$)", re.I), "QUERY_CONTACTS", 0.93),
    # Log vacation / absence for tenant (any name, not hardcoded)
    (re.compile(r"(?:\w+\s+(?:on vacation|going home|on leave|absent|away|out of station|on holiday|chutti)|log vacation|\w+\s+vacation\s+(?:from|for|\d)|going home for|on leave from|will be away|out of station|vacation\s+(?:for\s+)?\d+\s+days?|chutti\s+(?:pe|par|\d+)|din\s+ke\s+liye\s+(?:bahar|ghar)|ghar\s+(?:gaya|gayi|gaye)\b|\w+\s+\d+\s+din\s+bahar\b|\w+\s+not\s+here\b|chutti\s+pe\s+(?:hai|hain|ho)\b|chutti\s+\w+\s+\d+\s+din\b)", re.I), "LOG_VACATION", 0.89),
    # Bank deposit matching — MUST come before REPORT/P&L catches
    (re.compile(r"(?:match\s+deposits?|deposit\s+match|check\s+deposits?|identify\s+deposits?|which\s+deposits?|tenant\s+deposits?\s+(?:in\s+bank|matched|verify)|deposit\s+identification|bank\s+deposits?\s+match)", re.I), "BANK_DEPOSIT_MATCH", 0.94),
    # Bank statement P&L report — MUST come before generic REPORT catch
    (re.compile(r"(?:bank\s+report|bank\s+statement\s+(?:report|summary|analysis|p&l)|statement\s+report|bank\s+p&l|bank\s+analysis|show\s+bank\s+(?:report|summary|expenses?|income)|analyze\s+bank|bank\s+expense\s+(?:report|summary|breakdown)|income\s+expense\s+report|p&l\s+(?:for|of|report)\b)", re.I), "BANK_REPORT", 0.94),
    # Complaint REGISTER with "report" verb — "report plumbing issue" = file complaint (before REPORT)
    (re.compile(r"^report\s+(?:plumbing|electrical|electric|water|fan|ac|air.?con|pest|toilet|door|window|lift|wifi|internet|issue|problem|complaint|broken|leak|not\s+working)", re.I), "COMPLAINT_REGISTER", 0.93),
    # Report — early catch for "occupancy report", "monthly report" before other patterns grab them
    (re.compile(r"(?:occupancy\s+report|\w+(?:\s+\w+)?\s+report\b|monthly\s+report)", re.I), "REPORT", 0.92),
    # Report — general
    (re.compile(r"(?:report|summary|monthly|(?:monthly|financial)\s+statement|accounts|P&L|profit|income|collection|total collected|financial)", re.I), "REPORT", 0.88),
    # Report — cash / UPI / general collection queries
    (re.compile(r"(?:how much (?:cash|upi|rent|money|total|was|is|have|did)|how much collect|cash collect|upi collect|total cash|total upi|what.?s collect|collect\w* in|collect\w* for|cash (?:for|in|this|last|march|feb|jan|dec|nov|oct|sep|aug|jul|jun|apr)|upi (?:for|in|this|last|march|feb|jan|dec|nov|oct|sep|aug|jul|jun|apr))", re.I), "REPORT", 0.92),
    # Salary / staff payment — must come BEFORE generic PAYMENT_LOG and ADD_EXPENSE
    (re.compile(r"(?:paid\s+salary|salary\s+paid|staff\s+salary|pay\s+salary|salary\s+to\s+\w+|wages?|disburse\w*\s+salary)", re.I), "ADD_EXPENSE", 0.92),
    # Bill payments (electricity/water/internet + "bill" + "paid") — ADD_EXPENSE not PAYMENT_LOG
    (re.compile(r"(?:paid\s+(?:electricity|electric|water|internet|eb|bwssb|bescom|broadband)\s+bill|(?:electricity|water|internet|eb)\s+bill\s+(?:paid|pay|payment)\b|(?:electricity|elec|electric|elecrticity|elecrtric)\s+bill\s+\d)", re.I), "ADD_EXPENSE", 0.94),
    # Typo patterns for payment: "pajment", "paiment"
    (re.compile(r"p[ai]{0,2}j?[ai]{0,2}m[ae]{0,2}nt\s+\d|(?:pajment|paiment|payemnt|pymnt)\b", re.I), "PAYMENT_LOG", 0.88),
    # Typo patterns for electricity ADD_EXPENSE: "elecrticity", "electrcity", etc.
    (re.compile(r"(?:elecrt?icity|electrcity|elecricity|elecrtrcity)\s+(?:bill\s+)?[\d,k]+", re.I), "ADD_EXPENSE", 0.90),
    # Service/repair payments with amount — plumber, electrician, etc. (before COMPLAINT_REGISTER)
    (re.compile(r"(?:plumber|electrician|carpenter|painter|pest\s*control|cleaning\s*(?:service|staff)|security\s+guard|watchman|cook|maid|housekeeping|caretaker)\s+\d|paid\s+(?:plumber|electrician|carpenter|painter|pest|cleaning|security|watchman|cook|maid)\b|\d+\s+(?:for\s+)?(?:plumber|electrician|repair|maintenance|pest|cleaning)", re.I), "ADD_EXPENSE", 0.93),
    # Expense (add new expense — must come before PAYMENT_LOG)
    (re.compile(r"(?:expense|electricity\s+(?:bill\s+)?\d|water\s+bill|internet\s+bill|salary|maintenance\s+cost|paid\s+for|vendor|repair\s+\d|\d+\s+repair|generator\s+(?:maintenance|fuel|diesel|repair|rent|bill|expense|cost)\b|diesel\s+\d|\d+\s+diesel)", re.I), "ADD_EXPENSE", 0.88),
    # Amount-first expense shorthand: "5000 cash maintenance", "3000 upi electricity"
    (re.compile(r"^\d[\d,k]+\s+(?:cash|upi|gpay|phonepe|paytm|online|bank|neft|imps|naqad)\s+(?:maintena?na?ce?|cleaning|repair|electricity|water|internet|generator|groceries?|housekeeping|supplies|security|pest|plumbing|painting|furniture|food)\b", re.I), "ADD_EXPENSE", 0.92),
    # Early QUERY_DUES — explicit patterns before QUERY_TENANT grabs "outstanding"/"month" as a name
    (re.compile(
        r"(?:outstanding\s+dues\b|dues\s+(?:for\s+)?(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*(?:\s+\d{4})?|backlogs?\b|kisne\s+nahi\s+diya|defaulters?\s+(?:list|log)|baki\s+(?:list|sabka))",
        re.I
    ), "QUERY_DUES", 0.92),
    # "did Raj pay this month?" / "did Suresh pay?" — query, NOT payment log
    (re.compile(r"did\s+(?!my\b)([A-Za-z]{3,}(?:\s+[A-Za-z]+)?)\s+pay\b", re.I), "QUERY_TENANT", 0.92),
    # "change/set/update rent for X" — MUST come before QUERY_TENANT rent_for rule
    (re.compile(r"(?:change|update|set|increase|decrease|revise|hike|reduce)\s+rent\s+(?:for|of)\s+\w", re.I), "RENT_CHANGE", 0.93),
    # "what is the rent for X" / "what's X's rent from July" — tenant account query
    (re.compile(r"(?:what(?:'?s|\s+is|\s+was)\s+(?:the\s+)?rent|rent\s+(?:for|of)\s+\w|how\s+much\s+(?:is|was)\s+(?:the\s+)?rent)", re.I), "QUERY_TENANT", 0.91),
    # Specific tenant query — "Raj dues", "Jeevan balance", "room 203 balance"
    # Must come before QUERY_DUES catch-all. Three patterns:
    #   1. Named person + dues/balance/status/outstanding/account statement
    #   2. balance/dues of <name>
    #   3. Hindi: name ka paise/balance
    (re.compile(
        r"(?:"
        r"(?:balance|dues|status)\s+(?:of\s+|for\s+)?(?!(?:my|all|total|pending|outstanding|show|the|everyone|all|this|last)\b)([A-Za-z]{3,}(?:\s+[A-Za-z]+)?)"  # "balance of Raj"
        r"|"
        r"(?!(?:my|all|total|pending|outstanding|show|the|everyone)\b)([A-Z][a-z]{1,}(?:\s+[A-Z][a-z]+)?)'?s?\s+(?:balance|dues|status|outstanding|account\s+statement|details?)"  # "Raj balance", "Raj's account", "Vikram details"
        r"|"
        r"room\s+[\w-]+\s+(?:balance|dues|status|who|tenant|person|occupant)"  # "room 203 balance" (removed "details" — goes to ROOM_STATUS)
        r"|"
        r"how\s+much\s+(?:does|did|is|has)\s+(?!my\b)(\w+)\s+(?:owe|paid|pay|balance)"  # "how much does Suresh owe"
        r"|"
        r"someone\s+from\s+room\s+[\w-]+"  # "someone from room 203"
        r"|"
        r"(?!(?:my|all|total|pending|outstanding|show|the|everyone)\b)([A-Z][a-z]{1,}(?:\s+[A-Z][a-z]+)?)\s+(?:ka|ki|ke)\s+(?:paise|paisa|account|balance)\b"  # "Raj ka paise"
        r"|"
        r"payment\s+history\b"  # "payment history" = show all tenant payment history
        r"|"
        r"show\s+(?!(?:all|total|pending|outstanding|p&l|pl|profit|summary|report|financial|income|collection|accounts|stats)\b)([A-Z][a-z]{2,}(?:\s+[A-Z][a-z]+)?)'?s?\s+(?:account|details|info|summary)\b"  # "show Arjun account", "show Arjun's account"
        r"|"
        r"(?!(?:my|all|total|pending|outstanding|show|the|everyone)\b)([A-Za-z]{3,}(?:\s+[A-Za-z]+)?)\s+(?:account|account\s+details|account\s+summary)\b"  # "Arjun account"
        r")",
        re.I
    ), "QUERY_TENANT", 0.88),
    # Financial summary queries with "show" — must come before the QUERY_DUES "show" catch
    (re.compile(r"(?:show\s+(?:p&l|pl|profit|summary|report|financial|income|collection|accounts|stats?\b)|what\s+(?:is|was|are)?\s+(?:the\s+)?(?:financial|p&l|total\s+(?:income|collection|revenue))|how\s+much\s+(?:total|overall|did\s+we\s+collect|have\s+we\s+made)|\bstats?\b|(?:jan|feb|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+report\b|report\s+for\s+(?:jan|feb|mar|apr|may))", re.I), "REPORT", 0.92),
    # Dues / pending — bulk queries (who hasn't paid, show pending, etc.)
    # NOT for single-tenant queries like "Raj dues" (those go to QUERY_TENANT above)
    (re.compile(r"(?:who\s+(?:hasn.?t|haven.?t|has\s+not|have\s+not)\s+paid|who\s+owes\b|pending\s+(?:dues|list|rent|payments?)|list\s+(?:dues|pending|unpaid)|show\s+(?:all\s+)?(?:dues|pending|unpaid|outstanding)|baki|unpaid|not\s+paid|haven.?t\s+paid|dues\s+(?:list|this|for\s+(?:all|everyone|this|the))|dues\s+this\s+month|all\s+(?:pending|dues|outstanding)|outstanding\s+(?:dues|rent|payments?)|defaulters?\b)", re.I), "QUERY_DUES", 0.90),
    # Backdated check-in correction — BEFORE SCHEDULE_CHECKOUT (catches "update checkin Arjun March 5")
    (re.compile(r"(?:update|correct|change|backdat)\w*\s+check.?in|checked?\s+in\s+on\b|actually\s+joined|joined\s+on\b|check.?in\s+date\s+(?:for|of)\s+\w+|\w+\s+joined\s+on\s+\d|check.?in\s+was\s+on|joining\s+date\s+(?:for|is|was)|\w+\s+check.?in\s+(?:was\s+)?(?:on\s+)?\d|\w+\s+check.?in\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)", re.I), "UPDATE_CHECKIN", 0.94),
    # Reminder — BEFORE SCHEDULE_CHECKOUT (catches "reminder Deepak March 5")
    (re.compile(r"(?:remind|reminder|remindr?\b|remaindr?\b|reminde\b|set reminder|alert|notify|yaad\s+(?:dilao|dilaao|karo)\b|ko\s+yaad\s+dilao)", re.I), "REMINDER_SET", 0.90),
    # Scheduled / date-specific checkout — "checkout on 31 May", "leaving on March 10"
    (re.compile(
        r"(?:check(?:ing)?\s*out|leaving|vacating|moving\s*out)\s+(?:on|by|from|before)\b"
        r"|(?:scheduled?|planned?|expected)\s+checkout|checkout\s+(?:date|on|by|scheduled)\b"
        r"|(?:last\s+day|final\s+day)\s+(?:is|will\s+be|on)|plan\s+checkout\s+\w+"
        r"|\w+\s+leaving\s+(?:end\s+of\s+)?(?:in\s+)?(?:jan|feb|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b"
        r"|\w+\s+leaving\s+(?:end\s+of|this|next)\s+month|plan(?:ned)?\s+to\s+(?:leave|vacate)\s+(?:on\s+)?\d"
        r"|\w+\s+\d{1,2}\s+(?:jan|feb|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b"
        r"|\w+\s+(?:jan|feb|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+\d{1,2}\b"
        r"|\w+\s+\d+\s+(?:jan|feb|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?)\s+ko\s+jayega|\w+\s+(?:ko|mein)\s+jayega\b",
        re.I
    ), "SCHEDULE_CHECKOUT", 0.93),
    # Notice period — "gave notice", "serving notice", "wants to leave", bare "notice"
    (re.compile(r"gave notice|giving notice|serving notice|\bnotice\b|notice period|plans? to (?:leave|vacate)|wants? to (?:leave|move)", re.I), "NOTICE_GIVEN", 0.92),
    # Immediate checkout (no date)
    (re.compile(r"(?:check.?out|vacate|vacating|leaving|exit|moving out|ja\s+raha\s+hai\b|chhod\s+raha\s+hai\b)", re.I), "CHECKOUT", 0.95),
    # Add tenant
    (re.compile(r"(?:add\s+te(?:nant?|ant|nent|nnant?)\b|new\s+tenant|new\s+admission|\badmit\s+\w+|\btenant\s+\w+\s+\d{7,}|\bcheck.?in\b|joining|new\s+room|onboard|register\s+tenant|naya\s+tenant\b|tenant\s+add\s+karo)", re.I), "ADD_TENANT", 0.95),
    # Rent change (permanent or from a month) — must come before RENT_DISCOUNT
    (re.compile(r"rent (?:is now|from\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|next)|change|increase|hike|reduce|decrease)|new rent|from \w+ rent|rent to \d|from\s+next\s+month\s+rent|room\s+[\w-]+\s+rent\s+(?:\d|updated?|changed?|revised?)|(?:change|update|revise|set|increase)\s+rent\b|room\s+[\w-]+\s+to\s+\d{4,}|increase\s+rent\s+(?:for\s+)?room|(?:change|update|revise|set|increase)\s+rent\s+(?:for\s+)?(?:room|[A-Z][a-z]+)\b", re.I), "RENT_CHANGE", 0.91),
    # One-time discount / concession / surcharge
    (re.compile(r"(?:concession|discount|waive|deduct|give.*less|less this month|reduce this month|reduce\s+\w+'?s?\s+rent\s+by|extra charge|add.*surcharge|add.*electricity|add.*food charge)", re.I), "RENT_DISCOUNT", 0.90),
    # Add partner / staff
    (re.compile(r"(?:add partner|add owner|add power user|new admin|give access|add\s+staff\b)", re.I), "ADD_PARTNER", 0.97),
    # WiFi password — owner reads or sets WiFi credentials
    (re.compile(r"(?:set\s+wifi|update\s+wifi|change\s+wifi|wifi\s+(?:ssid|network|password)\s+\w+|set\s+(?:floor|common)\s+wifi)", re.I), "SET_WIFI", 0.95),
    (re.compile(r"(?:wifi|wi-fi|internet|net)\s*(?:password|pass|pw|code|key|kya\s+hai|batao|share|bata|kya\s+h)", re.I), "GET_WIFI_PASSWORD", 0.95),
    (re.compile(r"(?:what.?s?\s+(?:the\s+)?wifi|whats?\s+(?:the\s+)?wifi|wifi\s+(?:ka\s+)?password|password\s+(?:for\s+)?wifi)", re.I), "GET_WIFI_PASSWORD", 0.95),
    # Complaint update / resolve — "resolve CMP001", "close complaint 3", "mark resolved"
    (re.compile(r"(?:resolve\s+(?:complaint\s+)?(?:CMP[-\d]+|\d+)|complaint\s+(?:solved?|done|fixed|closed?|resolved?)\s*(?:CMP[-\d]+|\d+)?|close\s+complaint\s*(?:CMP[-\d]+|\d+)?|mark\s+(?:complaint\s+)?(?:resolved?|done|fixed|closed?)\s*(?:CMP[-\d]+|\d+)?|fix(?:ed)?\s+complaint\s*(?:CMP[-\d]+|\d+)?)", re.I), "COMPLAINT_UPDATE", 0.94),
    # Complaint query — "show complaints", "pending complaints", "open complaints"
    (re.compile(r"(?:show\s+(?:all\s+)?complaints?|open\s+complaints?|pending\s+complaints?|complaint\s+list|list\s+(?:all\s+)?complaints?|unresolved\s+complaints?|complaints?\s+(?:status|summary|pending|open|list)|how\s+many\s+complaints?)", re.I), "QUERY_COMPLAINTS", 0.93),
    # Complaint / maintenance — owner can log for a room
    (re.compile(r"(?:complaint|complain|issue|problem|not working|broken|leak(?:ing)?\b|fix|tap|flush|bulb|fan|switch|slow net|food (?:complaint|bad|issue|quality)|bed sheet|mattress|pillow|chair|table|shelf|almirah|\bAC\b|air.?condition|toilet|blocked|door\s*lock|kharab\b|pest\b|wifi\s+(?:not|issue|problem|broken|slow)|internet\s+(?:not|issue|problem|down|slow))", re.I), "COMPLAINT_REGISTER", 0.88),
    # PG rules & regulations
    (re.compile(r"(?:rules?|regulations?|pg rules?|what are the rules?|rules and regulations?|policy|policies|house rules?|show rules?|niyam\b)", re.I), "RULES", 0.91),
    # Tenant notes / agreed terms / payment method lookup
    (re.compile(r"(?:notes?|agreement|agreed\s+terms?|payment\s+method|cash\s+only|rent\s+terms?|terms?)\s+(?:for\s+|of\s+)?(?:room\s+)?[\w-]+|(?:check|show|get|what(?:'?s|\s+is)?)\s+(?:the\s+)?(?:notes?|agreement|terms?|payment\s+method)\s+(?:for\s+|of\s+)?[\w\s-]+|room\s+[\w-]+\s+(?:notes?|terms?|agreement|payment\s+method|cash\s+only)|(?:notes?|agreement|terms?)\s+room\s+[\w-]+", re.I), "GET_TENANT_NOTES", 0.93),
    # Expense category shorthand "Category Amount [Mode]" — MUST come before PAYMENT_LOG shorthand
    # With payment mode (e.g. "maintenance 3000 upi")
    (re.compile(r"^(?:maintena?na?ce?|maintanace|maintanance|cleaning|repairs?|furniture|plumbing|painting|pest\s*(?:control)?|food\s+(?:supplies?|expense|stuff)|internet|generator|groceries?|housekeeping|supplies|security)\s+[\d,k]+\s+(?:cash|upi|gpay|phonepe|paytm|online|bank|neft|imps|cheque|naqad)\b", re.I), "ADD_EXPENSE", 0.94),
    # Without payment mode (e.g. "electricity 8400", "internet 1800", "maintenance 3000")
    (re.compile(r"^(?:electricity|water\s*bill|internet|maintenance|food|groceries?|cleaning|plumbing|pest\s*(?:control)?|generator|security|supplies|housekeeping|repairs?|diesel|salary)\s+[\d,k]+\s*$", re.I), "ADD_EXPENSE", 0.92),
    # Collect rent — step-by-step form trigger (no amount/name)
    (re.compile(r"^(?:collect\s+rent|rent\s+collect(?:ion)?|log\s+(?:a\s+)?payment|record\s+payment|payment\s+log)\s*$", re.I), "PAYMENT_LOG", 0.93),
    # Payment log — before HELP so "Hi sir Raj paid 15000" doesn't become HELP
    (re.compile(r"(?:p[ai]{2,3}d?|payment|received|collected|deposited|transferred|jama|diya)\s.*?\d", re.I), "PAYMENT_LOG", 0.92),
    (re.compile(r"\d[\d,k]+\s*(?:paid|p[ai]{2,3}d?|payment|received|from|by)", re.I), "PAYMENT_LOG", 0.92),
    # "Deepak payment received" — payment received without explicit digit (assume most recent payment)
    (re.compile(r"(?:[A-Z][a-z]{2,})\s+payment\s+(?:received|confirmed|done|collected|cleared)\b", re.I), "PAYMENT_LOG", 0.90),
    # Shorthand "Name Amount Mode" — e.g. "Arjun 12000 cash", "Raj 8000 upi"
    (re.compile(r"^[A-Z][a-z]{2,}\s+\d[\d,k]+\s+(?:cash|upi|gpay|phonepe|paytm|online|bank|neft|imps|cheque|naqad)\b", re.I), "PAYMENT_LOG", 0.91),
    # Amount-first shorthand: "15000 Raj gpay", "8000 from Suresh cash"
    (re.compile(r"^\d[\d,k]+\s+(?:[A-Z][a-z]{2,}|from\s+[A-Z][a-z]{2,})\s+(?:cash|upi|gpay|phonepe|paytm|online|bank|neft|imps|cheque|naqad)\b", re.I), "PAYMENT_LOG", 0.91),
    # Word-number payments: "Raj paid fifteen thousand", "paid ten thousand"
    (re.compile(r"(?:[A-Z][a-z]+\s+)?p[ai]{2,3}d?\s+(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty|thirty|forty|fifty)\s+(?:thousand|hundred|lakh)\b", re.I), "PAYMENT_LOG", 0.90),
    # Help — only for short greeting messages (moved after PAYMENT_LOG)
    (re.compile(r"^(?:hi|hello|hey|help|menu|commands?|start|hii|helo)\b|kya\s+kar\s+sakte|what\s+can\s+(?:i|you)\b|how\s+to\s+use\b|show\s+commands?\b", re.I), "HELP", 0.95),
]

# ── Tenant intents ────────────────────────────────────────────────────────────

_TENANT_RULES: list[tuple[re.Pattern, str, float]] = [
    # Checkout notice — tenant wanting to leave (check before HELP/balance)
    (re.compile(r"(?:i want to (?:leave|vacate|move out|checkout|check out)|i(?:'m| am) (?:leaving|moving out)|(?:giving|serve|serving) notice|i(?:'ll| will) vacate|my last day|i want to give notice|notice to vacate|plan(?:ning)? to leave|want to (?:checkout|check out|leave|vacate))", re.I), "CHECKOUT_NOTICE", 0.94),
    # Vacation / going home notice
    (re.compile(r"(?:going home|on vacation|on leave|going to (?:native|village|hometown)|will be (?:away|absent|back on)|coming back on|out of (?:station|town|city)|vacation\s+notice\s+\d+\s+days?)", re.I), "VACATION_NOTICE", 0.92),
    # WiFi password request — before COMPLAINT_REGISTER so "wifi password" doesn't become a complaint
    (re.compile(r"(?:wifi|wi-fi|internet|net)\s*(?:password|pass|pw|code|key|kya\s+hai|batao|share|bata|kya\s+h)", re.I), "GET_WIFI_PASSWORD", 0.95),
    (re.compile(r"(?:what.?s?\s+(?:the\s+)?wifi|whats?\s+(?:the\s+)?wifi|wifi\s+(?:ka\s+)?password|password\s+(?:for\s+)?wifi)", re.I), "GET_WIFI_PASSWORD", 0.95),
    # Complaint / maintenance request
    (re.compile(r"(?:complaint|complain|issue|problem|not working|broken|leak(?:ing)?\b|repair|fix|tap|flush|bulb|fan|switch|wifi|wi-fi|internet|slow net|food (?:complaint|bad|issue|quality)|bed sheet|mattress|pillow|chair|table|shelf|almirah|\bAC\b|air.?condition|toilet|blocked|door\s*lock|kharab\b|pest\b|light\s+nahi\b)", re.I), "COMPLAINT_REGISTER", 0.91),
    # Balance
    (re.compile(r"(?:my balance|mera balance|balance\s+kya\s+hai?|how much|i owe|dues|pending|baki|outstanding|need to pay|kitna dena|rent status|kitna bacha|mera\s+(?:balance|paisa|account))", re.I), "MY_BALANCE", 0.92),
    # Request receipt / payment proof — BEFORE MY_PAYMENTS so "payment receipt" routes here
    (re.compile(r"(?:receipt|payment\s+proof|payment\s+(?:receipt|slip|confirmation)|send\s+receipt|need\s+receipt|my\s+receipt)", re.I), "REQUEST_RECEIPT", 0.92),
    # Payment history — bare "paid" removed to avoid catching "who hasn't paid" (admin cmd)
    (re.compile(r"(?:my\s+payments?|past\s+payments?|payment\s+history|when\s+did\s+i\s+last\s+pay|meri\s+payments?|transaction\s+history|previous\s+payments?)", re.I), "MY_PAYMENTS", 0.90),
    # My details
    (re.compile(r"(?:my room|my details|my rent|checkin|when did i|my info|my profile|my information|my account|mera room|mera number)", re.I), "MY_DETAILS", 0.88),
    # PG rules & regulations
    (re.compile(r"(?:rules?|regulations?|pg rules?|what are the rules?|rules and regulations?|policy|policies|house rules?|show rules?|what rules?|niyam\b)", re.I), "RULES", 0.91),
    # Help / greeting
    (re.compile(r"^(?:hi|hello|hey|help|menu|start|commands?|good\s+morning|good\s+evening|good\s+afternoon|thanks?|thank\s+you|ok(?:ay)?)\b|what\s+can\s+(?:i|you)\b", re.I), "HELP", 0.95),
]

# ── Lead intents ──────────────────────────────────────────────────────────────

_LEAD_RULES: list[tuple[re.Pattern, str, float]] = [
    (re.compile(r"(?:price|pricing\b|rent|cost|how much|rates?|charge|fee|monthly(?!\s+report)|what.?s\s+included)", re.I), "ROOM_PRICE", 0.90),
    (re.compile(r"(?:available|vacancy|empty|free room|any room|do\s+you\s+have\s+rooms?|looking\s+for\s+a\s+(?:room|pg)|rooms?\s+available)", re.I), "AVAILABILITY", 0.90),
    (re.compile(r"(?:single|double|triple|sharing|private|attached|ac room|non.?ac|what\s+types?\s+of\s+rooms?|shared\s+room)", re.I), "ROOM_TYPE", 0.88),
    (re.compile(r"(?:visit|tour|come see|can i see|viewing|inspect)", re.I), "VISIT_REQUEST", 0.92),
    # Detect admin-only intents so lead handler can give a helpful "contact owner" response
    (re.compile(r"(?:wifi|wi-fi|internet|net)\s*(?:password|pass|pw|code|key|kya\s+hai|batao|share|bata|kya\s+h)", re.I), "GET_WIFI_PASSWORD", 0.95),
    (re.compile(r"(?:what.?s?\s+(?:the\s+)?wifi|wifi\s+(?:ka\s+)?password|password\s+(?:for\s+)?wifi)", re.I), "GET_WIFI_PASSWORD", 0.95),
]


_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _extract_date_entity(text: str) -> Optional[str]:
    """
    Extract a date from text and return ISO string YYYY-MM-DD, or None.
    Handles: "20 Feb", "Feb 20", "March 10", "31 May 2026", "20/02/2026".
    If no year given and result is in the future, keeps future year (for scheduling).
    """
    from datetime import date as date_type

    today = date_type.today()

    def _build(day: int, month: int, year: Optional[int] = None) -> Optional[str]:
        y = year or today.year
        try:
            return date_type(y, month, day).isoformat()
        except ValueError:
            return None

    # "20 Feb", "20th Feb", "20 February", "20 Feb 2026"
    m = re.search(
        r"(\d{1,2})(?:st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*(?:\s+(\d{4}))?",
        text, re.I,
    )
    if m:
        month_num = _MONTHS.get(m.group(2)[:3].lower())
        if month_num:
            year = int(m.group(3)) if m.group(3) else None
            return _build(int(m.group(1)), month_num, year)

    # "Feb 20", "Feb 20th", "February 20", "March 10 2026"
    m = re.search(
        r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+(\d{1,2})(?:st|nd|rd|th)?(?:\s+(\d{4}))?",
        text, re.I,
    )
    if m:
        month_num = _MONTHS.get(m.group(1)[:3].lower())
        if month_num:
            year = int(m.group(3)) if m.group(3) else None
            return _build(int(m.group(2)), month_num, year)

    # DD/MM/YYYY or DD-MM-YYYY or DD.MM.YYYY
    m = re.search(r"\b(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})\b", text)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if year < 100:
            year += 2000
        return _build(day, month, year)

    return None


# ── Ambiguous pattern pairs (checked BEFORE main rules) ───────────────────────
# Each entry: (pattern, [intent1, intent2], human_labels)
# Fired when a message genuinely could mean two different things.
_MONTH = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_AMBIGUOUS_OWNER: list[tuple[re.Pattern, list[str], list[str]]] = [
    # "Raj 31st March" or "Raj March 31" — no checkin/checkout verb
    (
        re.compile(
            r"^([A-Z]\w+)\s+(?:\d{1,2}(?:st|nd|rd|th)?\s+" + _MONTH + r"|" + _MONTH + r"\s+\d{1,2}(?:st|nd|rd|th)?)\s*$",
            re.I,
        ),
        ["UPDATE_CHECKIN", "SCHEDULE_CHECKOUT"],
        ["Update check-in date", "Schedule checkout"],
    ),
]

# Human-readable labels for intent alternatives shown in disambiguation prompt
_INTENT_LABELS: dict[str, str] = {
    "UPDATE_CHECKIN":    "Update check-in date",
    "SCHEDULE_CHECKOUT": "Schedule checkout date",
    "CHECKOUT":          "Mark checkout (immediate)",
    "PAYMENT_LOG":       "Log payment received",
    "ADD_EXPENSE":       "Record expense",
    "QUERY_DUES":        "Check who owes dues",
    "QUERY_TENANT":      "View tenant details",
    "QUERY_CONTACTS":    "Look up vendor/supplier contacts",
}


# ── Direct intent passthrough (WhatsApp button / list replies) ────────────────
# When a user taps a button or selects from a list, Meta sends the button id as
# the message body verbatim. We bypass regex and route it directly.
_OWNER_DIRECT: frozenset[str] = frozenset({
    "ADD_TENANT", "CHECKOUT", "RECORD_CHECKOUT", "START_ONBOARDING",
    "PAYMENT_LOG", "ADD_EXPENSE", "ADD_REFUND",
    "QUERY_DUES", "QUERY_TENANT", "QUERY_VACANT_ROOMS", "QUERY_OCCUPANCY",
    "QUERY_EXPIRING", "QUERY_CHECKINS", "QUERY_CHECKOUTS", "QUERY_CONTACTS",
    "REPORT", "GET_WIFI_PASSWORD", "SET_WIFI", "ADD_PARTNER",
    "COMPLAINT_REGISTER", "COMPLAINT_UPDATE", "QUERY_COMPLAINTS",
    "ACTIVITY_LOG", "QUERY_ACTIVITY",
    "RULES", "HELP", "MORE_MENU",
})

# Subset of _OWNER_DIRECT that receptionist can use via button taps
_RECEPTIONIST_DIRECT: frozenset[str] = frozenset({
    "PAYMENT_LOG", "QUERY_DUES", "QUERY_TENANT", "QUERY_VACANT_ROOMS",
    "QUERY_OCCUPANCY", "QUERY_CONTACTS",
    "COMPLAINT_REGISTER", "COMPLAINT_UPDATE", "QUERY_COMPLAINTS",
    "ACTIVITY_LOG", "QUERY_ACTIVITY",
    "HELP", "MORE_MENU",
})
_TENANT_DIRECT: frozenset[str] = frozenset({
    "MY_BALANCE", "MY_PAYMENTS", "MY_DETAILS", "REQUEST_RECEIPT",
    "GET_WIFI_PASSWORD", "COMPLAINT_REGISTER", "CHECKOUT_NOTICE", "RULES", "HELP",
})
_LEAD_DIRECT: frozenset[str] = frozenset({
    "ROOM_PRICE", "AVAILABILITY", "ROOM_TYPE", "VISIT_REQUEST",
})


def detect_intent(text: str, role: str) -> IntentResult:
    """
    Detect intent from message text based on caller role.
    Returns IntentResult with intent name, confidence, and extracted entities.
    """
    text = text.strip()

    # ── Button / list tap: exact intent name sent by Meta ─────────────────────
    upper = text.upper()
    if role in ("admin", "power_user", "key_user") and upper in _OWNER_DIRECT:
        return IntentResult(intent=upper, confidence=0.99)
    if role == "receptionist" and upper in _RECEPTIONIST_DIRECT:
        return IntentResult(intent=upper, confidence=0.99)
    if role == "tenant" and upper in _TENANT_DIRECT:
        return IntentResult(intent=upper, confidence=0.99)
    if role == "lead" and upper in _LEAD_DIRECT:
        return IntentResult(intent=upper, confidence=0.99)

    if role in ("admin", "power_user", "key_user", "receptionist"):
        rules = _OWNER_RULES
        # Check ambiguous patterns first (before main rules) — only for full owner roles
        if role in ("admin", "power_user", "key_user"):
            for amb_pattern, amb_intents, amb_labels in _AMBIGUOUS_OWNER:
                if amb_pattern.search(text):
                    entities = _extract_entities(text, amb_intents[0])
                    entities["alternatives"] = amb_intents
                    entities["alt_labels"]   = amb_labels
                    return IntentResult(
                        intent="AMBIGUOUS",
                        confidence=0.5,
                        entities=entities,
                        alternatives=amb_intents,
                    )
    elif role == "tenant":
        rules = _TENANT_RULES
    elif role == "lead":
        rules = _LEAD_RULES
    else:
        return IntentResult(intent="GENERAL", confidence=0.5)

    for pattern, intent, conf in rules:
        if pattern.search(text):
            entities = _extract_entities(text, intent)
            return IntentResult(intent=intent, confidence=conf, entities=entities)

    # ── Learned rules (admin-taught via !learn command) ───────────────────────
    for pattern, intent, conf, applies_to in _load_learned_rules():
        if applies_to not in ("all", role) and applies_to != "owner" or (
            applies_to == "owner" and role not in ("admin", "power_user", "key_user", "receptionist")
        ):
            continue
        if pattern.search(text):
            entities = _extract_entities(text, intent)
            return IntentResult(intent=intent, confidence=conf, entities=entities)

    # Fallback
    if role == "lead":
        return IntentResult(intent="GENERAL", confidence=0.5)
    return IntentResult(intent="UNKNOWN", confidence=0.3)


def _extract_entities(text: str, intent: str) -> dict:
    """Extract structured data from natural language."""
    entities: dict = {}

    # Extract amount — prefer number AFTER a payment keyword (avoids room-number-as-amount)
    # e.g. "203 paid 8000" → 8000, not 203
    amount_match = re.search(
        r"(?:paid|payment|received|collected|deposited|rs\.?|inr)\s*(\d[\d,]*(?:\.\d+)?)\s*(?:k\b)?",
        text, re.I,
    )
    if not amount_match:
        # Strip room numbers before fallback scan so "room 811" doesn't become amount=811
        _text_no_room = re.sub(r"\b(?:room|bed|flat|unit)\s+[\w-]+", "", text, flags=re.I)
        amount_match = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*(?:k\b)?", _text_no_room, re.I)
    if amount_match:
        raw = amount_match.group(1).replace(",", "")
        # Check for "k" suffix in the 2 chars after the match (use matched text itself)
        after = amount_match.group(0)
        multiplier = 1000 if after.lower().endswith("k") else 1
        try:
            entities["amount"] = float(raw) * multiplier
        except ValueError:
            pass

    # Extract name (capitalized word not a command word)
    SKIP_WORDS = {"paid", "payment", "balance", "dues", "pending", "report",
                  "monthly", "summary", "from", "for", "room", "rent"}
    name_match = re.search(r"\b([A-Z][a-z]{2,}(?:\s[A-Z][a-z]+)?)\b", text)
    if name_match:
        parts = name_match.group(1).split()
        # Strip trailing skip words (e.g. "Jeevan Balance" -> "Jeevan")
        while parts and parts[-1].lower() in SKIP_WORDS:
            parts.pop()
        if parts and parts[0].lower() not in SKIP_WORDS:
            entities["name"] = " ".join(parts)

    # Extract room number — handles:
    #   "room 203", "room 203-A", "bed 203", "flat G15"
    #   "203A paid 8000"  (room number at start before a payment verb)
    room_match = re.search(r"(?:room|bed|flat|unit)\s*([\w-]+)", text, re.I)
    if not room_match:
        room_match = re.search(
            r"^([\d]{2,4}[A-Za-z]?)\s+(?:paid|payment|received|balance|dues|has|is|gave|wants|plans|leaving|checkout|checked|joined)\b",
            text, re.I,
        )
    if room_match:
        entities["room"] = room_match.group(1)

    # Extract full date (ISO string) — takes priority for timing scenarios
    date_val = _extract_date_entity(text)
    if date_val:
        entities["date"] = date_val

    # Extract month (fallback when no full date extracted)
    if "month" not in entities:
        for abbr, num in _MONTHS.items():
            if re.search(abbr, text, re.I):
                entities["month"] = num
                break

    # Extract payment mode
    if re.search(r"\b(?:cash|naqad)\b", text, re.I):
        entities["payment_mode"] = "cash"
    elif re.search(r"\b(?:upi|gpay|phonepe|paytm|online|transfer)\b", text, re.I):
        entities["payment_mode"] = "upi"

    # Extract expense category (for ADD_EXPENSE — avoids unnecessary "choose category" prompt)
    if intent == "ADD_EXPENSE":
        _EXPENSE_KEYWORDS = [
            (r"\belectricity\b|\blight\s+bill\b|\beb\s+bill\b", "electricity"),
            (r"\bwater\s+bill\b|\bwater\b", "water"),
            (r"\binternet\b|\bbroadband\b|\bwifi\s+bill\b", "internet"),
            (r"\bsalary\b|\bwages?\b|\bstaff\s+pay\b", "salary"),
            (r"\bplumb\w*\b|\bpipe\b|\btap\b|\bdrain\b|\bsewage\b", "maintenance"),
            (r"\bmaintena?na?ce?\b|\brepair\b|\bpainting\b|\bcarpenter\b|\belectrician\b", "maintenance"),
            (r"\bgroceries?\b|\bgrocery\b|\bvegetable\b|\bprovision\b", "groceries"),
            (r"\bfood\b|\bcooking\b|\bcaterer\b", "groceries"),
            (r"\bgenerator\b|\bdiesel\b|\bfuel\b|\bdg\b", "maintenance"),
            (r"\bcleaning\b|\bhousekeeping\b|\bmaid\b|\bsweeping\b", "maintenance"),
            (r"\bsecurity\b|\bwatchman\b|\bguard\b", "salary"),
        ]
        for pattern, cat in _EXPENSE_KEYWORDS:
            if re.search(pattern, text, re.I):
                entities["category"] = cat
                break

    # Extract year — useful for BANK_REPORT / QUERY_DUES with explicit year
    if "year" not in entities:
        year_match = re.search(r"\b(202[4-9]|203\d)\b", text)
        if year_match:
            entities["year"] = int(year_match.group(1))

    # Relative time — "last month", "previous month"
    if re.search(r"\b(?:last|previous|prev)\s+month\b", text, re.I):
        entities["relative"] = "last_month"

    return entities
