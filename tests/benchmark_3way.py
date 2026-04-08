"""
3-way benchmark: Regex vs Haiku (paid) vs Groq/Llama 3.3 70B (free).
Extended test suite with natural language, Hindi, typos, edge cases.

Usage: python tests/benchmark_3way.py
"""
import sys, os, time, asyncio, json
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

import httpx
from src.whatsapp.intent_detector import detect_intent
from src.llm_gateway.claude_client import get_claude_client, ClaudeClient
from src.llm_gateway.prompts import WHATSAPP_INTENT_PROMPT

GROQ_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
INTENTS_TEXT = ClaudeClient._OWNER_INTENTS


async def call_groq(message):
    prompt = WHATSAPP_INTENT_PROMPT.format(role="admin", intents=INTENTS_TEXT, message=message)
    headers = {"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"}
    payload = {"model": GROQ_MODEL, "messages": [{"role": "user", "content": prompt}],
               "temperature": 0.0, "max_tokens": 512}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload)
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"].strip()
        # Strip markdown code fences if present
        import re as _re
        clean = _re.sub(r'^```(?:json)?\s*', '', raw)
        clean = _re.sub(r'\s*```$', '', clean).strip()
        result = json.loads(clean)
        return str(result.get("intent", "UNKNOWN")).upper()


# ── Extended test suite ──────────────────────────────────────────────────────
TEST_CASES = [
    # === PAYMENT_LOG — 10 variants ===
    ("Raj paid 15000", "PAYMENT_LOG", "direct"),
    ("received 8k from room 203", "PAYMENT_LOG", "shorthand"),
    ("Krishnan paid rent 23500 upi", "PAYMENT_LOG", "with mode"),
    ("collect rent from Anuron", "PAYMENT_LOG", "collect"),
    ("15000 from room 105", "PAYMENT_LOG", "amount first"),
    ("Manideep ne 14000 diya", "PAYMENT_LOG", "hinglish"),
    ("payment received from Tanishka 20000", "PAYMENT_LOG", "formal"),
    ("log payment 13000 cash from 203", "PAYMENT_LOG", "explicit log"),
    ("Bala gave 15500 cash", "PAYMENT_LOG", "gave variant"),
    ("room 305 paid", "PAYMENT_LOG", "room paid"),

    # === QUERY_DUES — 6 variants ===
    ("who hasn't paid", "QUERY_DUES", "natural"),
    ("pending list", "QUERY_DUES", "short"),
    ("outstanding balances", "QUERY_DUES", "formal"),
    ("defaulters", "QUERY_DUES", "single word"),
    ("kitne logo ne rent nahi diya", "QUERY_DUES", "hindi"),
    ("unpaid tenants april", "QUERY_DUES", "month specific"),

    # === QUERY_TENANT — 8 variants ===
    ("Raj balance", "QUERY_TENANT", "name + balance"),
    ("room 203 details", "QUERY_TENANT", "room query"),
    ("what is rent for chinmay", "QUERY_TENANT", "natural"),
    ("show me details of room 102", "QUERY_TENANT", "verbose"),
    ("Anuron ka balance kya hai", "QUERY_TENANT", "hinglish"),
    ("how much does Kishan owe", "QUERY_TENANT", "owe variant"),
    ("tenant info for room 401", "QUERY_TENANT", "info variant"),
    ("what about Manideep", "QUERY_TENANT", "vague name"),

    # === ADD_TENANT — 5 variants ===
    ("add tenant Raju room 305", "ADD_TENANT", "direct"),
    ("new tenant check in", "ADD_TENANT", "natural"),
    ("admit Priya to room 401", "ADD_TENANT", "admit"),
    ("register new tenant", "ADD_TENANT", "register"),
    ("check in Suresh room 510", "ADD_TENANT", "check in"),

    # === CHECKOUT — 6 variants ===
    ("Raj is leaving", "CHECKOUT", "natural"),
    ("checkout room 203", "CHECKOUT", "direct"),
    ("Manideep leaving today", "CHECKOUT", "with today"),
    ("ja raha hai room 305", "CHECKOUT", "hindi"),
    ("Kishan wants to vacate", "CHECKOUT", "wants to"),
    ("room 401 tenant leaving", "CHECKOUT", "room first"),

    # === SCHEDULE_CHECKOUT — 4 variants ===
    ("Raj leaving on 15th april", "SCHEDULE_CHECKOUT", "with date"),
    ("Kishan vacating next month", "SCHEDULE_CHECKOUT", "next month"),
    ("schedule exit for room 305 on may 1st", "SCHEDULE_CHECKOUT", "formal"),
    ("Tanishka leaving end of month", "SCHEDULE_CHECKOUT", "end of month"),

    # === NOTICE_GIVEN — 3 variants ===
    ("Raj gave notice", "NOTICE_GIVEN", "direct"),
    ("Kishan wants to leave next month", "NOTICE_GIVEN", "natural"),
    ("1 month notice from room 203", "NOTICE_GIVEN", "formal"),

    # === ADD_EXPENSE — 6 variants ===
    ("log expense", "ADD_EXPENSE", "bare"),
    ("add expense electricity 5000", "ADD_EXPENSE", "with details"),
    ("paid plumber 3000 for bathroom fix", "ADD_EXPENSE", "natural"),
    ("salary payment 15000 to Lokesh", "ADD_EXPENSE", "salary"),
    ("water bill 2500", "ADD_EXPENSE", "bill"),
    ("internet bill paid 3000", "ADD_EXPENSE", "paid bill"),

    # === REPORT — 6 variants ===
    ("monthly report", "REPORT", "direct"),
    ("how much collected this month", "REPORT", "natural"),
    ("P&L for march", "REPORT", "specific"),
    ("collection summary", "REPORT", "summary"),
    ("how is april looking", "REPORT", "vague"),
    ("revenue this month", "REPORT", "revenue"),

    # === QUERY_VACANT_ROOMS — 4 variants ===
    ("vacant rooms", "QUERY_VACANT_ROOMS", "direct"),
    ("any empty beds", "QUERY_VACANT_ROOMS", "natural"),
    ("available rooms for female", "QUERY_VACANT_ROOMS", "filtered"),
    ("is there any room available", "QUERY_VACANT_ROOMS", "question"),

    # === QUERY_OCCUPANCY — 4 variants ===
    ("occupancy", "QUERY_OCCUPANCY", "single word"),
    ("how many tenants", "QUERY_OCCUPANCY", "natural"),
    ("how full are we", "QUERY_OCCUPANCY", "conversational"),
    ("total beds occupied", "QUERY_OCCUPANCY", "beds variant"),

    # === ADD_CONTACT — 5 variants ===
    ("add contact", "ADD_CONTACT", "bare"),
    ("add building electrician contact", "ADD_CONTACT", "with category"),
    ("save plumber Raju 9876543210", "ADD_CONTACT", "full details"),
    ("add Vinay electrician contact 7026668797", "ADD_CONTACT", "full"),
    ("new vendor contact", "ADD_CONTACT", "vendor"),

    # === QUERY_CONTACTS — 6 variants ===
    ("plumber number", "QUERY_CONTACTS", "direct"),
    ("show electrician contacts", "QUERY_CONTACTS", "show"),
    ("give me Shiva number", "QUERY_CONTACTS", "name specific"),
    ("send me electrician vinays contact", "QUERY_CONTACTS", "name + cat"),
    ("who is our plumber", "QUERY_CONTACTS", "who is"),
    ("I need painter details", "QUERY_CONTACTS", "I need"),

    # === UPDATE_CONTACT — 3 variants ===
    ("update contact Shiva", "UPDATE_CONTACT", "direct"),
    ("change Balu number", "UPDATE_CONTACT", "change number"),
    ("edit plumber notes", "UPDATE_CONTACT", "edit notes"),

    # === COMPLAINT_REGISTER — 5 variants ===
    ("no water in room 305", "COMPLAINT_REGISTER", "direct"),
    ("wifi not working", "COMPLAINT_REGISTER", "common"),
    ("fan broken in 203", "COMPLAINT_REGISTER", "broken"),
    ("AC leaking room 401", "COMPLAINT_REGISTER", "specific"),
    ("bathroom tap dripping 305", "COMPLAINT_REGISTER", "detailed"),

    # === LOG_VACATION — 3 variants ===
    ("Raj on vacation from 10th to 20th", "LOG_VACATION", "with dates"),
    ("Manideep going home for 5 days", "LOG_VACATION", "natural"),
    ("Kishan chutti pe hai 3 din", "LOG_VACATION", "hindi"),

    # === VOID_PAYMENT — 3 variants ===
    ("void payment for Raj", "VOID_PAYMENT", "direct"),
    ("cancel last payment", "VOID_PAYMENT", "cancel variant"),
    ("reverse Raj payment", "VOID_PAYMENT", "reverse"),

    # === RENT_CHANGE — 3 variants ===
    ("increase rent for Raj to 15000", "RENT_CHANGE", "direct"),
    ("change rent for room 305", "RENT_CHANGE", "room"),
    ("reduce rent for Kishan by 1000", "RENT_CHANGE", "reduce"),

    # === ACTIVITY_LOG — 3 variants ===
    ("log activity received 20 chairs", "ACTIVITY_LOG", "direct"),
    ("water tank cleaned today", "ACTIVITY_LOG", "maintenance"),
    ("generator serviced", "ACTIVITY_LOG", "serviced"),

    # === HELP — 4 variants ===
    ("help", "HELP", "single word"),
    ("hi", "HELP", "greeting"),
    ("hello", "HELP", "greeting"),
    ("what can you do", "HELP", "natural"),

    # === GET_WIFI_PASSWORD — 3 variants ===
    ("wifi password", "GET_WIFI_PASSWORD", "direct"),
    ("what is the wifi", "GET_WIFI_PASSWORD", "natural"),
    ("wifi for 3rd floor", "GET_WIFI_PASSWORD", "floor specific"),

    # === RULES — 2 variants ===
    ("pg rules", "RULES", "direct"),
    ("what are the rules", "RULES", "natural"),

    # === EDGE CASES / AMBIGUOUS ===
    ("Raj 31st March", "AMBIGUOUS", "ambiguous date"),
    ("what about room 203", "QUERY_TENANT", "vague"),
    ("cancel", "UNKNOWN", "bare cancel"),
    ("thanks", "UNKNOWN", "thanks"),
    ("ok", "UNKNOWN", "ack"),
    ("good morning", "HELP", "greeting variant"),
    ("hmmm", "UNKNOWN", "noise"),
    ("acha", "UNKNOWN", "hindi ack"),
    ("tell me about Anuron", "QUERY_TENANT", "tell me"),

    # === TYPOS / MESSY INPUT ===
    ("vaccant rooms", "QUERY_VACANT_ROOMS", "typo"),
    ("chek in new tenant", "ADD_TENANT", "typo"),
    ("whats the occupncy", "QUERY_OCCUPANCY", "typo"),
    ("plumbr contact", "QUERY_CONTACTS", "typo"),
]


async def run():
    ai = get_claude_client()
    total = len(TEST_CASES)

    regex_ok = 0; haiku_ok = 0; groq_ok = 0
    regex_ms_total = 0; haiku_ms_total = 0; groq_ms_total = 0
    results = []

    print(f"Running {total} tests: Regex vs Haiku vs Groq (Llama 3.3 70B)")
    print(f"{'='*140}")
    print(f"{'Message':42s} {'Expected':18s} {'Regex':14s}{'ms':>4s} {'Haiku':14s}{'ms':>5s} {'Groq':14s}{'ms':>5s} {'Best':>6s}")
    print(f"{'-'*140}")

    for msg, expected, ctx in TEST_CASES:
        # Regex
        t0 = time.time()
        r = detect_intent(msg, "admin")
        r_ms = (time.time() - t0) * 1000
        r_intent = r.intent
        regex_ms_total += r_ms

        # Haiku
        t0 = time.time()
        try:
            h = await ai.detect_whatsapp_intent(msg, "admin")
            h_intent = str(h.get("intent", "UNKNOWN")).upper()
        except:
            h_intent = "ERROR"
        h_ms = (time.time() - t0) * 1000
        haiku_ms_total += h_ms

        # Groq
        t0 = time.time()
        try:
            g_intent = await call_groq(msg)
        except Exception as e:
            g_intent = "ERROR"
        g_ms = (time.time() - t0) * 1000
        groq_ms_total += g_ms

        # Score
        def check(got, exp):
            if exp == "AMBIGUOUS": return got not in ("UNKNOWN", "ERROR")
            if exp == "UNKNOWN": return got in ("UNKNOWN", "HELP", "GENERAL", "AI_CONVERSE")
            return got == exp

        r_pass = check(r_intent, expected); h_pass = check(h_intent, expected); g_pass = check(g_intent, expected)
        if r_pass: regex_ok += 1
        if h_pass: haiku_ok += 1
        if g_pass: groq_ok += 1

        best = ""
        passes = []
        if r_pass: passes.append("R")
        if h_pass: passes.append("H")
        if g_pass: passes.append("G")
        best = "+".join(passes) if passes else "NONE"

        r_mark = "ok" if r_pass else "MISS"
        h_mark = "ok" if h_pass else "MISS"
        g_mark = "ok" if g_pass else "MISS"

        flag = "  " if len(passes) == 3 else ">>"
        print(f"{flag} {msg[:40]:40s} {expected:18s} {r_intent[:12]:12s} {r_mark:>4s} {r_ms:3.0f} {h_intent[:12]:12s} {h_mark:>4s} {h_ms:4.0f} {g_intent[:12]:12s} {g_mark:>4s} {g_ms:4.0f}  {best}")

        results.append({"msg": msg, "expected": expected, "ctx": ctx,
                        "r": r_intent, "h": h_intent, "g": g_intent,
                        "r_ok": r_pass, "h_ok": h_pass, "g_ok": g_pass,
                        "r_ms": r_ms, "h_ms": h_ms, "g_ms": g_ms})

        # Rate limit protection for Groq
        await asyncio.sleep(0.3)

    # Summary
    print(f"\n{'='*140}")
    print(f"{'RESULTS SUMMARY':^140}")
    print(f"{'='*140}")
    print(f"Total: {total} test cases\n")
    print(f"{'':20s} {'REGEX':>12s} {'HAIKU':>12s} {'GROQ':>12s}")
    print(f"{'-'*58}")
    print(f"{'Correct':20s} {regex_ok:>12d} {haiku_ok:>12d} {groq_ok:>12d}")
    print(f"{'Accuracy':20s} {regex_ok/total*100:>11.1f}% {haiku_ok/total*100:>11.1f}% {groq_ok/total*100:>11.1f}%")
    print(f"{'Total latency':20s} {regex_ms_total:>10.0f}ms {haiku_ms_total:>10.0f}ms {groq_ms_total:>10.0f}ms")
    print(f"{'Avg latency':20s} {regex_ms_total/total:>10.1f}ms {haiku_ms_total/total:>10.1f}ms {groq_ms_total/total:>10.1f}ms")
    print(f"{'Cost per 1000':20s} {'$0.00':>12s} {'~$0.10':>12s} {'$0.00':>12s}")
    print(f"{'Infra cost':20s} {'$0':>12s} {'$0':>12s} {'$0':>12s}")

    # Category breakdown
    print(f"\n{'ACCURACY BY CATEGORY':^140}")
    print(f"{'-'*80}")
    categories = {}
    for r in results:
        cat = r["expected"]
        if cat not in categories:
            categories[cat] = {"total": 0, "r": 0, "h": 0, "g": 0}
        categories[cat]["total"] += 1
        if r["r_ok"]: categories[cat]["r"] += 1
        if r["h_ok"]: categories[cat]["h"] += 1
        if r["g_ok"]: categories[cat]["g"] += 1

    print(f"{'Intent':25s} {'Tests':>5s} {'Regex':>10s} {'Haiku':>10s} {'Groq':>10s}")
    for cat in sorted(categories.keys()):
        d = categories[cat]
        print(f"{cat:25s} {d['total']:>5d} {d['r']:>5d}/{d['total']:<3d}  {d['h']:>5d}/{d['total']:<3d}  {d['g']:>5d}/{d['total']:<3d}")

    # Misses by system
    for label, key in [("REGEX", "r_ok"), ("HAIKU", "h_ok"), ("GROQ", "g_ok")]:
        misses = [r for r in results if not r[key]]
        if misses:
            print(f"\n{label} MISSES ({len(misses)}):")
            for r in misses:
                got = r[label[0].lower()]
                print(f"  {r['msg'][:45]:45s} expected={r['expected']:18s} got={got}")


if __name__ == "__main__":
    asyncio.run(run())
