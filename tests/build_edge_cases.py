"""
Build/rebuild tests/edge_test_cases.json:
  - Strips old // comments from the existing file
  - Appends 50 new test cases (tenant lifecycle, financial prorate,
    security firewall, data integrity, intent feedback)
"""
import json, re, pathlib

ROOT = pathlib.Path(__file__).parent
SRC  = ROOT / "edge_test_cases.json"

# ── Load & clean existing file ─────────────────────────────────────────────
text = SRC.read_text(encoding="utf-8")
text = re.sub(r"\s*//[^\n]*", "", text)
data = json.loads(text)
print(f"Loaded {len(data)} existing cases")

# ── New test cases ─────────────────────────────────────────────────────────
NEW = [
  # ── TENANT LIFECYCLE ────────────────────────────────────────────────────
  {"id": "E201", "name": "TC-01: ADD_TENANT bare trigger", "category": "tenant_lifecycle",
   "turns": [{"role": "admin", "input": "add new tenant",
     "expected_intent": "ADD_TENANT", "expected_state": "collecting",
     "reply_must_contain": ["Name", "Phone", "Room", "Rent"],
     "reply_must_not_contain": ["error", "traceback"]}]},

  {"id": "E202", "name": "TC-01b: ADD_TENANT with name and phone", "category": "tenant_lifecycle",
   "turns": [{"role": "admin", "input": "add tenant Rahul Sharma 9876543210",
     "expected_intent": "ADD_TENANT", "expected_state": "collecting",
     "reply_must_contain": ["Name", "Room", "Deposit"],
     "reply_must_not_contain": ["error", "traceback"]}]},

  {"id": "E203", "name": "TC-01c: ADD_TENANT - warns if tenant already active", "category": "tenant_lifecycle",
   "turns": [{"role": "admin", "input": "add Ankit Kumar",
     "expected_intent": "ADD_TENANT", "expected_state": "collecting",
     "reply_must_contain": ["active"],
     "reply_must_not_contain": ["error", "traceback"]}]},

  {"id": "E204", "name": "TC-01d: START_ONBOARDING with name and phone", "category": "tenant_lifecycle",
   "turns": [{"role": "admin", "input": "start onboarding Ravi 9001234567",
     "expected_intent": "START_ONBOARDING", "expected_state": "idle",
     "reply_must_contain": ["9001234567", "WhatsApp"],
     "reply_must_not_contain": ["error", "traceback"]}]},

  {"id": "E205", "name": "TC-04: CHECKOUT by tenant name", "category": "tenant_lifecycle",
   "turns": [{"role": "admin", "input": "checkout Ankit Kumar",
     "expected_intent": "CHECKOUT", "expected_state": "confirming",
     "reply_must_contain": ["Confirm", "Ankit"],
     "reply_must_not_contain": ["error", "traceback"]}]},

  {"id": "E206", "name": "TC-04b: CHECKOUT by room number", "category": "tenant_lifecycle",
   "turns": [{"role": "admin", "input": "checkout room 203",
     "expected_intent": "CHECKOUT", "expected_state": "confirming",
     "reply_must_contain": ["Confirm"],
     "reply_must_not_contain": ["error", "traceback"]}]},

  {"id": "E207", "name": "TC-04c: RECORD_CHECKOUT checklist start", "category": "tenant_lifecycle",
   "turns": [{"role": "admin", "input": "record checkout Ankit",
     "expected_intent": "RECORD_CHECKOUT", "expected_state": "pending",
     "reply_must_contain": ["cupboard", "key"],
     "reply_must_not_contain": ["error", "traceback"]}]},

  {"id": "E208", "name": "TC-05: SCHEDULE_CHECKOUT - future date", "category": "tenant_lifecycle",
   "turns": [{"role": "admin", "input": "checkout Ankit on 30 Jun",
     "expected_intent": "SCHEDULE_CHECKOUT", "expected_state": "confirming",
     "reply_must_contain": ["Jun", "active"],
     "reply_must_not_contain": ["error", "traceback"]}]},

  {"id": "E209", "name": "TC-06: CHECKOUT - unknown tenant returns no-match", "category": "tenant_lifecycle",
   "turns": [{"role": "admin", "input": "checkout Mukesh XYZ 99999",
     "expected_intent": "CHECKOUT", "expected_state": "idle",
     "reply_must_contain": [],
     "reply_must_not_contain": ["error", "traceback", "exception"]}]},

  {"id": "E210", "name": "TC-07: LOG_VACATION for active tenant", "category": "tenant_lifecycle",
   "turns": [{"role": "admin", "input": "Ankit on vacation from 15 Apr to 30 Apr",
     "expected_intent": "LOG_VACATION", "expected_state": "confirming",
     "reply_must_contain": ["vacation", "Ankit"],
     "reply_must_not_contain": ["error", "traceback"]}]},

  {"id": "E211", "name": "TC-03: UPDATE_CHECKIN - correct checkin date", "category": "tenant_lifecycle",
   "turns": [{"role": "admin", "input": "Ankit checked in on 10 Jan",
     "expected_intent": "UPDATE_CHECKIN", "expected_state": "confirming",
     "reply_must_contain": ["Update", "10 Jan"],
     "reply_must_not_contain": ["error", "traceback"]}]},

  {"id": "E212", "name": "TC-08: NOTICE_GIVEN today (assumed date)", "category": "tenant_lifecycle",
   "turns": [{"role": "admin", "input": "Ankit gave notice today",
     "expected_intent": "NOTICE_GIVEN", "expected_state": "confirming",
     "reply_must_contain": ["Notice", "Last day"],
     "reply_must_not_contain": ["error", "traceback"]}]},

  {"id": "E213", "name": "TC-08b: NOTICE_GIVEN specific date - late notice forfeits deposit", "category": "tenant_lifecycle",
   "turns": [{"role": "admin", "input": "Ankit gave notice on 15th March",
     "expected_intent": "NOTICE_GIVEN", "expected_state": "confirming",
     "reply_must_contain": ["deposit"],
     "reply_must_not_contain": ["error", "traceback"]}]},

  {"id": "E214", "name": "QUERY_CHECKINS: who checked in this month", "category": "tenant_lifecycle",
   "turns": [{"role": "admin", "input": "who checked in this month",
     "expected_intent": "QUERY_CHECKINS", "expected_state": "idle",
     "reply_must_contain": [],
     "reply_must_not_contain": ["error", "traceback"]}]},

  {"id": "E215", "name": "QUERY_CHECKOUTS: who checked out this month", "category": "tenant_lifecycle",
   "turns": [{"role": "admin", "input": "who checked out this month",
     "expected_intent": "QUERY_CHECKOUTS", "expected_state": "idle",
     "reply_must_contain": [],
     "reply_must_not_contain": ["error", "traceback"]}]},

  # ── FINANCIAL PRORATE & ADVANCE ─────────────────────────────────────────
  {"id": "E221", "name": "TC-09: PAYMENT_LOG - booking advance payment", "category": "financial_prorate",
   "turns": [{"role": "admin", "input": "Ankit paid 5000 advance upi",
     "expected_intent": "PAYMENT_LOG", "expected_state": "confirming",
     "reply_must_contain": ["5,000", "Ankit"],
     "reply_must_not_contain": ["error", "traceback"]}]},

  {"id": "E222", "name": "TC-10: QUERY_TENANT balance after advance paid", "category": "financial_prorate",
   "turns": [{"role": "admin", "input": "Ankit balance",
     "expected_intent": "QUERY_TENANT", "expected_state": "idle",
     "reply_must_contain": [],
     "reply_must_not_contain": ["error", "traceback"]}]},

  {"id": "E223", "name": "TC-09b: Pro-rata query for mid-month checkin", "category": "financial_prorate",
   "turns": [{"role": "admin", "input": "what is pro rata for Ankit",
     "expected_intent": "QUERY_TENANT", "expected_state": "idle",
     "reply_must_contain": [],
     "reply_must_not_contain": ["error", "traceback"]}]},

  {"id": "E224", "name": "TC-09c: Checkout reply shows prorated settlement", "category": "financial_prorate",
   "turns": [{"role": "admin", "input": "checkout Ankit today",
     "expected_intent": "CHECKOUT", "expected_state": "confirming",
     "reply_must_contain": ["deposit", "Ankit"],
     "reply_must_not_contain": ["error", "traceback"]}]},

  {"id": "E225", "name": "TC-11: RENT_CHANGE - first-month concession 1000", "category": "financial_prorate",
   "turns": [{"role": "admin", "input": "give Ankit 1000 discount this month",
     "expected_intent": "RENT_CHANGE", "expected_state": "confirming",
     "reply_must_contain": ["1,000"],
     "reply_must_not_contain": ["error", "traceback"]}]},

  {"id": "E226", "name": "TC-11b: RENT_CHANGE permanent rent increase", "category": "financial_prorate",
   "turns": [{"role": "admin", "input": "change Ankit rent to 16000 from next month",
     "expected_intent": "RENT_CHANGE", "expected_state": "confirming",
     "reply_must_contain": ["16,000"],
     "reply_must_not_contain": ["error", "traceback"]}]},

  {"id": "E227", "name": "TC-12: ADD_EXPENSE maintenance 5000 paid to plumber", "category": "financial_prorate",
   "turns": [{"role": "admin", "input": "maintenance 5000 paid to plumber",
     "expected_intent": "ADD_EXPENSE", "expected_state": "confirming",
     "reply_must_contain": ["5,000"],
     "reply_must_not_contain": ["error", "traceback"]}]},

  {"id": "E228", "name": "TC-12b: ADD_EXPENSE WiFi bill auto-category", "category": "financial_prorate",
   "turns": [{"role": "admin", "input": "wifi bill 2500",
     "expected_intent": "ADD_EXPENSE", "expected_state": "confirming",
     "reply_must_contain": ["2,500"],
     "reply_must_not_contain": ["error", "traceback"]}]},

  {"id": "E229", "name": "TC-13: PAYMENT_LOG - overpayment above monthly rent", "category": "financial_prorate",
   "turns": [{"role": "admin", "input": "Ankit paid 20000 upi",
     "expected_intent": "PAYMENT_LOG", "expected_state": "confirming",
     "reply_must_contain": ["20,000"],
     "reply_must_not_contain": ["error", "traceback"]}]},

  {"id": "E230", "name": "TC-10b: First month payment after deducting 5000 advance", "category": "financial_prorate",
   "turns": [{"role": "admin", "input": "Ankit first month 10500 cash after 5000 advance",
     "expected_intent": "PAYMENT_LOG", "expected_state": "confirming",
     "reply_must_contain": ["10,500"],
     "reply_must_not_contain": ["error", "traceback"]}]},

  {"id": "E231", "name": "ADD_EXPENSE - electricity bill auto-category", "category": "financial_prorate",
   "turns": [{"role": "admin", "input": "electricity 8000",
     "expected_intent": "ADD_EXPENSE", "expected_state": "confirming",
     "reply_must_contain": ["8,000"],
     "reply_must_not_contain": ["error", "traceback"]}]},

  {"id": "E232", "name": "ADD_EXPENSE - cook salary auto-category cash", "category": "financial_prorate",
   "turns": [{"role": "admin", "input": "cook salary 12000 cash",
     "expected_intent": "ADD_EXPENSE", "expected_state": "confirming",
     "reply_must_contain": ["12,000"],
     "reply_must_not_contain": ["error", "traceback"]}]},

  {"id": "E233", "name": "QUERY_DUES - filter by specific month", "category": "financial_prorate",
   "turns": [{"role": "admin", "input": "who has not paid for March",
     "expected_intent": "QUERY_DUES", "expected_state": "idle",
     "reply_must_contain": [],
     "reply_must_not_contain": ["error", "traceback"]}]},

  {"id": "E234", "name": "REPORT - show rent collected this month", "category": "financial_prorate",
   "turns": [{"role": "admin", "input": "show rent collected this month",
     "expected_intent": "REPORT", "expected_state": "idle",
     "reply_must_contain": [],
     "reply_must_not_contain": ["error", "traceback"]}]},

  {"id": "E235", "name": "QUERY_EXPIRING - upcoming checkout notices", "category": "financial_prorate",
   "turns": [{"role": "admin", "input": "who is leaving this month",
     "expected_intent": "QUERY_EXPIRING", "expected_state": "idle",
     "reply_must_contain": [],
     "reply_must_not_contain": ["error", "traceback"]}]},

  # ── SECURITY FIREWALL ────────────────────────────────────────────────────
  {"id": "E236", "name": "TC-14: Tenant cannot log payment for another tenant", "category": "security_firewall",
   "turns": [{"role": "tenant", "input": "Ankit paid 15000",
     "expected_intent": "UNKNOWN", "expected_state": "idle",
     "reply_must_contain": [],
     "reply_must_not_contain": ["error", "traceback", "logged", "confirmed"]}]},

  {"id": "E237", "name": "TC-15: Tenant cannot see all-tenant dues list", "category": "security_firewall",
   "turns": [{"role": "tenant", "input": "who has not paid",
     "expected_intent": "UNKNOWN", "expected_state": "idle",
     "reply_must_contain": [],
     "reply_must_not_contain": ["error", "traceback"]}]},

  {"id": "E238", "name": "Lead cannot access financial records", "category": "security_firewall",
   "turns": [{"role": "lead", "input": "show me all tenant payments",
     "expected_intent": "UNKNOWN", "expected_state": "idle",
     "reply_must_contain": [],
     "reply_must_not_contain": ["payments", "Rs.", "dues", "error", "traceback"]}]},

  {"id": "E239", "name": "Lead cannot access WiFi password", "category": "security_firewall",
   "turns": [{"role": "lead", "input": "what is the wifi password",
     "expected_intent": "UNKNOWN", "expected_state": "idle",
     "reply_must_contain": [],
     "reply_must_not_contain": ["password", "ssid", "error"]}]},

  {"id": "E240", "name": "Lead asking room price - allowed (sales path)", "category": "security_firewall",
   "turns": [{"role": "lead", "input": "how much is the rent",
     "expected_intent": "ROOM_PRICE", "expected_state": "idle",
     "reply_must_contain": [],
     "reply_must_not_contain": ["error", "traceback"]}]},

  {"id": "E241", "name": "TC-14b: key_user cannot add partner (admin-only)", "category": "security_firewall",
   "turns": [{"role": "key_user", "input": "add partner 9001234567 Suresh",
     "expected_intent": "ADD_PARTNER", "expected_state": "idle",
     "reply_must_contain": ["admin"],
     "reply_must_not_contain": ["error", "traceback"]}]},

  {"id": "E242", "name": "TC-15b: Tenant can see own balance (MY_BALANCE)", "category": "security_firewall",
   "turns": [{"role": "tenant", "input": "my balance",
     "expected_intent": "MY_BALANCE", "expected_state": "idle",
     "reply_must_contain": [],
     "reply_must_not_contain": ["error", "traceback"]}]},

  # ── DATA INTEGRITY ───────────────────────────────────────────────────────
  {"id": "E243", "name": "TC-08h: Duplicate payment flagged on re-log", "category": "data_integrity",
   "turns": [
     {"role": "admin", "input": "Ankit paid 15000 upi",
      "expected_intent": "PAYMENT_LOG", "expected_state": "confirming",
      "reply_must_contain": ["15,000"], "reply_must_not_contain": ["error"]},
     {"role": "admin", "input": "yes",
      "expected_intent": "CONFIRMATION", "expected_state": "idle",
      "reply_must_contain": [], "reply_must_not_contain": ["error"]},
     {"role": "admin", "input": "Ankit paid 15000 upi",
      "expected_intent": "PAYMENT_LOG", "expected_state": "confirming",
      "reply_must_contain": ["already"], "reply_must_not_contain": ["error"]}
   ]},

  {"id": "E244", "name": "VOID_PAYMENT flow start by name", "category": "data_integrity",
   "turns": [{"role": "admin", "input": "void payment Ankit",
     "expected_intent": "VOID_PAYMENT", "expected_state": "collecting",
     "reply_must_contain": [],
     "reply_must_not_contain": ["error", "traceback"]}]},

  {"id": "E245", "name": "Checkout date before checkin is blocked", "category": "data_integrity",
   "turns": [
     {"role": "admin", "input": "checkout Ankit on 1 Jan 2000",
      "expected_intent": "CHECKOUT", "expected_state": "confirming",
      "reply_must_contain": [], "reply_must_not_contain": ["error"]},
     {"role": "admin", "input": "1",
      "expected_intent": "CONFIRMATION", "expected_state": "idle",
      "reply_must_contain": ["before", "checkin"], "reply_must_not_contain": ["error"]}
   ]},

  {"id": "E246", "name": "ADD_REFUND after checkout - deposit return", "category": "data_integrity",
   "turns": [{"role": "admin", "input": "refund 10000 to Ankit",
     "expected_intent": "ADD_REFUND", "expected_state": "confirming",
     "reply_must_contain": [],
     "reply_must_not_contain": ["error", "traceback"]}]},

  {"id": "E247", "name": "ADD_REFUND bare - missing name asks for clarification", "category": "data_integrity",
   "turns": [{"role": "admin", "input": "refund 8000",
     "expected_intent": "ADD_REFUND", "expected_state": "collecting",
     "reply_must_contain": [],
     "reply_must_not_contain": ["error", "traceback"]}]},

  {"id": "E248", "name": "PAYMENT_LOG with explicit period month label", "category": "data_integrity",
   "turns": [{"role": "admin", "input": "Ankit paid 15000 for March upi",
     "expected_intent": "PAYMENT_LOG", "expected_state": "confirming",
     "reply_must_contain": ["15,000"],
     "reply_must_not_contain": ["error", "traceback"]}]},

  {"id": "E249", "name": "PAYMENT_LOG with payment date override", "category": "data_integrity",
   "turns": [{"role": "admin", "input": "Ankit paid 15000 on 5 March upi",
     "expected_intent": "PAYMENT_LOG", "expected_state": "confirming",
     "reply_must_contain": ["15,000"],
     "reply_must_not_contain": ["error", "traceback"]}]},

  # ── TC-16/17: Intent Feedback Loop ──────────────────────────────────────
  {"id": "E250", "name": "TC-16: Unhandled intent logged to PendingLearning", "category": "intent_feedback",
   "turns": [{"role": "admin", "input": "can I bring my pet iguana to the PG",
     "expected_intent": "UNKNOWN", "expected_state": "idle",
     "reply_must_contain": [],
     "reply_must_not_contain": ["error", "traceback", "iguana"]}]},
]

data.extend(NEW)

# Print summary
cats: dict = {}
for item in data:
    cats[item["category"]] = cats.get(item["category"], 0) + 1
print(f"Total: {len(data)} test cases")
for k, v in sorted(cats.items()):
    print(f"  {k}: {v}")

SRC.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
print("Written to tests/edge_test_cases.json")
