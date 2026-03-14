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
    intent:     str
    confidence: float
    entities:   dict = field(default_factory=dict)   # e.g. {name, amount, room, month}


# ── Owner / Power-user intents ────────────────────────────────────────────────

_OWNER_RULES: list[tuple[re.Pattern, str, float]] = [
    # Start onboarding / KYC for a new tenant (must be first — very specific)
    (re.compile(r"(?:start onboarding|begin onboarding|start kyc|begin kyc|start checkin|begin checkin|onboard\s+\w+|kyc for|checkin for\s+\w+)", re.I), "START_ONBOARDING", 0.96),
    # Record checkout / offboarding form
    (re.compile(r"(?:record checkout|offboard|checkout form|fill checkout|checkout record|handover|keys? (?:returned?|handed?)|mark checkout complete|complete checkout)", re.I), "RECORD_CHECKOUT", 0.95),
    # Void / reverse payment
    (re.compile(r"(?:void|cancel|reverse|undo payment|mark void|failed payment|payment failed|wrong payment|duplicate payment)", re.I), "VOID_PAYMENT", 0.93),
    # Send reminder to ALL tenants
    (re.compile(r"(?:send reminder to all|remind all|remind everyone|blast reminder|mass reminder|send dues reminder|nudge all)", re.I), "SEND_REMINDER_ALL", 0.95),
    # Refund / deposit return
    (re.compile(r"(?:refund|return deposit|give back deposit|deposit back|repay deposit|disburse deposit)", re.I), "ADD_REFUND", 0.92),
    # Query pending refunds
    (re.compile(r"(?:pending refunds?|refunds? due|who needs? refund|deposits? to return|list refunds?)", re.I), "QUERY_REFUNDS", 0.91),
    # Room status — who's in a specific room
    (re.compile(r"(?:who(?:'?s| is) in room|room\s+\d+\s+(?:who|occupant|tenant|person)|who lives in|who stays in)", re.I), "ROOM_STATUS", 0.94),
    # Vacant rooms
    (re.compile(r"(?:vacant rooms?|empty rooms?|available rooms?|which rooms? (?:are |is )?(?:empty|free|vacant|available)|free rooms?|unoccupied)", re.I), "QUERY_VACANT_ROOMS", 0.94),
    # Occupancy overview
    (re.compile(r"(?:occupancy|how full|how many rooms|total rooms|occupied rooms|capacity|fill(?:ed)? (?:rooms?|up))", re.I), "QUERY_OCCUPANCY", 0.91),
    # Expiring tenancies / upcoming checkouts
    (re.compile(r"(?:expir(?:ing|es?)|agreements? ending|who(?:'s| is) leaving (?:this|next) month|upcoming checkout|checkout (?:this|next) month|notice (?:this|next) month|end of (?:lease|stay|tenancy))", re.I), "QUERY_EXPIRING", 0.92),
    # Checkins this month
    (re.compile(r"(?:who checked? ?in|new (?:arrivals?|tenants?|joinings?)|checkins? this month|joined this month|recent checkins?)", re.I), "QUERY_CHECKINS", 0.91),
    # Checkouts this month
    (re.compile(r"(?:who checked? ?out|checkouts? this month|who left|who vacated|exits? this month|move(?:d)? out this month)", re.I), "QUERY_CHECKOUTS", 0.91),
    # Expense query (before ADD_EXPENSE so "what did we spend" goes here)
    (re.compile(r"(?:what did we spend|expense report|total expenses?|expenses? (?:for|in|this|last)|how much (?:spent|spend|expense)|list expenses?|show expenses?)", re.I), "QUERY_EXPENSES", 0.91),
    # Log vacation / absence for tenant
    (re.compile(r"(?:(?:raj|kumar|tenant|room\s*\d+)\s+(?:on vacation|going home|on leave|absent|away)|log vacation|going home for|on leave from|will be away)", re.I), "LOG_VACATION", 0.89),
    # Report — general
    (re.compile(r"(?:report|summary|monthly|statement|accounts|P&L|profit|income|collection|total collected|financial)", re.I), "REPORT", 0.88),
    # Report — cash / UPI / general collection queries
    (re.compile(r"(?:how much (?:cash|upi|rent|money|total|was|is|have|did)|how much collect|cash collect|upi collect|total cash|total upi|what.?s collect|collect\w* in|collect\w* for|cash (?:for|in|this|last|march|feb|jan|dec|nov|oct|sep|aug|jul|jun|apr)|upi (?:for|in|this|last|march|feb|jan|dec|nov|oct|sep|aug|jul|jun|apr))", re.I), "REPORT", 0.92),
    # Salary / staff payment — must come BEFORE generic PAYMENT_LOG and ADD_EXPENSE
    (re.compile(r"(?:paid\s+salary|salary\s+paid|staff\s+salary|pay\s+salary|salary\s+to\s+\w+|wages?|disburse\w*\s+salary)", re.I), "ADD_EXPENSE", 0.92),
    # Expense (add new expense — must come before PAYMENT_LOG)
    (re.compile(r"(?:expense|electricity|water bill|internet bill|salary|maintenance cost|paid for|vendor)", re.I), "ADD_EXPENSE", 0.88),
    # Specific tenant query — "Raj dues", "Jeevan balance", "room 203 details"
    # Must come before QUERY_DUES. Two patterns:
    #   1. Named person + dues/balance/status
    #   2. balance/dues of <name>
    (re.compile(
        r"(?:"
        r"(?:balance|dues|details|status)\s+(?:of\s+|for\s+)?(?!(?:my|all|total|pending|outstanding|show|the|everyone|all|this|last)\b)([A-Za-z]{3,}(?:\s+[A-Za-z]+)?)"  # "balance of Raj"
        r"|"
        r"(?!(?:my|all|total|pending|outstanding|show|the|everyone)\b)([A-Z][a-z]{1,}(?:\s+[A-Z][a-z]+)?)\s+(?:balance|dues|status|details)"  # "Raj balance" (capital first)
        r"|"
        r"room\s+[\w-]+\s+(?:balance|dues|status|details|who|tenant|person|occupant)"  # "room 203 details"
        r"|"
        r"how\s+much\s+(?:does|did|is|has)\s+(?!my\b)(\w+)\s+(?:owe|paid|pay|balance)"  # "how much does Suresh owe"
        r"|"
        r"someone\s+from\s+room\s+[\w-]+"  # "someone from room 203"
        r")",
        re.I
    ), "QUERY_TENANT", 0.88),
    # Financial summary queries with "show" — must come before the QUERY_DUES "show" catch
    (re.compile(r"(?:show\s+(?:p&l|pl|profit|summary|report|financial|income|collection|accounts)|what\s+(?:is|was|are)?\s+(?:the\s+)?(?:financial|p&l|total\s+(?:income|collection|revenue))|how\s+much\s+(?:total|overall|did\s+we\s+collect|have\s+we\s+made))", re.I), "REPORT", 0.92),
    # Dues / pending — bulk queries (who hasn't paid, show pending, etc.)
    # NOT for single-tenant queries like "Raj dues" (those go to QUERY_TENANT above)
    (re.compile(r"(?:who\s+(?:hasn.?t|haven.?t|has\s+not|have\s+not)\s+paid|pending\s+(?:dues|list|rent|payments?)|list\s+(?:dues|pending|unpaid)|show\s+(?:all\s+)?(?:dues|pending|unpaid|outstanding)|baki|unpaid|not\s+paid|haven.?t\s+paid|dues\s+(?:list|for\s+(?:all|everyone|this|the))|all\s+(?:pending|dues|outstanding)|outstanding\s+(?:dues|rent|payments?))", re.I), "QUERY_DUES", 0.90),
    # Scheduled / date-specific checkout — "checkout on 31 May", "leaving on March 10"
    (re.compile(r"(?:check(?:ing)?\s*out|leaving|vacating|moving\s*out)\s+(?:on|by|from|before)\b|(?:scheduled?|planned?|expected)\s+checkout|checkout\s+(?:date|on|by)\b|(?:last\s+day|final\s+day)\s+(?:is|will\s+be|on)", re.I), "SCHEDULE_CHECKOUT", 0.93),
    # Notice period — "gave notice", "serving notice", "wants to leave"
    (re.compile(r"gave notice|giving notice|serving notice|notice period|plans? to (?:leave|vacate)|wants? to (?:leave|move)", re.I), "NOTICE_GIVEN", 0.92),
    # Immediate checkout (no date)
    (re.compile(r"(?:check.?out|vacate|vacating|leaving|exit|moving out)", re.I), "CHECKOUT", 0.95),
    # Add tenant
    (re.compile(r"(?:add tenant|new tenant|\bcheck.?in\b|joining|new room|onboard|register tenant)", re.I), "ADD_TENANT", 0.95),
    # Backdated check-in correction
    (re.compile(r"(?:update|correct|change|backdat)\w*\s+check.?in|checked?\s+in\s+on\b|actually\s+joined|joined\s+on\b", re.I), "UPDATE_CHECKIN", 0.94),
    # Rent change (permanent or from a month) — must come before RENT_DISCOUNT
    (re.compile(r"rent (?:is now|from\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|next)|change|increase|hike|reduce|decrease)|new rent|from \w+ rent|rent to \d", re.I), "RENT_CHANGE", 0.91),
    # One-time discount / concession / surcharge
    (re.compile(r"(?:concession|discount|waive|deduct|give.*less|less this month|reduce this month|extra charge|add.*surcharge|add.*electricity|add.*food charge)", re.I), "RENT_DISCOUNT", 0.90),
    # Add partner
    (re.compile(r"(?:add partner|add owner|add power user|new admin|give access)", re.I), "ADD_PARTNER", 0.97),
    # Reminder
    (re.compile(r"(?:remind|reminder|set reminder|alert|notify)", re.I), "REMINDER_SET", 0.90),
    # Complaint / maintenance — owner can log for a room
    (re.compile(r"(?:complaint|complain|issue|problem|not working|broken|leaking|repair|fix|tap|flush|bulb|fan|switch|wifi|wi-fi|internet|slow net|food (?:complaint|bad|issue|quality)|bed sheet|mattress|pillow|chair|table|shelf|almirah)", re.I), "COMPLAINT_REGISTER", 0.88),
    # PG rules & regulations
    (re.compile(r"(?:rules?|regulations?|pg rules?|what are the rules?|rules and regulations?|policy|policies|house rules?|show rules?)", re.I), "RULES", 0.91),
    # Help
    (re.compile(r"^(?:hi|hello|hey|help|menu|commands|start|hii|helo)\b", re.I), "HELP", 0.95),
    # Payment log — lowest priority so specific exceptions match first
    (re.compile(r"(?:paid|payment|received|collected|deposited|transferred|jama|diya)\s.*?\d", re.I), "PAYMENT_LOG", 0.92),
    (re.compile(r"\d[\d,k]+\s*(?:paid|payment|received|from|by)", re.I), "PAYMENT_LOG", 0.92),
]

# ── Tenant intents ────────────────────────────────────────────────────────────

_TENANT_RULES: list[tuple[re.Pattern, str, float]] = [
    # Checkout notice — tenant wanting to leave (check before HELP/balance)
    (re.compile(r"(?:i want to (?:leave|vacate|move out|checkout)|i(?:'m| am) leaving|(?:giving|serve|serving) notice|i(?:'ll| will) vacate|my last day|i want to give notice|notice to vacate|plan(?:ning)? to leave)", re.I), "CHECKOUT_NOTICE", 0.94),
    # Vacation / going home notice
    (re.compile(r"(?:going home|on vacation|on leave|going to (?:native|village|hometown)|will be (?:away|absent|back on)|coming back on|out of station)", re.I), "VACATION_NOTICE", 0.92),
    # Complaint / maintenance request
    (re.compile(r"(?:complaint|complain|issue|problem|not working|broken|leaking|repair|fix|tap|flush|bulb|fan|switch|wifi|wi-fi|internet|slow net|food (?:complaint|bad|issue|quality)|bed sheet|mattress|pillow|chair|table|shelf|almirah)", re.I), "COMPLAINT_REGISTER", 0.91),
    # Request receipt / payment proof
    (re.compile(r"(?:receipt|payment proof|payment (?:receipt|slip|confirmation)|send receipt|need receipt|my receipt)", re.I), "REQUEST_RECEIPT", 0.92),
    # Balance
    (re.compile(r"(?:my balance|how much|i owe|dues|pending|baki|outstanding)", re.I), "MY_BALANCE", 0.92),
    # Payment history
    (re.compile(r"(?:my payment|payment history|paid|transaction)", re.I), "MY_PAYMENTS", 0.90),
    # Receipt (already logged payments — list)
    (re.compile(r"(?:receipt|paid receipt)", re.I), "REQUEST_RECEIPT", 0.90),
    # My details
    (re.compile(r"(?:my room|my details|my rent|checkin|when did i|my info)", re.I), "MY_DETAILS", 0.88),
    # PG rules & regulations
    (re.compile(r"(?:rules?|regulations?|pg rules?|what are the rules?|rules and regulations?|policy|policies|house rules?|show rules?|what rules?)", re.I), "RULES", 0.91),
    # Help / greeting
    (re.compile(r"^(?:hi|hello|hey|help|menu|start)\b", re.I), "HELP", 0.95),
]

# ── Lead intents ──────────────────────────────────────────────────────────────

_LEAD_RULES: list[tuple[re.Pattern, str, float]] = [
    (re.compile(r"(?:price|rent|cost|how much|rates|charge|fee|monthly)", re.I), "ROOM_PRICE", 0.90),
    (re.compile(r"(?:available|vacancy|empty|free room|any room)", re.I), "AVAILABILITY", 0.90),
    (re.compile(r"(?:single|double|triple|sharing|private|attached|ac room|non.?ac)", re.I), "ROOM_TYPE", 0.88),
    (re.compile(r"(?:visit|tour|come see|show me|can i see|viewing|inspect)", re.I), "VISIT_REQUEST", 0.92),
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

    # "20 Feb", "20 February", "20 Feb 2026"
    m = re.search(
        r"(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*(?:\s+(\d{4}))?",
        text, re.I,
    )
    if m:
        month_num = _MONTHS.get(m.group(2)[:3].lower())
        if month_num:
            year = int(m.group(3)) if m.group(3) else None
            return _build(int(m.group(1)), month_num, year)

    # "Feb 20", "February 20", "March 10 2026"
    m = re.search(
        r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+(\d{1,2})(?:\s+(\d{4}))?",
        text, re.I,
    )
    if m:
        month_num = _MONTHS.get(m.group(1)[:3].lower())
        if month_num:
            year = int(m.group(3)) if m.group(3) else None
            return _build(int(m.group(2)), month_num, year)

    # DD/MM/YYYY or DD-MM-YYYY
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b", text)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if year < 100:
            year += 2000
        return _build(day, month, year)

    return None


def detect_intent(text: str, role: str) -> IntentResult:
    """
    Detect intent from message text based on caller role.
    Returns IntentResult with intent name, confidence, and extracted entities.
    """
    text = text.strip()

    if role in ("admin", "power_user", "key_user"):
        rules = _OWNER_RULES
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
            applies_to == "owner" and role not in ("admin", "power_user", "key_user")
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
        amount_match = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*(?:k\b)?", text, re.I)
    if amount_match:
        raw = amount_match.group(1).replace(",", "")
        multiplier = 1000 if "k" in text[amount_match.end():amount_match.end()+2].lower() else 1
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

    return entities
