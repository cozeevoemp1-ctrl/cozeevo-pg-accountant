"""
Comprehensive NLP test suite for ConversationAgent.
20 natural language variations per intent group — messy, real-world typing.
Includes spelling mistakes, abbreviations, Indian English patterns.

Run: PYTHONIOENCODING=utf-8 python tests/test_agent_nlp.py
     PYTHONIOENCODING=utf-8 python tests/test_agent_nlp.py --group PAYMENT_LOG
Requires: GROQ_API_KEY in .env
"""
import asyncio
import os
import sys
import json
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

from src.llm_gateway.agents.conversation_agent import _call_llm
from src.llm_gateway.agents.prompt_builder import build_system_prompt

PG_CONFIG = {
    "pg_name": "Cozeevo Co-living",
    "brand_name": "Cozeevo Help Desk",
    "brand_voice": "Be concise, professional, and helpful. Use simple English.",
    "buildings": [
        {"name": "THOR", "floors": 7, "type": "male"},
        {"name": "HULK", "floors": 6, "type": "female"},
    ],
    "admin_phones": ["+917845952289"],
    "pricing": {"sharing_3": 7500, "sharing_2": 9000, "single": 12000, "single_ac": 15000},
    "expense_categories": ["Electricity", "Water", "Salaries", "Food", "Maintenance", "Plumbing", "Internet", "Gas", "Furniture", "Security"],
    "business_rules": {"proration": "first_month_standard_only", "checkout_notice_day": 5},
    "custom_intents": [],
}

# ═══════════════════════════════════════════════════════════════════════════════
# TEST CASES: (message, expected_intent, role)
# 20 variations per group — messy, real typing, spelling mistakes, shortcuts
# ═══════════════════════════════════════════════════════════════════════════════

TESTS = [
    # ── PAYMENT_LOG (20) ─────────────────────────────────────────────────────
    ("Raj paid 15000 cash", "PAYMENT_LOG", "admin"),
    ("received 8k frm room 203", "PAYMENT_LOG", "admin"),
    ("suresh gave 7500 upi", "PAYMENT_LOG", "admin"),
    ("collectd rent from amit 9000", "PAYMENT_LOG", "admin"),
    ("got 12000 from priya gpay", "PAYMENT_LOG", "admin"),
    ("rahul paid his rent tday", "PAYMENT_LOG", "admin"),
    ("15k recd via phonepe room 401", "PAYMENT_LOG", "admin"),
    ("tnant in 102 paid 7500 by csh", "PAYMENT_LOG", "admin"),
    ("log pymnt deepak 9000", "PAYMENT_LOG", "admin"),
    ("room 508 paid full amnt", "PAYMENT_LOG", "admin"),
    ("arun transferd 15000 to bnk", "PAYMENT_LOG", "admin"),
    ("just collectd 7.5k frm venkat", "PAYMENT_LOG", "admin"),
    ("rent money came from karthik 12000", "PAYMENT_LOG", "admin"),
    ("mohans payment 9000 csh", "PAYMENT_LOG", "admin"),
    ("upi paymet from sanjay 15000", "PAYMENT_LOG", "admin"),
    ("new paymet - ravi room 201 amout 7500", "PAYMENT_LOG", "admin"),
    ("recrd payment for naveen 8000", "PAYMENT_LOG", "admin"),
    ("ahmed paid rnt 9k through phonpe", "PAYMENT_LOG", "admin"),
    ("receivd deposit frm new tennt 15000", "PAYMENT_LOG", "admin"),
    ("305 wala ne 7500 diya cash me", "PAYMENT_LOG", "admin"),

    # ── QUERY_DUES (20) ──────────────────────────────────────────────────────
    ("who hasnt paid this mnth", "QUERY_DUES", "admin"),
    ("pending paymnts", "QUERY_DUES", "admin"),
    ("show me defaultrs", "QUERY_DUES", "admin"),
    ("dues list", "QUERY_DUES", "admin"),
    ("who owes mney", "QUERY_DUES", "admin"),
    ("unpaid tenats", "QUERY_DUES", "admin"),
    ("outstandng balances", "QUERY_DUES", "admin"),
    ("how many havnt paid rent", "QUERY_DUES", "admin"),
    ("list of pendng dues", "QUERY_DUES", "admin"),
    ("who all r pending for march", "QUERY_DUES", "admin"),
    ("rent not paid lst", "QUERY_DUES", "admin"),
    ("any pendng payments tday", "QUERY_DUES", "admin"),
    ("check who didnt pay", "QUERY_DUES", "admin"),
    ("paymet status all tenants", "QUERY_DUES", "admin"),
    ("how much pendng collection", "QUERY_DUES", "admin"),
    ("total outstndng this month", "QUERY_DUES", "admin"),
    ("show overdu tenants", "QUERY_DUES", "admin"),
    ("whch rooms havnt paid", "QUERY_DUES", "admin"),
    ("monthly pendng report", "QUERY_DUES", "admin"),
    ("collectn status", "QUERY_DUES", "admin"),

    # ── QUERY_TENANT (20) ─────────────────────────────────────────────────────
    ("raj balance", "QUERY_TENANT", "admin"),
    ("room 203 detils", "QUERY_TENANT", "admin"),
    ("wat is priyas rent", "QUERY_TENANT", "admin"),
    ("how much does room 102 owe", "QUERY_TENANT", "admin"),
    ("chek tenant amit status", "QUERY_TENANT", "admin"),
    ("show deepaks paymet history", "QUERY_TENANT", "admin"),
    ("who is in room 401", "QUERY_TENANT", "admin"),
    ("suresh dues", "QUERY_TENANT", "admin"),
    ("tell me abt room 305", "QUERY_TENANT", "admin"),
    ("karthiks rent detals", "QUERY_TENANT", "admin"),
    ("balance of room 508", "QUERY_TENANT", "admin"),
    ("wats pending for venkat", "QUERY_TENANT", "admin"),
    ("room 201 info", "QUERY_TENANT", "admin"),
    ("how much has mohan paid", "QUERY_TENANT", "admin"),
    ("naveen paymet status", "QUERY_TENANT", "admin"),
    ("tennt details for room g05", "QUERY_TENANT", "admin"),
    ("ahmeds accnt", "QUERY_TENANT", "admin"),
    ("room 612 balance chk", "QUERY_TENANT", "admin"),
    ("what rent is ravi payng", "QUERY_TENANT", "admin"),
    ("chck 203", "QUERY_TENANT", "admin"),

    # ── ADD_TENANT (20) ───────────────────────────────────────────────────────
    ("add new tennt", "ADD_TENANT", "admin"),
    ("new checkin in room 305", "ADD_TENANT", "admin"),
    ("registr tenant arjun", "ADD_TENANT", "admin"),
    ("admit new prson in 201", "ADD_TENANT", "admin"),
    ("new admision today", "ADD_TENANT", "admin"),
    ("alot room 102 to sanjay", "ADD_TENANT", "admin"),
    ("check in new tennt", "ADD_TENANT", "admin"),
    ("add priya to room 408", "ADD_TENANT", "admin"),
    ("new joinng", "ADD_TENANT", "admin"),
    ("somone is moving in tday", "ADD_TENANT", "admin"),
    ("registr new membr rahul", "ADD_TENANT", "admin"),
    ("new tennt comng today room 305", "ADD_TENANT", "admin"),
    ("add a new residnt", "ADD_TENANT", "admin"),
    ("checkin procss for vikram", "ADD_TENANT", "admin"),
    ("new guy chkng in room 501", "ADD_TENANT", "admin"),
    ("tenant registraton", "ADD_TENANT", "admin"),
    ("add occupnt to room 103", "ADD_TENANT", "admin"),
    ("book room 205 for new tennt", "ADD_TENANT", "admin"),
    ("new person joinng room 612", "ADD_TENANT", "admin"),
    ("create tennt arun room 301", "ADD_TENANT", "admin"),

    # ── CHECKOUT (20) ─────────────────────────────────────────────────────────
    ("raj is leavng today", "CHECKOUT", "admin"),
    ("chckout room 203", "CHECKOUT", "admin"),
    ("priya vacatng now", "CHECKOUT", "admin"),
    ("tennt in 305 wants to leav", "CHECKOUT", "admin"),
    ("room 102 chekout", "CHECKOUT", "admin"),
    ("amit is movng out", "CHECKOUT", "admin"),
    ("exit prcess for deepak", "CHECKOUT", "admin"),
    ("vacate room 401", "CHECKOUT", "admin"),
    ("suresh leavng today itslf", "CHECKOUT", "admin"),
    ("process chekout for room 508", "CHECKOUT", "admin"),
    ("tennt leaving frm 201", "CHECKOUT", "admin"),
    ("mohan wnts to vacate", "CHECKOUT", "admin"),
    ("room 612 prson is going", "CHECKOUT", "admin"),
    ("chck out karthik", "CHECKOUT", "admin"),
    ("exit naveen frm room 301", "CHECKOUT", "admin"),
    ("tennt in 103 is leavng now", "CHECKOUT", "admin"),
    ("ravi chekout today", "CHECKOUT", "admin"),
    ("vacatng room 205", "CHECKOUT", "admin"),
    ("ahmed leavng the pg", "CHECKOUT", "admin"),
    ("immedtae checkout room 501", "CHECKOUT", "admin"),

    # ── ADD_EXPENSE (20) ──────────────────────────────────────────────────────
    ("electrcity bill 45000", "ADD_EXPENSE", "admin"),
    ("paid plumbr 2500", "ADD_EXPENSE", "admin"),
    ("salry for staff 35000", "ADD_EXPENSE", "admin"),
    ("maintnance charge 5000", "ADD_EXPENSE", "admin"),
    ("watr tanker 3500", "ADD_EXPENSE", "admin"),
    ("bought cleanng supplies 1200", "ADD_EXPENSE", "admin"),
    ("pest contrl service 3000", "ADD_EXPENSE", "admin"),
    ("intrnet bill this mnth 4500", "ADD_EXPENSE", "admin"),
    ("paid electrcian 1500", "ADD_EXPENSE", "admin"),
    ("gas cylndr 1100", "ADD_EXPENSE", "admin"),
    ("new matress 3500", "ADD_EXPENSE", "admin"),
    ("securty guard salary 12000", "ADD_EXPENSE", "admin"),
    ("paintng work 8000", "ADD_EXPENSE", "admin"),
    ("wifi routr replacement 2500", "ADD_EXPENSE", "admin"),
    ("garbge collection 500", "ADD_EXPENSE", "admin"),
    ("plumbing repir 1800", "ADD_EXPENSE", "admin"),
    ("food expnse 15000 this week", "ADD_EXPENSE", "admin"),
    ("ac servce charge 2000", "ADD_EXPENSE", "admin"),
    ("lift maintnance 5000", "ADD_EXPENSE", "admin"),
    ("proprty tax 25000", "ADD_EXPENSE", "admin"),

    # ── REPORT (20) — with different filters ──────────────────────────────────
    ("monthly reprt", "REPORT", "admin"),
    ("show me p&l", "REPORT", "admin"),
    ("collecton summary", "REPORT", "admin"),
    ("financal report for march", "REPORT", "admin"),
    ("how much did we colect this mnth", "REPORT", "admin"),
    ("revnue summary", "REPORT", "admin"),
    ("total incme this month", "REPORT", "admin"),
    ("profit and los", "REPORT", "admin"),
    ("give me the numbrs", "REPORT", "admin"),
    ("monthly summry report", "REPORT", "admin"),
    ("march collecton report", "REPORT", "admin"),
    ("income vs expnses", "REPORT", "admin"),
    ("total rent collectd", "REPORT", "admin"),
    ("this months financals", "REPORT", "admin"),
    ("how much money came in", "REPORT", "admin"),
    ("overall financal status", "REPORT", "admin"),
    ("busines report", "REPORT", "admin"),
    ("april report please", "REPORT", "admin"),
    ("show collection for feb and march", "REPORT", "admin"),
    ("quarterly report", "REPORT", "admin"),

    # ── COMPLAINT_REGISTER (20) ───────────────────────────────────────────────
    ("no watr in room 203", "COMPLAINT_REGISTER", "admin"),
    ("ac not workng in 305", "COMPLAINT_REGISTER", "admin"),
    ("fan brokn in room 102", "COMPLAINT_REGISTER", "admin"),
    ("toilet is leakng", "COMPLAINT_REGISTER", "admin"),
    ("wifi not wrking", "COMPLAINT_REGISTER", "admin"),
    ("no hot watr on 3rd flor", "COMPLAINT_REGISTER", "admin"),
    ("powr cut in room 401", "COMPLAINT_REGISTER", "admin"),
    ("door lok is broken room 508", "COMPLAINT_REGISTER", "admin"),
    ("cockroch problm in kitchen", "COMPLAINT_REGISTER", "admin"),
    ("watr seepage in room 201", "COMPLAINT_REGISTER", "admin"),
    ("bathrom light not workng", "COMPLAINT_REGISTER", "admin"),
    ("room 612 windw broken", "COMPLAINT_REGISTER", "admin"),
    ("washng machine not workng", "COMPLAINT_REGISTER", "admin"),
    ("geysr problm in 301", "COMPLAINT_REGISTER", "admin"),
    ("bed bug isue in room 103", "COMPLAINT_REGISTER", "admin"),
    ("lift is not wrking", "COMPLAINT_REGISTER", "admin"),
    ("generatr not starting", "COMPLAINT_REGISTER", "admin"),
    ("room 205 drainage blockd", "COMPLAINT_REGISTER", "admin"),
    ("mosquto problem on ground flor", "COMPLAINT_REGISTER", "admin"),
    ("no electricty in room 501", "COMPLAINT_REGISTER", "admin"),

    # ── QUERY_VACANT_ROOMS (20) — different room/bed conditions ───────────────
    ("any vacnt rooms", "QUERY_VACANT_ROOMS", "admin"),
    ("empty beds availble", "QUERY_VACANT_ROOMS", "admin"),
    ("which roms are free", "QUERY_VACANT_ROOMS", "admin"),
    ("vacancy staus", "QUERY_VACANT_ROOMS", "admin"),
    ("how many beds emty", "QUERY_VACANT_ROOMS", "admin"),
    ("availble rooms in thor", "QUERY_VACANT_ROOMS", "admin"),
    ("any singl room availble", "QUERY_VACANT_ROOMS", "admin"),
    ("vacant roms list", "QUERY_VACANT_ROOMS", "admin"),
    ("is ther any space", "QUERY_VACANT_ROOMS", "admin"),
    ("check vacncy", "QUERY_VACANT_ROOMS", "admin"),
    ("rooms for new tennt", "QUERY_VACANT_ROOMS", "admin"),
    ("emty rooms in hulk bldng", "QUERY_VACANT_ROOMS", "admin"),
    ("do we hav any vacancy", "QUERY_VACANT_ROOMS", "admin"),
    ("show availble beds", "QUERY_VACANT_ROOMS", "admin"),
    ("how many roms vacant", "QUERY_VACANT_ROOMS", "admin"),
    ("free rooms on 3rd flor", "QUERY_VACANT_ROOMS", "admin"),
    ("any double sharng available", "QUERY_VACANT_ROOMS", "admin"),
    ("vacncy in male building", "QUERY_VACANT_ROOMS", "admin"),
    ("open roms", "QUERY_VACANT_ROOMS", "admin"),
    ("availablty check", "QUERY_VACANT_ROOMS", "admin"),

    # ── ADD_CONTACT (20) ──────────────────────────────────────────────────────
    ("add plumbr rajan 9876543210", "ADD_CONTACT", "admin"),
    ("save electrican contact 8765432109", "ADD_CONTACT", "admin"),
    ("new contct - ac service guy 7654321098", "ADD_CONTACT", "admin"),
    ("add vendpr shiva plumber 9988776655", "ADD_CONTACT", "admin"),
    ("save lineman numbr 9112233445", "ADD_CONTACT", "admin"),
    ("registr contct for carpenter 8899001122", "ADD_CONTACT", "admin"),
    ("add pest contrl guy numbr 9090909090", "ADD_CONTACT", "admin"),
    ("new contact wifi technican 8080808080", "ADD_CONTACT", "admin"),
    ("save watr tanker person 7070707070", "ADD_CONTACT", "admin"),
    ("add balu paintng 6060606060", "ADD_CONTACT", "admin"),
    ("save garbage collctor numbr 9191919191", "ADD_CONTACT", "admin"),
    ("new contct generator mechnic 8181818181", "ADD_CONTACT", "admin"),
    ("add gas supply guy 7171717171", "ADD_CONTACT", "admin"),
    ("save locksmth number 6161616161", "ADD_CONTACT", "admin"),
    ("registr mason contact 9292929292", "ADD_CONTACT", "admin"),
    ("add securty agency numbr 8282828282", "ADD_CONTACT", "admin"),
    ("new vendpr - cctv repir 7272727272", "ADD_CONTACT", "admin"),
    ("save interor decorator 6262626262", "ADD_CONTACT", "admin"),
    ("add weldr contact 9393939393", "ADD_CONTACT", "admin"),
    ("save building electrican vinay 8383838383", "ADD_CONTACT", "admin"),

    # ── QUERY_CONTACTS (20) ───────────────────────────────────────────────────
    ("plumbr number", "QUERY_CONTACTS", "admin"),
    ("send me electrcian contact", "QUERY_CONTACTS", "admin"),
    ("who is our ac servce guy", "QUERY_CONTACTS", "admin"),
    ("carpentr contact pls", "QUERY_CONTACTS", "admin"),
    ("get me plumbrs phone", "QUERY_CONTACTS", "admin"),
    ("lineman numbr?", "QUERY_CONTACTS", "admin"),
    ("do we hav pest control contct", "QUERY_CONTACTS", "admin"),
    ("wifi techncan number", "QUERY_CONTACTS", "admin"),
    ("send rajans numbr", "QUERY_CONTACTS", "admin"),
    ("watr tanker contct", "QUERY_CONTACTS", "admin"),
    ("paintr contact", "QUERY_CONTACTS", "admin"),
    ("garbge collectr phone", "QUERY_CONTACTS", "admin"),
    ("generator mechnic numbr", "QUERY_CONTACTS", "admin"),
    ("gas supplyr contact", "QUERY_CONTACTS", "admin"),
    ("locksmth number please", "QUERY_CONTACTS", "admin"),
    ("masn phone numbr", "QUERY_CONTACTS", "admin"),
    ("securty agency contct", "QUERY_CONTACTS", "admin"),
    ("cctv repir guy numbr", "QUERY_CONTACTS", "admin"),
    ("show all vendpr contacts", "QUERY_CONTACTS", "admin"),
    ("vinays phone numbr", "QUERY_CONTACTS", "admin"),

    # ── UPDATE_TENANT_NOTES (20) — permanent & temporary notes ────────────────
    ("add note for raj - late payr always", "UPDATE_TENANT_NOTES", "admin"),
    ("update priya notes - agrred to pay by 5th evry month", "UPDATE_TENANT_NOTES", "admin"),
    ("note for room 203 - tennt has pet dog approvd", "UPDATE_TENANT_NOTES", "admin"),
    ("add permannt note deepak - no cooking alowed in room", "UPDATE_TENANT_NOTES", "admin"),
    ("update notes amit - deposit adjustd for damage", "UPDATE_TENANT_NOTES", "admin"),
    ("add remark for suresh - given extra matress", "UPDATE_TENANT_NOTES", "admin"),
    ("note: room 401 tennt parkng spot allotd", "UPDATE_TENANT_NOTES", "admin"),
    ("save note for venkat - agreed rent 8500 from next mnth", "UPDATE_TENANT_NOTES", "admin"),
    ("room 508 note - ac installd tennt bearng cost", "UPDATE_TENANT_NOTES", "admin"),
    ("add temp note mohan - on vacaton till 15th", "UPDATE_TENANT_NOTES", "admin"),
    ("update naveen notes - key depositd at reception", "UPDATE_TENANT_NOTES", "admin"),
    ("add agreemnt note for karthik - 6 month lockin", "UPDATE_TENANT_NOTES", "admin"),
    ("note for ahmed room 301 - medical emrgncy contact updtd", "UPDATE_TENANT_NOTES", "admin"),
    ("permnt note ravi - vegetarin only food", "UPDATE_TENANT_NOTES", "admin"),
    ("save remrk for sanjay - works night shft quiet hours", "UPDATE_TENANT_NOTES", "admin"),
    ("temprory note room 205 - maintennce pendng", "UPDATE_TENANT_NOTES", "admin"),
    ("add note vikram - ID proof pending submision", "UPDATE_TENANT_NOTES", "admin"),
    ("update agrement for room 612 - extendend till june", "UPDATE_TENANT_NOTES", "admin"),
    ("note: arjun has complaned about noisy neigbor", "UPDATE_TENANT_NOTES", "admin"),
    ("add special note for room 103 - female gust not allowd", "UPDATE_TENANT_NOTES", "admin"),

    # ── QUERY_OCCUPANCY (20) ──────────────────────────────────────────────────
    ("occupancy", "QUERY_OCCUPANCY", "admin"),
    ("how full are we", "QUERY_OCCUPANCY", "admin"),
    ("how many tenats total", "QUERY_OCCUPANCY", "admin"),
    ("occupncy rate", "QUERY_OCCUPANCY", "admin"),
    ("what percnt rooms filled", "QUERY_OCCUPANCY", "admin"),
    ("total occupnts", "QUERY_OCCUPANCY", "admin"),
    ("how many ppl livng here", "QUERY_OCCUPANCY", "admin"),
    ("occupncy for thor", "QUERY_OCCUPANCY", "admin"),
    ("hulk buildng occupancy", "QUERY_OCCUPANCY", "admin"),
    ("how many beds occupid", "QUERY_OCCUPANCY", "admin"),
    ("currnt occupancy percntage", "QUERY_OCCUPANCY", "admin"),
    ("total residents", "QUERY_OCCUPANCY", "admin"),
    ("are we full", "QUERY_OCCUPANCY", "admin"),
    ("capacity utilzation", "QUERY_OCCUPANCY", "admin"),
    ("headcount", "QUERY_OCCUPANCY", "admin"),
    ("how many stayng in thor", "QUERY_OCCUPANCY", "admin"),
    ("total beds in use", "QUERY_OCCUPANCY", "admin"),
    ("occupancy numbrs", "QUERY_OCCUPANCY", "admin"),
    ("how packed are we", "QUERY_OCCUPANCY", "admin"),
    ("building wise occupncy", "QUERY_OCCUPANCY", "admin"),

    # ── CONVERSATION (20) — greetings, thanks, identity ──────────────────────
    ("good mornng", "CONVERSE", "admin"),
    ("hello", "CONVERSE", "admin"),
    ("thnk you", "CONVERSE", "admin"),
    ("thnks for ur help", "CONVERSE", "admin"),
    ("who r u", "CONVERSE", "admin"),
    ("what cn you do", "CONVERSE", "admin"),
    ("how r u", "CONVERSE", "admin"),
    ("nice wrk", "CONVERSE", "admin"),
    ("ok got it", "CONVERSE", "admin"),
    ("bye", "CONVERSE", "admin"),
    ("good nite", "CONVERSE", "admin"),
    ("wats ur name", "CONVERSE", "admin"),
    ("r u a robot", "CONVERSE", "admin"),
    ("hmm ok", "CONVERSE", "admin"),
    ("thats grt", "CONVERSE", "admin"),
    ("perfct", "CONVERSE", "admin"),
    ("alrght", "CONVERSE", "admin"),
    ("oh i see", "CONVERSE", "admin"),
    ("no worres", "CONVERSE", "admin"),
    ("cool thnks", "CONVERSE", "admin"),

    # ── TENANT: MY_BALANCE (20) ──────────────────────────────────────────────
    ("how much do i owe", "MY_BALANCE", "tenant"),
    ("my dues", "MY_BALANCE", "tenant"),
    ("wats my balance", "MY_BALANCE", "tenant"),
    ("pendng amount", "MY_BALANCE", "tenant"),
    ("am i clear on rent", "MY_BALANCE", "tenant"),
    ("how much rent pendng", "MY_BALANCE", "tenant"),
    ("do i owe anythng", "MY_BALANCE", "tenant"),
    ("my outstndng", "MY_BALANCE", "tenant"),
    ("chek my dues", "MY_BALANCE", "tenant"),
    ("am i paid up", "MY_BALANCE", "tenant"),
    ("kitna baki hai", "MY_BALANCE", "tenant"),
    ("mera balanc", "MY_BALANCE", "tenant"),
    ("pendng rent", "MY_BALANCE", "tenant"),
    ("have i paid this mnth", "MY_BALANCE", "tenant"),
    ("my rent staus", "MY_BALANCE", "tenant"),
    ("is my rent paid", "MY_BALANCE", "tenant"),
    ("outstandng dues pls", "MY_BALANCE", "tenant"),
    ("balance enqury", "MY_BALANCE", "tenant"),
    ("show my pendng", "MY_BALANCE", "tenant"),
    ("rent dues", "MY_BALANCE", "tenant"),

    # ── TENANT: MY_PAYMENTS (20) ─────────────────────────────────────────────
    ("my paymnt history", "MY_PAYMENTS", "tenant"),
    ("show my recepts", "MY_PAYMENTS", "tenant"),
    ("what did i pay", "MY_PAYMENTS", "tenant"),
    ("paymet receipts", "MY_PAYMENTS", "tenant"),
    ("my paymnt records", "MY_PAYMENTS", "tenant"),
    ("list my paymnts", "MY_PAYMENTS", "tenant"),
    ("paymnt log", "MY_PAYMENTS", "tenant"),
    ("previos payments", "MY_PAYMENTS", "tenant"),
    ("show all my paymnts", "MY_PAYMENTS", "tenant"),
    ("transction history", "MY_PAYMENTS", "tenant"),
    ("when did i last pay", "MY_PAYMENTS", "tenant"),
    ("my rent paymnts", "MY_PAYMENTS", "tenant"),
    ("recpt for last payment", "MY_PAYMENTS", "tenant"),
    ("paymet confrmation", "MY_PAYMENTS", "tenant"),
    ("all my transctns", "MY_PAYMENTS", "tenant"),
    ("march paymet recpt", "MY_PAYMENTS", "tenant"),
    ("did my paymet go thru", "MY_PAYMENTS", "tenant"),
    ("paymet summary", "MY_PAYMENTS", "tenant"),
    ("show recpt", "MY_PAYMENTS", "tenant"),
    ("my paymet detils", "MY_PAYMENTS", "tenant"),

    # ── LEAD: ROOM_PRICE (20) ────────────────────────────────────────────────
    ("how much is rent", "ROOM_PRICE", "lead"),
    ("wat are the chrges", "ROOM_PRICE", "lead"),
    ("monthly rent for singl room", "ROOM_PRICE", "lead"),
    ("pricng details", "ROOM_PRICE", "lead"),
    ("how much for dubble sharing", "ROOM_PRICE", "lead"),
    ("wats the cost", "ROOM_PRICE", "lead"),
    ("rent for ac room", "ROOM_PRICE", "lead"),
    ("tarif please", "ROOM_PRICE", "lead"),
    ("price list", "ROOM_PRICE", "lead"),
    ("how much per mnth", "ROOM_PRICE", "lead"),
    ("kitna rent hai", "ROOM_PRICE", "lead"),
    ("3 sharing rate", "ROOM_PRICE", "lead"),
    ("single room price", "ROOM_PRICE", "lead"),
    ("wat r ur rates", "ROOM_PRICE", "lead"),
    ("pricing for pg", "ROOM_PRICE", "lead"),
    ("montly charges", "ROOM_PRICE", "lead"),
    ("cheapest room pric", "ROOM_PRICE", "lead"),
    ("cost of livng here", "ROOM_PRICE", "lead"),
    ("rent details pls", "ROOM_PRICE", "lead"),
    ("how much wil it cost", "ROOM_PRICE", "lead"),

    # ── LEAD: AVAILABILITY (20) ──────────────────────────────────────────────
    ("any rooms availble", "AVAILABILITY", "lead"),
    ("is ther vacancy", "AVAILABILITY", "lead"),
    ("do u hav emty rooms", "AVAILABILITY", "lead"),
    ("room availble?", "AVAILABILITY", "lead"),
    ("any beds free", "AVAILABILITY", "lead"),
    ("vacncy hai kya", "AVAILABILITY", "lead"),
    ("can i get a rom", "AVAILABILITY", "lead"),
    ("space availble", "AVAILABILITY", "lead"),
    ("any opning", "AVAILABILITY", "lead"),
    ("room milega kya", "AVAILABILITY", "lead"),
    ("availblity check", "AVAILABILITY", "lead"),
    ("is ther a room for me", "AVAILABILITY", "lead"),
    ("emty rooms?", "AVAILABILITY", "lead"),
    ("vacnt beds", "AVAILABILITY", "lead"),
    ("room free hai", "AVAILABILITY", "lead"),
    ("can i join", "AVAILABILITY", "lead"),
    ("single room availble", "AVAILABILITY", "lead"),
    ("sharing bed availble", "AVAILABILITY", "lead"),
    ("any vacancy for male", "AVAILABILITY", "lead"),
    ("room chahiye", "AVAILABILITY", "lead"),

    # ── LEAD: VISIT_REQUEST (20) ──────────────────────────────────────────────
    ("can i visit", "VISIT_REQUEST", "lead"),
    ("i want to see the rooms", "VISIT_REQUEST", "lead"),
    ("can i come for a tour", "VISIT_REQUEST", "lead"),
    ("show me the pg", "VISIT_REQUEST", "lead"),
    ("i want to vist tmrw", "VISIT_REQUEST", "lead"),
    ("room dekhna hai", "VISIT_REQUEST", "lead"),
    ("can i come tday", "VISIT_REQUEST", "lead"),
    ("schedule a vist", "VISIT_REQUEST", "lead"),
    ("tour timng", "VISIT_REQUEST", "lead"),
    ("when can i come see", "VISIT_REQUEST", "lead"),
    ("want to check the place", "VISIT_REQUEST", "lead"),
    ("can i see the rooms tomorow", "VISIT_REQUEST", "lead"),
    ("pg dekhna tha", "VISIT_REQUEST", "lead"),
    ("i wnt to visit ur pg", "VISIT_REQUEST", "lead"),
    ("inspection possble?", "VISIT_REQUEST", "lead"),
    ("room visit", "VISIT_REQUEST", "lead"),
    ("show rooom", "VISIT_REQUEST", "lead"),
    ("can u show me arond", "VISIT_REQUEST", "lead"),
    ("walk throgh", "VISIT_REQUEST", "lead"),
    ("i want tour", "VISIT_REQUEST", "lead"),
]


# ── Runner ───────────────────────────────────────────────────────────────────

async def run_tests(filter_group=None):
    tests = TESTS
    if filter_group:
        tests = [(m, e, r) for m, e, r in TESTS if e.upper() == filter_group.upper()]
        if not tests:
            print(f"No tests found for group: {filter_group}")
            return

    total = len(tests)
    passed = 0
    failed = 0
    errors = []

    print(f"\n{'='*70}")
    print(f"  ConversationAgent NLP Test Suite - {total} tests")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*70}\n")

    prompts = {}
    for role in ("admin", "tenant", "lead"):
        prompts[role] = build_system_prompt(PG_CONFIG, role, [], "", "")

    current_group = ""
    group_pass = 0
    group_total = 0

    for i, (message, expected, role) in enumerate(tests):
        group = expected
        if group != current_group:
            if current_group:
                pct = (group_pass / group_total * 100) if group_total else 0
                print(f"  {'='*50}")
                print(f"  {current_group}: {group_pass}/{group_total} ({pct:.0f}%)\n")
            current_group = group
            group_pass = 0
            group_total = 0
            print(f"  --- {group} ({role}) ---")

        group_total += 1

        try:
            result = await _call_llm(prompts[role], message)

            if expected == "CONVERSE":
                ok = result.action == "converse"
                actual = f"action={result.action}"
            else:
                actual_intent = (result.intent or "").upper()
                ok = actual_intent == expected.upper()
                if not ok and result.action == "ask_options" and result.options:
                    ok = expected.upper() in [o.upper() for o in result.options]
                actual = f"{result.intent} ({result.confidence:.2f})"

            if ok:
                passed += 1
                group_pass += 1
                print(f"  [PASS] \"{message}\" -> {actual}")
            else:
                failed += 1
                errors.append((message, expected, actual, role))
                print(f"  [FAIL] \"{message}\" -> {actual} (expected {expected})")

        except Exception as e:
            failed += 1
            errors.append((message, expected, f"ERROR: {e}", role))
            print(f"  [ERR]  \"{message}\" -> {e}")

        await asyncio.sleep(0.5)

    if current_group:
        pct = (group_pass / group_total * 100) if group_total else 0
        print(f"  {'='*50}")
        print(f"  {current_group}: {group_pass}/{group_total} ({pct:.0f}%)\n")

    pct = (passed / total * 100) if total else 0
    print(f"\n{'='*70}")
    print(f"  RESULTS: {passed}/{total} passed ({pct:.1f}%)")
    print(f"  Failed: {failed}")
    print(f"{'='*70}")

    if errors:
        print(f"\n  FAILURES:")
        for msg, expected, actual, role in errors:
            print(f"    [{role}] \"{msg}\"")
            print(f"      Expected: {expected}")
            print(f"      Got:      {actual}")

    results = {
        "timestamp": datetime.now().isoformat(),
        "total": total,
        "passed": passed,
        "failed": failed,
        "pass_rate": round(pct, 1),
        "failures": [
            {"message": msg, "expected": exp, "actual": act, "role": role}
            for msg, exp, act, role in errors
        ],
    }
    with open("tests/agent_nlp_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n  Results saved to tests/agent_nlp_results.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", help="Run only one intent group (e.g. PAYMENT_LOG)")
    args = parser.parse_args()
    asyncio.run(run_tests(args.group))
