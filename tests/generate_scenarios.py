"""
tests/generate_scenarios.py
============================
Generates tests/scenarios_500.json — the full 500-scenario test suite.

Run once to (re-)generate the JSON:
    python tests/generate_scenarios.py

The generated file is consumed by run_500.py.
"""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

OUT = Path(__file__).parent / "scenarios_500.json"

# ── helpers ───────────────────────────────────────────────────────────────────

def sc(id_, worker, intent, role, message, expected_intent=None,
       confidence=0.80, reply_contains=None, tags=None):
    return {
        "id": id_,
        "worker": worker,
        "intent": intent,
        "role": role,
        "phone": role,                          # resolved by runner
        "message": message,
        "expected_intent": expected_intent or intent,
        "min_confidence": confidence,
        "reply_contains": reply_contains or [],
        "tags": tags or [],
    }

A = lambda id_, intent, msg, role="admin", **kw: sc(
    id_, "AccountWorker", intent, role, msg, **kw)
O = lambda id_, intent, msg, role="admin", **kw: sc(
    id_, "OwnerWorker", intent, role, msg, **kw)
T = lambda id_, intent, msg, **kw: sc(
    id_, "TenantWorker", intent, "tenant", msg, **kw)
L = lambda id_, intent, msg, **kw: sc(
    id_, "LeadWorker", intent, "lead", msg, **kw)
E = lambda id_, worker, intent, role, msg, **kw: sc(
    id_, worker, intent, role, msg, **kw)

# ─────────────────────────────────────────────────────────────────────────────
# ACCOUNT WORKER  (A001 – A135)
# ─────────────────────────────────────────────────────────────────────────────

scenarios = [

# ── PAYMENT_LOG  A001-A015 ────────────────────────────────────────────────────
A("A001","PAYMENT_LOG","Raj paid 15000 upi",tags=["basic","financial"]),
A("A002","PAYMENT_LOG","Arjun 12000 cash",tags=["basic","financial"]),
A("A003","PAYMENT_LOG","received 10000 from Kumar bank transfer",tags=["financial"]),
A("A004","PAYMENT_LOG","Suresh paid 7500",tags=["basic","financial"]),
A("A005","PAYMENT_LOG","15000 from Raj upi",tags=["financial"]),
A("A006","PAYMENT_LOG","Deepak paid rent 11000 cheque",tags=["financial"]),
A("A007","PAYMENT_LOG","Mohan paid 9000 phonepe",tags=["financial"]),
A("A008","PAYMENT_LOG","Ravi gave 13000 cash",tags=["financial"]),
A("A009","PAYMENT_LOG","log payment Sanjay 8500",tags=["financial"]),
A("A010","PAYMENT_LOG","Priya paid 6000 neft",tags=["financial"]),
A("A011","PAYMENT_LOG","Anand 14000 imps",tags=["financial"]),
A("A012","PAYMENT_LOG","payment received from Rahul 10500 upi",tags=["financial"]),
A("A013","PAYMENT_LOG","Kumar paid 7000 paytm",tags=["financial"]),
A("A014","PAYMENT_LOG","Mahesh paid 12500 bank",tags=["financial"]),
A("A015","PAYMENT_LOG","Vikram ko payment mil gaya 8000 gpay",tags=["financial","hinglish"]),

# ── QUERY_DUES  A016-A025 ─────────────────────────────────────────────────────
A("A016","QUERY_DUES","who hasn't paid",tags=["basic","query"]),
A("A017","QUERY_DUES","dues this month",tags=["basic","query"]),
A("A018","QUERY_DUES","defaulters list",tags=["query"]),
A("A019","QUERY_DUES","who owes money",tags=["query"]),
A("A020","QUERY_DUES","show pending payments",tags=["query"]),
A("A021","QUERY_DUES","outstanding dues",tags=["query"]),
A("A022","QUERY_DUES","who hasn't paid March",tags=["query"]),
A("A023","QUERY_DUES","unpaid rent this month",tags=["query"]),
A("A024","QUERY_DUES","list of defaulters",tags=["query"]),
A("A025","QUERY_DUES","dues March 2026",tags=["query"]),

# ── QUERY_TENANT  A026-A037 ───────────────────────────────────────────────────
A("A026","QUERY_TENANT","Raj balance",tags=["basic","query"]),
A("A027","QUERY_TENANT","show Arjun's account",tags=["query"]),
A("A028","QUERY_TENANT","Vikram details",tags=["query"]),
A("A029","QUERY_TENANT","how much does Kumar owe",tags=["query"]),
A("A030","QUERY_TENANT","check Suresh balance",tags=["query"]),
A("A031","QUERY_TENANT","Deepak ka balance",tags=["query","hinglish"]),
A("A032","QUERY_TENANT","Mohan outstanding",tags=["query"]),
A("A033","QUERY_TENANT","Ravi payment history",tags=["query"]),
A("A034","QUERY_TENANT","balance for Sanjay",tags=["query"]),
A("A035","QUERY_TENANT","Anand account statement",tags=["query"]),
A("A036","QUERY_TENANT","Priya total dues",tags=["query"]),
A("A037","QUERY_TENANT","tell me Rahul balance",tags=["query"]),

# ── ADD_EXPENSE  A038-A049 ────────────────────────────────────────────────────
A("A038","ADD_EXPENSE","maintenance 5000 cash",tags=["basic","financial"]),
A("A039","ADD_EXPENSE","electricity bill 3000 upi",tags=["financial"]),
A("A040","ADD_EXPENSE","water bill 800 cash",tags=["financial"]),
A("A041","ADD_EXPENSE","cleaning 2000 bank",tags=["financial"]),
A("A042","ADD_EXPENSE","plumber 1500 cash",tags=["financial"]),
A("A043","ADD_EXPENSE","electrician 2500 upi",tags=["financial"]),
A("A044","ADD_EXPENSE","repairs 7000 cheque",tags=["financial"]),
A("A045","ADD_EXPENSE","furniture 15000 bank",tags=["financial"]),
A("A046","ADD_EXPENSE","food supplies 8000 cash",tags=["financial"]),
A("A047","ADD_EXPENSE","internet 2000 upi",tags=["financial"]),
A("A048","ADD_EXPENSE","generator maintenance 4000 cash",tags=["financial"]),
A("A049","ADD_EXPENSE","add expense security guard salary 9000 bank",tags=["financial"]),

# ── QUERY_EXPENSES  A050-A057 ─────────────────────────────────────────────────
A("A050","QUERY_EXPENSES","expenses this month",tags=["basic","query"]),
A("A051","QUERY_EXPENSES","show expenses",tags=["query"]),
A("A052","QUERY_EXPENSES","expense breakdown",tags=["query"]),
A("A053","QUERY_EXPENSES","monthly expenses",tags=["query"]),
A("A054","QUERY_EXPENSES","what did we spend",tags=["query"]),
A("A055","QUERY_EXPENSES","expense summary",tags=["query"]),
A("A056","QUERY_EXPENSES","March expenses",tags=["query"]),
A("A057","QUERY_EXPENSES","total expenses",tags=["query"]),

# ── REPORT  A058-A065 ─────────────────────────────────────────────────────────
A("A058","REPORT","monthly report",tags=["basic","query"]),
A("A059","REPORT","summary",tags=["query"]),
A("A060","REPORT","show monthly summary",tags=["query"]),
A("A061","REPORT","financial report",tags=["query"]),
A("A062","REPORT","March report",tags=["query"]),
A("A063","REPORT","generate report",tags=["query"]),
A("A064","REPORT","revenue summary",tags=["query"]),
A("A065","REPORT","occupancy report",tags=["query"]),

# ── RENT_CHANGE  A066-A075 ────────────────────────────────────────────────────
A("A066","RENT_CHANGE","change rent for room 205 to 12000",tags=["basic","operational"]),
A("A067","RENT_CHANGE","update rent room 204 to 11000",tags=["operational"]),
A("A068","RENT_CHANGE","room 101 rent change to 9000",tags=["operational"]),
A("A069","RENT_CHANGE","increase rent room 301 to 13000",tags=["operational"]),
A("A070","RENT_CHANGE","new rent for room 202 is 10500",tags=["operational"]),
A("A071","RENT_CHANGE","room 201 rent updated to 10000",tags=["operational"]),
A("A072","RENT_CHANGE","revise rent for room 102 to 8500",tags=["operational"]),
A("A073","RENT_CHANGE","room G15 rent 12000 from next month",tags=["operational"]),
A("A074","RENT_CHANGE","change room 105 rent to 9500",tags=["operational"]),
A("A075","RENT_CHANGE","set rent room 203 to 11500",tags=["operational"]),

# ── RENT_DISCOUNT  A076-A083 ──────────────────────────────────────────────────
A("A076","RENT_DISCOUNT","give Raj 500 discount",tags=["basic","financial"]),
A("A077","RENT_DISCOUNT","discount 1000 for Arjun",tags=["financial"]),
A("A078","RENT_DISCOUNT","Vikram rent discount 750",tags=["financial"]),
A("A079","RENT_DISCOUNT","reduce Kumar's rent by 500 this month",tags=["financial"]),
A("A080","RENT_DISCOUNT","one time discount Suresh 1000",tags=["financial"]),
A("A081","RENT_DISCOUNT","Deepak ko 500 discount do",tags=["financial","hinglish"]),
A("A082","RENT_DISCOUNT","waive 750 for Mohan this month",tags=["financial"]),
A("A083","RENT_DISCOUNT","Ravi discount 500",tags=["financial"]),

# ── VOID_PAYMENT  A084-A091 ───────────────────────────────────────────────────
A("A084","VOID_PAYMENT","void payment 42",tags=["basic","financial"]),
A("A085","VOID_PAYMENT","cancel payment 15",tags=["financial"]),
A("A086","VOID_PAYMENT","payment 23 was wrong void it",tags=["financial"]),
A("A087","VOID_PAYMENT","reverse payment id 8",tags=["financial"]),
A("A088","VOID_PAYMENT","mark payment 67 as void",tags=["financial"]),
A("A089","VOID_PAYMENT","payment 12 incorrect cancel",tags=["financial"]),
A("A090","VOID_PAYMENT","payment 45 cancel karo",tags=["financial","hinglish"]),
A("A091","VOID_PAYMENT","void transaction 88",tags=["financial"]),

# ── ADD_REFUND  A092-A099 ─────────────────────────────────────────────────────
A("A092","ADD_REFUND","refund 5000 to Raj",tags=["basic","financial"]),
A("A093","ADD_REFUND","return deposit 10000 Arjun",tags=["financial"]),
A("A094","ADD_REFUND","Vikram deposit refund 8000",tags=["financial"]),
A("A095","ADD_REFUND","add refund Kumar 7500",tags=["financial"]),
A("A096","ADD_REFUND","security deposit back to Suresh 15000",tags=["financial"]),
A("A097","ADD_REFUND","refund Deepak 3000",tags=["financial"]),
A("A098","ADD_REFUND","pay back deposit Mohan 12000",tags=["financial"]),
A("A099","ADD_REFUND","Ravi ko deposit wapas karo 6000",tags=["financial","hinglish"]),

# ── QUERY_REFUNDS  A100-A105 ──────────────────────────────────────────────────
A("A100","QUERY_REFUNDS","show refunds",tags=["basic","query"]),
A("A101","QUERY_REFUNDS","refund history",tags=["query"]),
A("A102","QUERY_REFUNDS","list all refunds",tags=["query"]),
A("A103","QUERY_REFUNDS","Raj refunds",tags=["query"]),
A("A104","QUERY_REFUNDS","refund summary",tags=["query"]),
A("A105","QUERY_REFUNDS","refunds this month",tags=["query"]),

# ── power_user role — financial intents A106-A115 ─────────────────────────────
A("A106","PAYMENT_LOG","Raj paid 15000 upi",role="power_user",tags=["role","financial"]),
A("A107","PAYMENT_LOG","Anand 9000 cash",role="power_user",tags=["role","financial"]),
A("A108","QUERY_DUES","who hasn't paid",role="power_user",tags=["role","query"]),
A("A109","QUERY_TENANT","Raj balance",role="power_user",tags=["role","query"]),
A("A110","ADD_EXPENSE","maintenance 4000 cash",role="power_user",tags=["role","financial"]),
A("A111","REPORT","monthly report",role="power_user",tags=["role","query"]),
A("A112","QUERY_EXPENSES","expenses this month",role="power_user",tags=["role","query"]),
A("A113","RENT_CHANGE","change rent for room 201 to 11000",role="power_user",tags=["role","operational"]),
A("A114","ADD_REFUND","refund 5000 to Kumar",role="power_user",tags=["role","financial"]),
A("A115","QUERY_REFUNDS","show refunds",role="power_user",tags=["role","query"]),

# ── key_user role A116-A122 ───────────────────────────────────────────────────
A("A116","PAYMENT_LOG","Raj paid 15000 upi",role="key_user",tags=["role","financial"]),
A("A117","PAYMENT_LOG","Suresh 8000 cash",role="key_user",tags=["role","financial"]),
A("A118","QUERY_TENANT","Raj balance",role="key_user",tags=["role","query"]),
A("A119","QUERY_DUES","who hasn't paid",role="key_user",tags=["role","query"]),
A("A120","ADD_EXPENSE","plumber 1500 cash",role="key_user",tags=["role","financial"]),
A("A121","QUERY_EXPENSES","expenses this month",role="key_user",tags=["role","query"]),
A("A122","REPORT","monthly report",role="key_user",tags=["role","query"]),

# ── edge / ambiguous AccountWorker A123-A135 ──────────────────────────────────
A("A123","PAYMENT_LOG","Raj ₹15000 upi",tags=["edge","financial"]),
A("A124","PAYMENT_LOG","💰 15000 Raj gpay",tags=["edge","financial"]),
A("A125","QUERY_TENANT","Raj balance",expected_intent="QUERY_TENANT",confidence=0.60,tags=["edge","ambiguous"]),
A("A126","ADD_EXPENSE","5000 cash maintenance",tags=["edge","financial"]),
A("A127","REPORT","show stats",expected_intent="REPORT",confidence=0.60,tags=["edge","ambiguous"]),
A("A128","PAYMENT_LOG","Deepak payment received",expected_intent="PAYMENT_LOG",confidence=0.55,tags=["edge","partial"]),
A("A129","QUERY_DUES","who owes",tags=["edge","query"]),
A("A130","RENT_CHANGE","room 205 rent 12000",tags=["edge","operational"]),
A("A131","VOID_PAYMENT","payment 42 galat tha cancel",tags=["edge","hinglish"]),
A("A132","ADD_EXPENSE","maintenance 5k cash",tags=["edge","financial"]),
A("A133","QUERY_TENANT","Raj ka paise",tags=["edge","hinglish"]),
A("A134","PAYMENT_LOG","Arjun ne diya 12000",tags=["edge","hinglish"]),
A("A135","QUERY_DUES","backlogs",expected_intent="QUERY_DUES",confidence=0.55,tags=["edge","ambiguous"]),

# ─────────────────────────────────────────────────────────────────────────────
# OWNER WORKER  (O001 – O160)
# ─────────────────────────────────────────────────────────────────────────────

# ── ADD_TENANT  O001-O008 ─────────────────────────────────────────────────────
O("O001","ADD_TENANT","add tenant Arjun 9876543210 room 204",tags=["basic","operational"]),
O("O002","ADD_TENANT","new tenant Priya 8765432109 room 101",tags=["operational"]),
O("O003","ADD_TENANT","add tenant Vikram room 202",tags=["operational"]),
O("O004","ADD_TENANT","check in Kumar 7654321098 in room 301",tags=["operational"]),
O("O005","ADD_TENANT","new admission Suresh 9988776655",tags=["operational"]),
O("O006","ADD_TENANT","admit Deepak 9123456789 room 205",tags=["operational"]),
O("O007","ADD_TENANT","add new tenant Mohan 9012345678",tags=["operational"]),
O("O008","ADD_TENANT","tenant Ravi 8901234567 room 102",tags=["operational"]),

# ── START_ONBOARDING  O009-O014 ───────────────────────────────────────────────
O("O009","START_ONBOARDING","start onboarding for Arjun 9876543210",tags=["basic","flow"]),
O("O010","START_ONBOARDING","begin kyc Priya 8765432109",tags=["flow"]),
O("O011","START_ONBOARDING","onboarding for Vikram 9876543210",tags=["flow"]),
O("O012","START_ONBOARDING","start registration Kumar 7654321098",tags=["flow"]),
O("O013","START_ONBOARDING","onboard Suresh 9988776655",tags=["flow"]),
O("O014","START_ONBOARDING","begin KYC for Deepak",tags=["flow"]),

# ── UPDATE_CHECKIN  O015-O020 ─────────────────────────────────────────────────
O("O015","UPDATE_CHECKIN","checkin date for Raj is March 1",tags=["basic","operational"]),
O("O016","UPDATE_CHECKIN","update checkin Arjun March 5",tags=["operational"]),
O("O017","UPDATE_CHECKIN","Vikram joined on 1st March",tags=["operational"]),
O("O018","UPDATE_CHECKIN","Kumar checkin was 15 Feb",tags=["operational"]),
O("O019","UPDATE_CHECKIN","correct checkin date Suresh 10 March",tags=["operational"]),
O("O020","UPDATE_CHECKIN","Deepak checkin March 20",tags=["operational"]),

# ── CHECKOUT  O021-O028 ───────────────────────────────────────────────────────
O("O021","CHECKOUT","Raj is leaving",tags=["basic","operational"]),
O("O022","CHECKOUT","checkout Arjun",tags=["operational"]),
O("O023","CHECKOUT","Vikram is vacating",tags=["operational"]),
O("O024","CHECKOUT","Kumar is moving out",tags=["operational"]),
O("O025","CHECKOUT","Suresh leaving at end of month",tags=["operational"]),
O("O026","CHECKOUT","Deepak checkout",tags=["operational"]),
O("O027","CHECKOUT","Mohan vacating",tags=["operational"]),
O("O028","CHECKOUT","Ravi is checking out",tags=["operational"]),

# ── SCHEDULE_CHECKOUT  O029-O034 ──────────────────────────────────────────────
O("O029","SCHEDULE_CHECKOUT","Raj checkout on 31st March",tags=["basic","operational"]),
O("O030","SCHEDULE_CHECKOUT","schedule checkout Arjun 28 March",tags=["operational"]),
O("O031","SCHEDULE_CHECKOUT","Vikram leaving on March 30",tags=["operational"]),
O("O032","SCHEDULE_CHECKOUT","Kumar checkout scheduled for April 15",tags=["operational"]),
O("O033","SCHEDULE_CHECKOUT","plan checkout Suresh 31 March",tags=["operational"]),
O("O034","SCHEDULE_CHECKOUT","Deepak leaving March end",tags=["operational"]),

# ── NOTICE_GIVEN  O035-O040 ───────────────────────────────────────────────────
O("O035","NOTICE_GIVEN","Raj gave notice",tags=["basic","operational"]),
O("O036","NOTICE_GIVEN","Arjun gave one month notice",tags=["operational"]),
O("O037","NOTICE_GIVEN","Vikram gave notice today",tags=["operational"]),
O("O038","NOTICE_GIVEN","Kumar is serving notice",tags=["operational"]),
O("O039","NOTICE_GIVEN","notice received from Suresh",tags=["operational"]),
O("O040","NOTICE_GIVEN","Deepak gave notice",tags=["operational"]),

# ── RECORD_CHECKOUT  O041-O046 ────────────────────────────────────────────────
O("O041","RECORD_CHECKOUT","record checkout Raj",tags=["basic","flow"]),
O("O042","RECORD_CHECKOUT","process checkout Arjun",tags=["flow"]),
O("O043","RECORD_CHECKOUT","complete checkout Vikram",tags=["flow"]),
O("O044","RECORD_CHECKOUT","finalize checkout Kumar",tags=["flow"]),
O("O045","RECORD_CHECKOUT","checkout process Suresh",tags=["flow"]),
O("O046","RECORD_CHECKOUT","do checkout Deepak",tags=["flow"]),

# ── LOG_VACATION  O047-O052 ───────────────────────────────────────────────────
O("O047","LOG_VACATION","Raj on vacation 10 days",tags=["basic","operational"]),
O("O048","LOG_VACATION","Arjun going home for 5 days",tags=["operational"]),
O("O049","LOG_VACATION","Vikram vacation from March 15 to 25",tags=["operational"]),
O("O050","LOG_VACATION","Kumar on leave 7 days",tags=["operational"]),
O("O051","LOG_VACATION","Suresh going out of station 3 days",tags=["operational"]),
O("O052","LOG_VACATION","Deepak vacation 2 weeks",tags=["operational"]),

# ── COMPLAINT_REGISTER (owner)  O053-O060 ─────────────────────────────────────
O("O053","COMPLAINT_REGISTER","AC not working in room 205",tags=["basic","operational"]),
O("O054","COMPLAINT_REGISTER","water leak in room 101",tags=["operational"]),
O("O055","COMPLAINT_REGISTER","complaint room 202 fan broken",tags=["operational"]),
O("O056","COMPLAINT_REGISTER","room 301 door lock issue",tags=["operational"]),
O("O057","COMPLAINT_REGISTER","plumbing problem room 204",tags=["operational"]),
O("O058","COMPLAINT_REGISTER","room 102 light not working",tags=["operational"]),
O("O059","COMPLAINT_REGISTER","wifi issue room 203",tags=["operational"]),
O("O060","COMPLAINT_REGISTER","room 201 toilet blocked",tags=["operational"]),

# ── QUERY_VACANT_ROOMS  O061-O068 ─────────────────────────────────────────────
O("O061","QUERY_VACANT_ROOMS","vacant rooms",tags=["basic","query"]),
O("O062","QUERY_VACANT_ROOMS","empty rooms",tags=["query"]),
O("O063","QUERY_VACANT_ROOMS","which rooms are free",tags=["query"]),
O("O064","QUERY_VACANT_ROOMS","available rooms",tags=["query"]),
O("O065","QUERY_VACANT_ROOMS","vacancy",tags=["query"]),
O("O066","QUERY_VACANT_ROOMS","how many rooms empty",tags=["query"]),
O("O067","QUERY_VACANT_ROOMS","list vacant rooms",tags=["query"]),
O("O068","QUERY_VACANT_ROOMS","free rooms",tags=["query"]),

# ── QUERY_OCCUPANCY  O069-O074 ────────────────────────────────────────────────
O("O069","QUERY_OCCUPANCY","occupancy",tags=["basic","query"]),
O("O070","QUERY_OCCUPANCY","how full are we",tags=["query"]),
O("O071","QUERY_OCCUPANCY","occupancy rate",tags=["query"]),
O("O072","QUERY_OCCUPANCY","how many tenants",tags=["query"]),
O("O073","QUERY_OCCUPANCY","occupancy this month",tags=["query"]),
O("O074","QUERY_OCCUPANCY","how many rooms occupied",tags=["query"]),

# ── QUERY_EXPIRING  O075-O080 ─────────────────────────────────────────────────
O("O075","QUERY_EXPIRING","who is leaving this month",tags=["basic","query"]),
O("O076","QUERY_EXPIRING","upcoming checkouts",tags=["query"]),
O("O077","QUERY_EXPIRING","who is vacating",tags=["query"]),
O("O078","QUERY_EXPIRING","tenants leaving in March",tags=["query"]),
O("O079","QUERY_EXPIRING","end of month checkouts",tags=["query"]),
O("O080","QUERY_EXPIRING","expiring tenancies",tags=["query"]),

# ── QUERY_CHECKINS  O081-O086 ─────────────────────────────────────────────────
O("O081","QUERY_CHECKINS","who checked in this month",tags=["basic","query"]),
O("O082","QUERY_CHECKINS","new tenants this month",tags=["query"]),
O("O083","QUERY_CHECKINS","recent admissions",tags=["query"]),
O("O084","QUERY_CHECKINS","checkins March",tags=["query"]),
O("O085","QUERY_CHECKINS","new joinings",tags=["query"]),
O("O086","QUERY_CHECKINS","who joined recently",tags=["query"]),

# ── QUERY_CHECKOUTS  O087-O092 ────────────────────────────────────────────────
O("O087","QUERY_CHECKOUTS","who checked out this month",tags=["basic","query"]),
O("O088","QUERY_CHECKOUTS","recent checkouts",tags=["query"]),
O("O089","QUERY_CHECKOUTS","tenants who left",tags=["query"]),
O("O090","QUERY_CHECKOUTS","exits this month",tags=["query"]),
O("O091","QUERY_CHECKOUTS","checkouts March",tags=["query"]),
O("O092","QUERY_CHECKOUTS","who left recently",tags=["query"]),

# ── REMINDER_SET  O093-O098 ───────────────────────────────────────────────────
O("O093","REMINDER_SET","remind Raj about rent on 5th",tags=["basic","operational"]),
O("O094","REMINDER_SET","set reminder Arjun rent March 5",tags=["operational"]),
O("O095","REMINDER_SET","reminder for Vikram on March 10",tags=["operational"]),
O("O096","REMINDER_SET","remind Kumar rent 3rd",tags=["operational"]),
O("O097","REMINDER_SET","send reminder to Suresh on 7th",tags=["operational"]),
O("O098","REMINDER_SET","reminder Deepak March 5",tags=["operational"]),

# ── SEND_REMINDER_ALL  O099-O102 ──────────────────────────────────────────────
O("O099","SEND_REMINDER_ALL","send rent reminders",tags=["basic","operational"]),
O("O100","SEND_REMINDER_ALL","remind all tenants about rent",tags=["operational"]),
O("O101","SEND_REMINDER_ALL","bulk reminder for rent",tags=["operational"]),
O("O102","SEND_REMINDER_ALL","send reminders to all",tags=["operational"]),

# ── ADD_PARTNER  O103-O106 ────────────────────────────────────────────────────
O("O103","ADD_PARTNER","add partner 9876543210",tags=["basic","operational"]),
O("O104","ADD_PARTNER","add power user 8765432109",tags=["operational"]),
O("O105","ADD_PARTNER","give access 9876543210",tags=["operational"]),
O("O106","ADD_PARTNER","add staff 7654321098",tags=["operational"]),

# ── RULES  O107-O112 ──────────────────────────────────────────────────────────
O("O107","RULES","pg rules",tags=["basic","info"]),
O("O108","RULES","house rules",tags=["info"]),
O("O109","RULES","show rules",tags=["info"]),
O("O110","RULES","what are the rules",tags=["info"]),
O("O111","RULES","list PG rules",tags=["info"]),
O("O112","RULES","rules and regulations",tags=["info"]),

# ── HELP  O113-O118 ───────────────────────────────────────────────────────────
O("O113","HELP","help",tags=["basic","info"]),
O("O114","HELP","commands",tags=["info"]),
O("O115","HELP","what can you do",tags=["info"]),
O("O116","HELP","how to use",tags=["info"]),
O("O117","HELP","show commands",tags=["info"]),
O("O118","HELP","menu",tags=["info"]),

# ── ROOM_STATUS  O119-O122 ────────────────────────────────────────────────────
O("O119","ROOM_STATUS","status of room 205",tags=["basic","query"]),
O("O120","ROOM_STATUS","room 101 status",tags=["query"]),
O("O121","ROOM_STATUS","is room 202 occupied",tags=["query"]),
O("O122","ROOM_STATUS","room 301 details",tags=["query"]),

# ── Hinglish / mixed language  O123-O140 ──────────────────────────────────────
O("O123","ADD_TENANT","naya tenant add karo Arjun 9876543210 room 204",tags=["hinglish","operational"]),
O("O124","CHECKOUT","Raj ja raha hai",tags=["hinglish","operational"]),
O("O125","QUERY_VACANT_ROOMS","khali rooms kaun se hain",tags=["hinglish","query"]),
O("O126","QUERY_OCCUPANCY","kitne log rehte hain",tags=["hinglish","query"]),
O("O127","QUERY_DUES","kisne nahi diya abhi tak",tags=["hinglish","query"]),
O("O128","COMPLAINT_REGISTER","room 205 ka AC kharab hai",tags=["hinglish","operational"]),
O("O129","LOG_VACATION","Raj chutti pe hai 10 din",tags=["hinglish","operational"]),
O("O130","REMINDER_SET","Raj ko rent yaad dilao 5 tarikh ko",tags=["hinglish","operational"]),
O("O131","NOTICE_GIVEN","Arjun ne notice de diya",tags=["hinglish","operational"]),
O("O132","REPORT","is mahine ka report do",tags=["hinglish","query"]),
O("O133","QUERY_EXPIRING","is mahine kaun ja raha hai",tags=["hinglish","query"]),
O("O134","RULES","niyam batao",tags=["hinglish","info"]),
O("O135","HELP","kya kar sakte ho",tags=["hinglish","info"]),
O("O136","RECORD_CHECKOUT","Raj ka checkout process karo",tags=["hinglish","flow"]),
O("O137","QUERY_CHECKINS","is mahine kaun aaya",tags=["hinglish","query"]),
O("O138","SEND_REMINDER_ALL","sabko rent reminder bhejo",tags=["hinglish","operational"]),
O("O139","SCHEDULE_CHECKOUT","Raj 31 March ko jayega",tags=["hinglish","operational"]),
O("O140","LOG_VACATION","Vikram 5 din ke liye ghar gaya",tags=["hinglish","operational"]),

# ── edge / ambiguous OwnerWorker  O141-O160 ────────────────────────────────────
O("O141","CHECKOUT","Raj leaving",expected_intent="CHECKOUT",confidence=0.50,tags=["edge","ambiguous"]),
O("O142","ADD_TENANT","add tenant Arjun",expected_intent="ADD_TENANT",confidence=0.60,tags=["edge","partial"]),
O("O143","QUERY_VACANT_ROOMS","any rooms",expected_intent="QUERY_VACANT_ROOMS",confidence=0.65,tags=["edge"]),
O("O144","QUERY_OCCUPANCY","rooms occupied?",tags=["edge"]),
O("O145","NOTICE_GIVEN","Raj notice",expected_intent="NOTICE_GIVEN",confidence=0.60,tags=["edge","ambiguous"]),
O("O146","COMPLAINT_REGISTER","room 205 problem",expected_intent="COMPLAINT_REGISTER",confidence=0.65,tags=["edge"]),
O("O147","REMINDER_SET","remind Raj",expected_intent="REMINDER_SET",confidence=0.60,tags=["edge","partial"]),
O("O148","LOG_VACATION","Raj not here",expected_intent="LOG_VACATION",confidence=0.55,tags=["edge","ambiguous"]),
O("O149","QUERY_EXPIRING","who is leaving",tags=["edge","query"]),
O("O150","RECORD_CHECKOUT","do Raj checkout",tags=["edge","flow"]),
O("O151","UPDATE_CHECKIN","Raj checkin March 1",tags=["edge","operational"]),
O("O152","AMBIGUOUS","Raj March 31",expected_intent="AMBIGUOUS",confidence=0.0,tags=["edge","ambiguous"]),
O("O153","COMPLAINT_REGISTER","room issue 204",expected_intent="COMPLAINT_REGISTER",confidence=0.65,tags=["edge"]),
O("O154","ADD_PARTNER","9876543210 add partner",tags=["edge","operational"]),
O("O155","QUERY_CHECKINS","checkins this month",tags=["edge","query"]),
O("O156","LOG_VACATION","Raj 7 din bahar",tags=["edge","hinglish"]),
O("O157","RULES","rules batao",tags=["edge","hinglish","info"]),
O("O158","SEND_REMINDER_ALL","send all reminders",tags=["edge","operational"]),
O("O159","CHECKOUT","Raj chhod raha hai",tags=["edge","hinglish"]),
O("O160","QUERY_CHECKOUTS","March mein kaun gaya",tags=["edge","hinglish","query"]),

# ─────────────────────────────────────────────────────────────────────────────
# TENANT WORKER  (T001 – T080)
# ─────────────────────────────────────────────────────────────────────────────

# ── MY_BALANCE  T001-T012 ─────────────────────────────────────────────────────
T("T001","MY_BALANCE","my balance",tags=["basic","query"]),
T("T002","MY_BALANCE","how much do I owe",tags=["query"]),
T("T003","MY_BALANCE","my dues",tags=["query"]),
T("T004","MY_BALANCE","what's my outstanding",tags=["query"]),
T("T005","MY_BALANCE","pending rent",tags=["query"]),
T("T006","MY_BALANCE","how much is my rent",tags=["query"]),
T("T007","MY_BALANCE","balance kya hai",tags=["query","hinglish"]),
T("T008","MY_BALANCE","mera balance",tags=["query","hinglish"]),
T("T009","MY_BALANCE","tell me my balance",tags=["query"]),
T("T010","MY_BALANCE","what do I need to pay",tags=["query"]),
T("T011","MY_BALANCE","outstanding amount",tags=["query"]),
T("T012","MY_BALANCE","my rent status",tags=["query"]),

# ── MY_PAYMENTS  T013-T020 ────────────────────────────────────────────────────
T("T013","MY_PAYMENTS","my payments",tags=["basic","query"]),
T("T014","MY_PAYMENTS","payment history",tags=["query"]),
T("T015","MY_PAYMENTS","past payments",tags=["query"]),
T("T016","MY_PAYMENTS","show my payments",tags=["query"]),
T("T017","MY_PAYMENTS","when did I last pay",tags=["query"]),
T("T018","MY_PAYMENTS","meri payments",tags=["query","hinglish"]),
T("T019","MY_PAYMENTS","transaction history",tags=["query"]),
T("T020","REQUEST_RECEIPT","my receipts",expected_intent="REQUEST_RECEIPT",tags=["query"]),

# ── MY_DETAILS  T021-T028 ─────────────────────────────────────────────────────
T("T021","MY_DETAILS","my details",tags=["basic","query"]),
T("T022","MY_DETAILS","my room",tags=["query"]),
T("T023","MY_DETAILS","my room number",tags=["query"]),
T("T024","MY_DETAILS","when did I check in",tags=["query"]),
T("T025","MY_DETAILS","my profile",tags=["query"]),
T("T026","MY_DETAILS","show my details",tags=["query"]),
T("T027","MY_DETAILS","my information",tags=["query"]),
T("T028","MY_DETAILS","my account details",tags=["query"]),

# ── COMPLAINT_REGISTER (tenant)  T029-T036 ────────────────────────────────────
T("T029","COMPLAINT_REGISTER","AC not working",tags=["basic","operational"]),
T("T030","COMPLAINT_REGISTER","water problem",tags=["operational"]),
T("T031","COMPLAINT_REGISTER","light not working in my room",tags=["operational"]),
T("T032","COMPLAINT_REGISTER","toilet blocked",tags=["operational"]),
T("T033","COMPLAINT_REGISTER","wifi not working",tags=["operational"]),
T("T034","COMPLAINT_REGISTER","fan broken",tags=["operational"]),
T("T035","COMPLAINT_REGISTER","door lock issue",tags=["operational"]),
T("T036","COMPLAINT_REGISTER","pest problem in my room",tags=["operational"]),

# ── RULES (tenant)  T037-T042 ─────────────────────────────────────────────────
T("T037","RULES","rules",tags=["basic","info"]),
T("T038","RULES","regulations",tags=["info"]),
T("T039","RULES","pg rules",tags=["info"]),
T("T040","RULES","house rules",tags=["info"]),
T("T041","RULES","what are the rules",tags=["info"]),
T("T042","RULES","show rules",tags=["info"]),

# ── CHECKOUT_NOTICE (tenant)  T043-T048 ───────────────────────────────────────
T("T043","CHECKOUT_NOTICE","I am leaving",tags=["basic","operational"]),
T("T044","CHECKOUT_NOTICE","I want to vacate",tags=["operational"]),
T("T045","CHECKOUT_NOTICE","planning to leave next month",tags=["operational"]),
T("T046","CHECKOUT_NOTICE","I'm moving out",tags=["operational"]),
T("T047","CHECKOUT_NOTICE","want to checkout",tags=["operational"]),
T("T048","CHECKOUT_NOTICE","giving notice",tags=["operational"]),

# ── VACATION_NOTICE (tenant)  T049-T054 ───────────────────────────────────────
T("T049","VACATION_NOTICE","I will be on vacation for 5 days",tags=["basic","operational"]),
T("T050","VACATION_NOTICE","going home for a week",tags=["operational"]),
T("T051","VACATION_NOTICE","out of town 3 days",tags=["operational"]),
T("T052","VACATION_NOTICE","on leave next week",tags=["operational"]),
T("T053","VACATION_NOTICE","vacation notice 10 days",tags=["operational"]),
T("T054","VACATION_NOTICE","going home for Diwali",tags=["operational"]),

# ── REQUEST_RECEIPT  T055-T058 ────────────────────────────────────────────────
T("T055","REQUEST_RECEIPT","send me receipt",tags=["basic","query"]),
T("T056","REQUEST_RECEIPT","I need my payment receipt",tags=["query"]),
T("T057","REQUEST_RECEIPT","receipt for last payment",tags=["query"]),
T("T058","REQUEST_RECEIPT","payment receipt",tags=["query"]),

# ── HELP (tenant)  T059-T062 ──────────────────────────────────────────────────
T("T059","HELP","help",tags=["basic","info"]),
T("T060","HELP","what can I ask",tags=["info"]),
T("T061","HELP","commands",tags=["info"]),
T("T062","HELP","menu",tags=["info"]),

# ── UNKNOWN (tenant)  T063-T066 ───────────────────────────────────────────────
T("T063","HELP","hello",tags=["edge","greeting"]),
T("T064","HELP","good morning",tags=["edge","greeting"]),
T("T065","UNKNOWN","what is this",expected_intent="UNKNOWN",tags=["edge","unknown"]),
T("T066","HELP","thanks",tags=["edge","greeting"]),

# ── permission boundary — tenant sending admin commands  T067-T074 ─────────────
# These should succeed (bot handles gracefully) but with tenant-appropriate responses
T("T067","UNKNOWN","add tenant Arjun 9876543210 room 204",
  expected_intent="UNKNOWN",confidence=0.50,tags=["permission","boundary"]),
T("T068","UNKNOWN","who hasn't paid",
  expected_intent="UNKNOWN",confidence=0.50,tags=["permission","boundary"]),
T("T069","UNKNOWN","monthly report",
  expected_intent="UNKNOWN",confidence=0.50,tags=["permission","boundary"]),
T("T070","UNKNOWN","add expense 5000 cash",
  expected_intent="UNKNOWN",confidence=0.50,tags=["permission","boundary"]),
T("T071","UNKNOWN","change rent for room 205 to 12000",
  expected_intent="UNKNOWN",confidence=0.50,tags=["permission","boundary"]),
T("T072","UNKNOWN","void payment 42",
  expected_intent="UNKNOWN",confidence=0.50,tags=["permission","boundary"]),
T("T073","UNKNOWN","add partner 9876543210",
  expected_intent="UNKNOWN",confidence=0.50,tags=["permission","boundary"]),
T("T074","UNKNOWN","Raj balance",
  expected_intent="UNKNOWN",confidence=0.50,tags=["permission","boundary"]),

# ── Hinglish tenant  T075-T080 ────────────────────────────────────────────────
T("T075","MY_BALANCE","mera balance kya hai",tags=["hinglish","query"]),
T("T076","MY_BALANCE","kitna dena hai mujhe",tags=["hinglish","query"]),
T("T077","MY_PAYMENTS","meri payment history",tags=["hinglish","query"]),
T("T078","COMPLAINT_REGISTER","AC kharab hai",tags=["hinglish","operational"]),
T("T079","COMPLAINT_REGISTER","room ki light nahi hai",tags=["hinglish","operational"]),
T("T080","MY_DETAILS","mera room number kya hai",tags=["hinglish","query"]),

# ── New intents (v2.0)  T081-T083 ─────────────────────────────────────────────
T("T081","GET_WIFI_PASSWORD","wifi password",tags=["query","wifi"]),
T("T082","VACATION_NOTICE","going home for 5 days",tags=["operational","vacation"]),
T("T083","REQUEST_RECEIPT","show my receipt for February",tags=["query","receipt"]),

# ─────────────────────────────────────────────────────────────────────────────
# LEAD WORKER  (L001 – L091)
# ─────────────────────────────────────────────────────────────────────────────

# ── ROOM_PRICE  L001-L012 ─────────────────────────────────────────────────────
L("L001","ROOM_PRICE","price",tags=["basic","query"]),
L("L002","ROOM_PRICE","rent",tags=["query"]),
L("L003","ROOM_PRICE","how much",tags=["query"]),
L("L004","ROOM_PRICE","room price",tags=["query"]),
L("L005","ROOM_PRICE","how much does a room cost",tags=["query"]),
L("L006","ROOM_PRICE","monthly rent",tags=["query"]),
L("L007","ROOM_PRICE","what's the rent",tags=["query"]),
L("L008","ROOM_PRICE","pricing",tags=["query"]),
L("L009","ROOM_PRICE","rate per room",tags=["query"]),
L("L010","ROOM_PRICE","kitna rent hai",tags=["query","hinglish"]),
L("L011","ROOM_PRICE","room charges",tags=["query"]),
L("L012","ROOM_PRICE","cost of staying",tags=["query"]),

# ── AVAILABILITY  L013-L020 ───────────────────────────────────────────────────
L("L013","AVAILABILITY","available",tags=["basic","query"]),
L("L014","AVAILABILITY","any rooms available",tags=["query"]),
L("L015","AVAILABILITY","vacancy",tags=["query"]),
L("L016","AVAILABILITY","do you have rooms",tags=["query"]),
L("L017","AVAILABILITY","is anything available",tags=["query"]),
L("L018","AVAILABILITY","room available kya hai",tags=["query","hinglish"]),
L("L019","AVAILABILITY","any empty rooms",tags=["query"]),
L("L020","AVAILABILITY","looking for a room",tags=["query"]),

# ── ROOM_TYPE  L021-L028 ──────────────────────────────────────────────────────
L("L021","ROOM_TYPE","single room",tags=["basic","query"]),
L("L022","ROOM_TYPE","double room",tags=["query"]),
L("L023","ROOM_TYPE","triple sharing",tags=["query"]),
L("L024","ROOM_TYPE","AC room",tags=["query"]),
L("L025","ROOM_TYPE","non AC room",tags=["query"]),
L("L026","ROOM_TYPE","what types of rooms do you have",tags=["query"]),
L("L027","ROOM_TYPE","shared room",tags=["query"]),
L("L028","ROOM_TYPE","private room",tags=["query"]),

# ── VISIT_REQUEST  L029-L036 ──────────────────────────────────────────────────
L("L029","VISIT_REQUEST","visit",tags=["basic","flow"]),
L("L030","VISIT_REQUEST","tour",tags=["flow"]),
L("L031","VISIT_REQUEST","can I see the room",tags=["flow"]),
L("L032","VISIT_REQUEST","I want to visit",tags=["flow"]),
L("L033","VISIT_REQUEST","book a tour",tags=["flow"]),
L("L034","VISIT_REQUEST","site visit",tags=["flow"]),
L("L035","VISIT_REQUEST","want to come see the room",tags=["flow"]),
L("L036","VISIT_REQUEST","schedule a visit",tags=["flow"]),

# ── GENERAL  L037-L044 ────────────────────────────────────────────────────────
L("L037","GENERAL","hello",confidence=0.50,tags=["basic","general"]),
L("L038","GENERAL","hi",confidence=0.50,tags=["general"]),
L("L039","GENERAL","tell me more about the PG",confidence=0.50,tags=["general"]),
L("L040","GENERAL","what facilities do you have",confidence=0.50,tags=["general"]),
L("L041","GENERAL","food included?",confidence=0.50,tags=["general"]),
L("L042","GENERAL","is parking available",confidence=0.50,tags=["general"]),
L("L043","GENERAL","what's included in rent",confidence=0.50,tags=["general"]),
L("L044","GENERAL","nearby metro station",confidence=0.50,tags=["general"]),

# ── Lead edge cases  L045-L050 ────────────────────────────────────────────────
L("L045","GENERAL","okay",expected_intent="GENERAL",confidence=0.50,tags=["edge","ambiguous"]),
L("L046","GENERAL","maybe",expected_intent="GENERAL",confidence=0.50,tags=["edge","ambiguous"]),
L("L047","ROOM_PRICE","12000",expected_intent="ROOM_PRICE",confidence=0.55,tags=["edge"]),
L("L048","GENERAL","🙏",expected_intent="GENERAL",confidence=0.50,tags=["edge","emoji"]),
L("L049","AVAILABILITY","rooms?",tags=["edge"]),
L("L050","VISIT_REQUEST","visit please",tags=["edge"]),

# ── Extra ROOM_PRICE  L051-L060 ────────────────────────────────────────────────
L("L051","ROOM_PRICE","monthly rent?",tags=["query"]),
L("L052","ROOM_PRICE","how much per month",tags=["query"]),
L("L053","ROOM_PRICE","kitna rent hai",tags=["query","hinglish"]),
L("L054","ROOM_PRICE","rent for single occupancy",tags=["query"]),
L("L055","ROOM_PRICE","charges per month",tags=["query"]),
L("L056","ROOM_PRICE","AC room charges",tags=["query"]),
L("L057","ROOM_PRICE","triple sharing rent",tags=["query"]),
L("L058","ROOM_PRICE","what is the monthly fee",tags=["query"]),
L("L059","ROOM_PRICE","cost of a room",tags=["query"]),
L("L060","ROOM_PRICE","double occupancy rate",tags=["query"]),

# ── Extra AVAILABILITY  L061-L068 ─────────────────────────────────────────────
L("L061","AVAILABILITY","any room available now",tags=["query"]),
L("L062","AVAILABILITY","single room available?",tags=["query"]),
L("L063","AVAILABILITY","do you have vacancy",tags=["query"]),
L("L064","AVAILABILITY","koi room khali hai kya",tags=["query","hinglish"]),
L("L065","AVAILABILITY","is there a room",tags=["query"]),
L("L066","AVAILABILITY","AC room available",tags=["query"]),
L("L067","AVAILABILITY","double room available",tags=["query"]),
L("L068","AVAILABILITY","vacancy for single",tags=["query"]),

# ── Extra VISIT_REQUEST  L069-L074 ────────────────────────────────────────────
L("L069","VISIT_REQUEST","I want to come see the PG",tags=["flow"]),
L("L070","VISIT_REQUEST","can I visit this weekend",tags=["flow"]),
L("L071","VISIT_REQUEST","I want to see the room tomorrow",tags=["flow"]),
L("L072","VISIT_REQUEST","dekhne aana chahta hoon",tags=["flow","hinglish"]),
L("L073","VISIT_REQUEST","arrange a visit for me",tags=["flow"]),
L("L074","VISIT_REQUEST","I'd like a tour of the PG",tags=["flow"]),

# ── Extra GENERAL  L075-L082 ──────────────────────────────────────────────────
L("L075","GENERAL","good morning",confidence=0.50,tags=["general","greeting"]),
L("L076","GENERAL","what are the rules",confidence=0.50,tags=["general"]),
L("L077","GENERAL","is it safe for girls",confidence=0.50,tags=["general"]),
L("L078","GENERAL","laundry facility",confidence=0.50,tags=["general"]),
L("L079","GENERAL","gym nearby",confidence=0.50,tags=["general"]),
L("L080","GENERAL","wifi speed",confidence=0.50,tags=["general"]),
L("L081","GENERAL","water supply",confidence=0.50,tags=["general"]),
L("L082","GENERAL","housekeeping included",confidence=0.50,tags=["general"]),

# ── Security blocks (lead cannot access admin/tenant data)  L083-L091 ─────────
L("L083","GENERAL","Raj paid 15000 upi",expected_intent="GENERAL",confidence=0.50,tags=["security","blocked"]),
L("L084","GENERAL","who hasn't paid",expected_intent="GENERAL",confidence=0.50,tags=["security","blocked"]),
L("L085","GENERAL","monthly report",expected_intent="GENERAL",confidence=0.50,tags=["security","blocked"]),
L("L086","GENERAL","show all tenants",expected_intent="GENERAL",confidence=0.50,tags=["security","blocked"]),
L("L087","GENERAL","add expense 5000 cash",expected_intent="GENERAL",confidence=0.50,tags=["security","blocked"]),
L("L088","GENERAL","wifi password",expected_intent="GENERAL",confidence=0.50,tags=["security","wifi","blocked"]),
L("L089","GENERAL","my balance",expected_intent="GENERAL",confidence=0.50,tags=["security","blocked"]),
L("L090","GENERAL","show expenses",expected_intent="GENERAL",confidence=0.50,tags=["security","blocked"]),
L("L091","GENERAL","void payment 42",expected_intent="GENERAL",confidence=0.50,tags=["security","blocked"]),

# ─────────────────────────────────────────────────────────────────────────────
# EDGE CASES & SYSTEM  (E001 – E075)
# ─────────────────────────────────────────────────────────────────────────────

# ── Empty / minimal  E001-E005 ────────────────────────────────────────────────
E("E001","AccountWorker","UNKNOWN","admin",".",
  expected_intent="UNKNOWN",confidence=0.0,tags=["edge","empty"]),
E("E002","AccountWorker","UNKNOWN","admin","?",
  expected_intent="UNKNOWN",confidence=0.0,tags=["edge","empty"]),
E("E003","LeadWorker","UNKNOWN","lead","ok",
  expected_intent="GENERAL",confidence=0.50,tags=["edge","minimal"]),
E("E004","TenantWorker","HELP","tenant","ok",
  expected_intent="HELP",confidence=0.50,tags=["edge","minimal"]),
E("E005","LeadWorker","GENERAL","lead","  ",
  expected_intent="GENERAL",confidence=0.50,tags=["edge","empty"]),

# ── Very long messages  E006-E010 ─────────────────────────────────────────────
E("E006","AccountWorker","PAYMENT_LOG","admin",
  "Hi sir Raj paid rent today he gave 15000 rupees through UPI and the transaction ID is UPI123456789 and I saw it in the bank statement",
  expected_intent="PAYMENT_LOG",tags=["edge","long"]),
E("E007","TenantWorker","COMPLAINT_REGISTER","tenant",
  "The AC in my room has not been working for the past 3 days and it is very hot and I have complained twice before and no one has fixed it please help",
  expected_intent="COMPLAINT_REGISTER",tags=["edge","long"]),
E("E008","LeadWorker","GENERAL","lead",
  "Hello I am looking for a PG near Whitefield with good facilities good food and reasonable rent preferably AC room single or double sharing please let me know",
  expected_intent="GENERAL",tags=["edge","long"]),
E("E009","AccountWorker","QUERY_DUES","admin",
  "Can you please tell me which tenants have not paid their rent this month because I need to send them reminders and also prepare a report",
  expected_intent="QUERY_DUES",tags=["edge","long"]),
E("E010","OwnerWorker","CHECKOUT","admin",
  "Raj Kumar from room 205 has informed me that he is planning to leave the PG by end of this month and wants to complete the checkout process",
  expected_intent="CHECKOUT",tags=["edge","long"]),

# ── Special characters  E011-E015 ─────────────────────────────────────────────
E("E011","AccountWorker","PAYMENT_LOG","admin","Raj paid ₹15000 upi",
  expected_intent="PAYMENT_LOG",tags=["edge","special_chars"]),
E("E012","AccountWorker","PAYMENT_LOG","admin","💰 15000 from Raj gpay",
  expected_intent="PAYMENT_LOG",tags=["edge","emoji"]),
E("E013","AccountWorker","PAYMENT_LOG","admin","*Raj* paid 15000",
  expected_intent="PAYMENT_LOG",tags=["edge","special_chars"]),
E("E014","AccountWorker","QUERY_DUES","admin","who hasn't paid? 🤔",
  expected_intent="QUERY_DUES",tags=["edge","emoji"]),
E("E015","TenantWorker","MY_BALANCE","tenant","💸 my balance?",
  expected_intent="MY_BALANCE",tags=["edge","emoji"]),

# ── Numbers as words  E016-E020 ───────────────────────────────────────────────
E("E016","AccountWorker","PAYMENT_LOG","admin","Raj paid fifteen thousand",
  expected_intent="PAYMENT_LOG",confidence=0.60,tags=["edge","numbers_as_words"]),
E("E017","AccountWorker","ADD_EXPENSE","admin","expenses five thousand cash",
  expected_intent="ADD_EXPENSE",confidence=0.65,tags=["edge","numbers_as_words"]),
E("E018","AccountWorker","RENT_CHANGE","admin","room two zero five rent twelve thousand",
  expected_intent="RENT_CHANGE",confidence=0.55,tags=["edge","numbers_as_words"]),
E("E019","AccountWorker","RENT_DISCOUNT","admin","give Raj five hundred discount",
  expected_intent="RENT_DISCOUNT",confidence=0.65,tags=["edge","numbers_as_words"]),
E("E020","AccountWorker","ADD_REFUND","admin","refund ten thousand to Arjun",
  expected_intent="ADD_REFUND",confidence=0.65,tags=["edge","numbers_as_words"]),

# ── Typos  E021-E030 ──────────────────────────────────────────────────────────
E("E021","AccountWorker","PAYMENT_LOG","admin","Raj piad 15000 upi",
  expected_intent="PAYMENT_LOG",confidence=0.70,tags=["edge","typo"]),
E("E022","AccountWorker","QUERY_DUES","admin","who hasnt piad",
  expected_intent="QUERY_DUES",confidence=0.70,tags=["edge","typo"]),
E("E023","AccountWorker","QUERY_EXPENSES","admin","expneses this month",
  expected_intent="QUERY_EXPENSES",confidence=0.65,tags=["edge","typo"]),
E("E024","AccountWorker","REPORT","admin","monhtly report",
  expected_intent="REPORT",confidence=0.70,tags=["edge","typo"]),
E("E025","OwnerWorker","QUERY_VACANT_ROOMS","admin","vacnt rooms",
  expected_intent="QUERY_VACANT_ROOMS",confidence=0.65,tags=["edge","typo"]),
E("E026","OwnerWorker","QUERY_OCCUPANCY","admin","ocupancy",
  expected_intent="QUERY_OCCUPANCY",confidence=0.65,tags=["edge","typo"]),
E("E027","OwnerWorker","RECORD_CHECKOUT","admin","chekout Raj",
  expected_intent="RECORD_CHECKOUT",confidence=0.65,tags=["edge","typo"]),
E("E028","OwnerWorker","REMINDER_SET","admin","remaind Raj about rent 5th",
  expected_intent="REMINDER_SET",confidence=0.65,tags=["edge","typo"]),
E("E029","AccountWorker","ADD_EXPENSE","admin","maintanace 5000 cash",
  expected_intent="ADD_EXPENSE",confidence=0.65,tags=["edge","typo"]),
E("E030","OwnerWorker","ADD_TENANT","admin","add teant Arjun 9876543210",
  expected_intent="ADD_TENANT",confidence=0.65,tags=["edge","typo"]),

# ── Role boundary violations  E031-E045 ───────────────────────────────────────
# Lead trying owner commands → should get GENERAL / lead response
E("E031","LeadWorker","GENERAL","lead","Raj paid 15000 upi",
  expected_intent="GENERAL",confidence=0.50,tags=["boundary","role"]),
E("E032","LeadWorker","GENERAL","lead","monthly report",
  expected_intent="GENERAL",confidence=0.50,tags=["boundary","role"]),
E("E033","LeadWorker","GENERAL","lead","who hasn't paid",
  expected_intent="GENERAL",confidence=0.50,tags=["boundary","role"]),
E("E034","LeadWorker","GENERAL","lead","add expense 5000 cash",
  expected_intent="GENERAL",confidence=0.50,tags=["boundary","role"]),
E("E035","LeadWorker","GENERAL","lead","void payment 42",
  expected_intent="GENERAL",confidence=0.50,tags=["boundary","role"]),
# Tenant trying financial commands → should get UNKNOWN / tenant response
E("E036","TenantWorker","UNKNOWN","tenant","Raj paid 15000 upi",
  expected_intent="UNKNOWN",confidence=0.50,tags=["boundary","role"]),
E("E037","TenantWorker","UNKNOWN","tenant","who hasn't paid",
  expected_intent="UNKNOWN",confidence=0.50,tags=["boundary","role"]),
E("E038","TenantWorker","UNKNOWN","tenant","monthly report",
  expected_intent="UNKNOWN",confidence=0.50,tags=["boundary","role"]),
E("E039","TenantWorker","UNKNOWN","tenant","add tenant Arjun room 204",
  expected_intent="UNKNOWN",confidence=0.50,tags=["boundary","role"]),
E("E040","TenantWorker","UNKNOWN","tenant","void payment 42",
  expected_intent="UNKNOWN",confidence=0.50,tags=["boundary","role"]),
# Power user — should be able to do financial but NOT add_partner
E("E041","AccountWorker","PAYMENT_LOG","power_user","Raj paid 15000 upi",
  expected_intent="PAYMENT_LOG",tags=["boundary","role"]),
E("E042","AccountWorker","REPORT","power_user","monthly report",
  expected_intent="REPORT",tags=["boundary","role"]),
E("E043","AccountWorker","QUERY_DUES","power_user","who hasn't paid",
  expected_intent="QUERY_DUES",tags=["boundary","role"]),
# Key_user — payment logging allowed, report may be restricted
E("E044","AccountWorker","PAYMENT_LOG","key_user","Raj paid 15000 upi",
  expected_intent="PAYMENT_LOG",tags=["boundary","role"]),
E("E045","AccountWorker","QUERY_TENANT","key_user","Raj balance",
  expected_intent="QUERY_TENANT",tags=["boundary","role"]),

# ── Ambiguous messages  E046-E055 ─────────────────────────────────────────────
E("E046","AccountWorker","QUERY_TENANT","admin","Raj dues",
  expected_intent="QUERY_TENANT",confidence=0.55,tags=["ambiguous"]),
E("E047","AccountWorker","QUERY_TENANT","admin","show Raj account",
  expected_intent="QUERY_TENANT",confidence=0.65,tags=["ambiguous"]),
E("E048","AccountWorker","UNKNOWN","admin","15000",
  expected_intent="UNKNOWN",confidence=0.40,tags=["ambiguous"]),
E("E049","AccountWorker","UNKNOWN","admin","paid",
  expected_intent="UNKNOWN",confidence=0.40,tags=["ambiguous"]),
E("E050","OwnerWorker","ROOM_STATUS","admin","room 205",
  expected_intent="ROOM_STATUS",confidence=0.60,tags=["ambiguous"]),
E("E051","AccountWorker","REPORT","admin","March report",
  expected_intent="REPORT",confidence=0.50,tags=["ambiguous"]),
E("E052","AccountWorker","QUERY_VACANT_ROOMS","admin","vacancy report",
  expected_intent="QUERY_VACANT_ROOMS",confidence=0.55,tags=["ambiguous"]),
E("E053","OwnerWorker","CHECKOUT","admin","checkout",
  expected_intent="CHECKOUT",confidence=0.65,tags=["ambiguous"]),
E("E054","OwnerWorker","CHECKOUT","admin","Raj checkout",
  expected_intent="CHECKOUT",confidence=0.70,tags=["ambiguous"]),
E("E055","AccountWorker","QUERY_TENANT","admin","payment history",
  expected_intent="QUERY_TENANT",confidence=0.60,tags=["ambiguous"]),

# ── Multi-step flow starters  E056-E070 ───────────────────────────────────────
# These test the FIRST message that triggers a multi-step flow
E("E056","OwnerWorker","START_ONBOARDING","admin","start onboarding for TestUser 9199000001",
  expected_intent="START_ONBOARDING",tags=["flow","multistep"]),
E("E057","OwnerWorker","RECORD_CHECKOUT","admin","record checkout TestUser",
  expected_intent="RECORD_CHECKOUT",tags=["flow","multistep"]),
# Simulated onboarding step responses (tenant phone, active session assumed)
E("E058","TenantWorker","UNKNOWN","tenant","Male",
  expected_intent="UNKNOWN",confidence=0.0,tags=["flow","multistep","onboarding"]),
E("E059","TenantWorker","UNKNOWN","tenant","1995-06-15",
  expected_intent="UNKNOWN",confidence=0.0,tags=["flow","multistep","onboarding"]),
E("E060","TenantWorker","UNKNOWN","tenant","Rajesh Kumar",
  expected_intent="UNKNOWN",confidence=0.0,tags=["flow","multistep","onboarding"]),
E("E061","TenantWorker","UNKNOWN","tenant","9876500000",
  expected_intent="UNKNOWN",confidence=0.0,tags=["flow","multistep","onboarding"]),
E("E062","TenantWorker","UNKNOWN","tenant","123 MG Road Bangalore 560001",
  expected_intent="UNKNOWN",confidence=0.0,tags=["flow","multistep","onboarding"]),
E("E063","TenantWorker","UNKNOWN","tenant","skip",
  expected_intent="UNKNOWN",confidence=0.0,tags=["flow","multistep","onboarding"]),
E("E064","TenantWorker","UNKNOWN","tenant","Software Engineer",
  expected_intent="UNKNOWN",confidence=0.0,tags=["flow","multistep","onboarding"]),
E("E065","TenantWorker","UNKNOWN","tenant","Aadhar",
  expected_intent="UNKNOWN",confidence=0.0,tags=["flow","multistep","onboarding"]),
E("E066","TenantWorker","UNKNOWN","tenant","1234-5678-9012",
  expected_intent="UNKNOWN",confidence=0.0,tags=["flow","multistep","onboarding"]),
# Checkout flow step responses (owner phone, active PendingAction assumed)
E("E067","OwnerWorker","UNKNOWN","admin","yes",
  expected_intent="UNKNOWN",confidence=0.0,tags=["flow","multistep","checkout"]),
E("E068","OwnerWorker","UNKNOWN","admin","no",
  expected_intent="UNKNOWN",confidence=0.0,tags=["flow","multistep","checkout"]),
E("E069","OwnerWorker","UNKNOWN","admin","yes minor damage",
  expected_intent="UNKNOWN",confidence=0.0,tags=["flow","multistep","checkout"]),
E("E070","OwnerWorker","SCHEDULE_CHECKOUT","admin","5000 by March 31",
  expected_intent="SCHEDULE_CHECKOUT",confidence=0.50,tags=["flow","multistep","checkout"]),

# ── Rapid fire / stress  E071-E075 ────────────────────────────────────────────
E("E071","AccountWorker","QUERY_DUES","admin","who hasn't paid",
  tags=["stress","rapid"]),
E("E072","AccountWorker","REPORT","admin","monthly report",
  tags=["stress","rapid"]),
E("E073","OwnerWorker","QUERY_VACANT_ROOMS","admin","vacant rooms",
  tags=["stress","rapid"]),
E("E074","OwnerWorker","QUERY_OCCUPANCY","admin","occupancy",
  tags=["stress","rapid"]),
E("E075","LeadWorker","ROOM_PRICE","lead","price",
  tags=["stress","rapid"]),

]

# ─────────────────────────────────────────────────────────────────────────────

assert len(scenarios) >= 500, f"Expected >= 500 scenarios, got {len(scenarios)}"

data = {
    "meta": {
        "version": "1.0.0",
        "total": len(scenarios),
        "created": "2026-03-14",
        "description": "500-scenario test suite for Cozeevo PG Accountant v1.4.0",
        "workers": {
            "AccountWorker": len([s for s in scenarios if s["worker"] == "AccountWorker"]),
            "OwnerWorker":   len([s for s in scenarios if s["worker"] == "OwnerWorker"]),
            "TenantWorker":  len([s for s in scenarios if s["worker"] == "TenantWorker"]),
            "LeadWorker":    len([s for s in scenarios if s["worker"] == "LeadWorker"]),
        },
        "phones": {
            "admin":     "+917845952289",
            "power_user":"+917358341775",
            "key_user":  "CONFIGURE_KEY_USER_PHONE",   # set a real key_user phone
            "tenant":    "CONFIGURE_TENANT_PHONE",     # set a real tenant phone from DB
            "lead":      "+919000000001",               # unknown number — acts as lead
        },
    },
    "scenarios": scenarios,
}

OUT.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"[OK] Generated {len(scenarios)} scenarios -> {OUT}")

# Print breakdown
print("\nScenario breakdown:")
for w, n in data["meta"]["workers"].items():
    print(f"  {w:20s}: {n}")

# Count by intent
from collections import Counter
intent_counts = Counter(s["expected_intent"] for s in scenarios)
print(f"\nTop 15 intents:")
for intent, count in intent_counts.most_common(15):
    print(f"  {intent:25s}: {count}")
