"""
Benchmark: Regex-first vs Pure LLM (Haiku) intent detection.
Tests every major intent with multiple phrasings, measures accuracy + latency.

Usage:
  python tests/benchmark_intent.py
"""
import sys, os, time, asyncio, json
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from src.whatsapp.intent_detector import detect_intent
from src.llm_gateway.claude_client import get_claude_client

# ── Test cases: (message, expected_intent, context) ─────────────────────────
# Multiple phrasings per intent, including tricky/natural language ones
TEST_CASES = [
    # === PAYMENT_LOG ===
    ("Raj paid 15000", "PAYMENT_LOG", "direct"),
    ("received 8k from room 203", "PAYMENT_LOG", "shorthand"),
    ("Krishnan paid rent 23500 upi", "PAYMENT_LOG", "with mode"),
    ("collect rent from Anuron", "PAYMENT_LOG", "collect variant"),
    ("15000 from room 105", "PAYMENT_LOG", "amount first"),
    ("Manideep ne 14000 diya", "PAYMENT_LOG", "hinglish"),

    # === QUERY_DUES ===
    ("who hasn't paid", "QUERY_DUES", "natural"),
    ("pending list", "QUERY_DUES", "short"),
    ("outstanding balances", "QUERY_DUES", "formal"),
    ("defaulters", "QUERY_DUES", "single word"),
    ("kitne logo ne rent nahi diya", "QUERY_DUES", "hindi"),

    # === QUERY_TENANT ===
    ("Raj balance", "QUERY_TENANT", "name + balance"),
    ("room 203 details", "QUERY_TENANT", "room query"),
    ("what is rent for chinmay", "QUERY_TENANT", "natural question"),
    ("show me details of room 102", "QUERY_TENANT", "verbose"),
    ("Anuron ka balance kya hai", "QUERY_TENANT", "hinglish"),

    # === ADD_TENANT ===
    ("add tenant Raju room 305", "ADD_TENANT", "direct"),
    ("new tenant check in", "ADD_TENANT", "natural"),
    ("admit Priya to room 401", "ADD_TENANT", "admit variant"),
    ("register new tenant", "ADD_TENANT", "register"),

    # === CHECKOUT ===
    ("Raj is leaving", "CHECKOUT", "natural"),
    ("checkout room 203", "CHECKOUT", "direct"),
    ("Manideep leaving today", "CHECKOUT", "with today"),
    ("ja raha hai room 305", "CHECKOUT", "hindi"),

    # === SCHEDULE_CHECKOUT ===
    ("Raj leaving on 15th april", "SCHEDULE_CHECKOUT", "with date"),
    ("Kishan vacating next month", "SCHEDULE_CHECKOUT", "next month"),

    # === ADD_EXPENSE ===
    ("log expense", "ADD_EXPENSE", "direct"),
    ("add expense electricity 5000", "ADD_EXPENSE", "with details"),
    ("paid plumber 3000 for bathroom fix", "ADD_EXPENSE", "natural"),
    ("salary payment 15000 to Lokesh", "ADD_EXPENSE", "salary"),

    # === REPORT ===
    ("monthly report", "REPORT", "direct"),
    ("how much collected this month", "REPORT", "natural"),
    ("P&L for march", "REPORT", "specific"),
    ("collection summary", "REPORT", "summary"),

    # === QUERY_VACANT_ROOMS ===
    ("vacant rooms", "QUERY_VACANT_ROOMS", "direct"),
    ("any empty beds", "QUERY_VACANT_ROOMS", "natural"),
    ("available rooms for female", "QUERY_VACANT_ROOMS", "filtered"),

    # === QUERY_OCCUPANCY ===
    ("occupancy", "QUERY_OCCUPANCY", "single word"),
    ("how many tenants", "QUERY_OCCUPANCY", "natural"),
    ("how full are we", "QUERY_OCCUPANCY", "conversational"),

    # === ADD_CONTACT ===
    ("add contact", "ADD_CONTACT", "bare"),
    ("add building electrician contact", "ADD_CONTACT", "with category"),
    ("save plumber Raju 9876543210", "ADD_CONTACT", "full details"),
    ("add Vinay electrician contact 7026668797", "ADD_CONTACT", "full"),

    # === QUERY_CONTACTS ===
    ("plumber number", "QUERY_CONTACTS", "direct"),
    ("show electrician contacts", "QUERY_CONTACTS", "show variant"),
    ("give me Shiva number", "QUERY_CONTACTS", "name specific"),
    ("send me electrician vinays contact", "QUERY_CONTACTS", "name + category"),
    ("who is our plumber", "QUERY_CONTACTS", "who is"),

    # === UPDATE_CONTACT ===
    ("update contact Shiva", "UPDATE_CONTACT", "direct"),
    ("change Balu number", "UPDATE_CONTACT", "change number"),
    ("edit plumber notes", "UPDATE_CONTACT", "edit notes"),

    # === COMPLAINT_REGISTER ===
    ("no water in room 305", "COMPLAINT_REGISTER", "direct"),
    ("wifi not working", "COMPLAINT_REGISTER", "common issue"),
    ("fan broken in 203", "COMPLAINT_REGISTER", "broken item"),
    ("AC leaking room 401", "COMPLAINT_REGISTER", "specific"),

    # === LOG_VACATION ===
    ("Raj on vacation from 10th to 20th", "LOG_VACATION", "with dates"),
    ("Manideep going home for 5 days", "LOG_VACATION", "natural"),

    # === VOID_PAYMENT ===
    ("void payment for Raj", "VOID_PAYMENT", "direct"),
    ("cancel last payment", "VOID_PAYMENT", "cancel variant"),

    # === HELP ===
    ("help", "HELP", "single word"),
    ("hi", "HELP", "greeting"),
    ("hello", "HELP", "greeting"),
    ("menu", "HELP", "menu"),

    # === TRICKY / AMBIGUOUS ===
    ("Raj 31st March", "AMBIGUOUS", "could be checkin or checkout"),
    ("how is april looking", "REPORT", "vague report"),
    ("what about room 203", "QUERY_TENANT", "vague room query"),
    ("cancel", "UNKNOWN", "bare cancel"),
    ("thanks", "UNKNOWN", "thanks"),
    ("ok", "UNKNOWN", "acknowledgement"),

    # === ACTIVITY_LOG ===
    ("log activity received 20 chairs", "ACTIVITY_LOG", "direct"),
    ("cctv not working noted", "ACTIVITY_LOG", "maintenance note"),

    # === RENT_CHANGE ===
    ("increase rent for Raj to 15000", "RENT_CHANGE", "direct"),
    ("change rent for room 305", "RENT_CHANGE", "room based"),

    # === GET_WIFI_PASSWORD ===
    ("wifi password", "GET_WIFI_PASSWORD", "direct"),
    ("what is the wifi", "GET_WIFI_PASSWORD", "natural"),

    # === RULES ===
    ("pg rules", "RULES", "direct"),
    ("what are the rules", "RULES", "natural"),
]


async def run_benchmark():
    ai = get_claude_client()

    results = []
    regex_correct = 0
    haiku_correct = 0
    regex_total_ms = 0
    haiku_total_ms = 0
    total = len(TEST_CASES)

    print(f"Running {total} test cases against REGEX and HAIKU...")
    print(f"{'='*120}")
    print(f"{'Message':50s} {'Expected':20s} {'Regex':20s} {'ms':>5s} {'Haiku':20s} {'ms':>6s} {'Winner':>8s}")
    print(f"{'-'*120}")

    for msg, expected, context in TEST_CASES:
        # === REGEX ===
        t0 = time.time()
        regex_result = detect_intent(msg, "admin")
        regex_ms = (time.time() - t0) * 1000
        regex_intent = regex_result.intent
        regex_total_ms += regex_ms

        # === HAIKU ===
        t0 = time.time()
        try:
            haiku_result = await ai.detect_whatsapp_intent(msg, "admin")
            haiku_intent = str(haiku_result.get("intent", "UNKNOWN")).upper()
        except Exception as e:
            haiku_intent = f"ERROR: {e}"
        haiku_ms = (time.time() - t0) * 1000
        haiku_total_ms += haiku_ms

        # === Score ===
        # Flexible matching: AMBIGUOUS expected can match related intents
        regex_ok = regex_intent == expected or (expected == "AMBIGUOUS" and regex_intent != "UNKNOWN")
        haiku_ok = haiku_intent == expected or (expected == "AMBIGUOUS" and haiku_intent != "UNKNOWN")
        # UNKNOWN expected: anything not a real intent is fine
        if expected == "UNKNOWN":
            regex_ok = regex_intent in ("UNKNOWN", "HELP", "AI_CONVERSE")
            haiku_ok = haiku_intent in ("UNKNOWN", "HELP", "GENERAL")

        if regex_ok: regex_correct += 1
        if haiku_ok: haiku_correct += 1

        winner = ""
        if regex_ok and not haiku_ok: winner = "REGEX"
        elif haiku_ok and not regex_ok: winner = "HAIKU"
        elif regex_ok and haiku_ok: winner = "BOTH"
        else: winner = "NONE"

        r_mark = "OK" if regex_ok else "MISS"
        h_mark = "OK" if haiku_ok else "MISS"

        results.append({
            "msg": msg, "expected": expected, "context": context,
            "regex_intent": regex_intent, "regex_ok": regex_ok, "regex_ms": regex_ms,
            "haiku_intent": haiku_intent, "haiku_ok": haiku_ok, "haiku_ms": haiku_ms,
            "winner": winner,
        })

        # Only show mismatches or interesting cases
        flag = "  " if winner == "BOTH" else ">>"
        print(f"{flag} {msg[:48]:48s} {expected:20s} {regex_intent:16s} {r_mark:>4s} {regex_ms:4.0f}  {haiku_intent:16s} {h_mark:>4s} {haiku_ms:5.0f}  {winner:>6s}")

    # === Summary ===
    print(f"\n{'='*120}")
    print(f"RESULTS SUMMARY")
    print(f"{'='*120}")
    print(f"Total test cases:  {total}")
    print(f"")
    print(f"{'':20s} {'REGEX':>12s} {'HAIKU':>12s}")
    print(f"{'-'*45}")
    print(f"{'Correct':20s} {regex_correct:>12d} {haiku_correct:>12d}")
    print(f"{'Accuracy':20s} {regex_correct/total*100:>11.1f}% {haiku_correct/total*100:>11.1f}%")
    print(f"{'Total latency':20s} {regex_total_ms:>10.0f}ms {haiku_total_ms:>10.0f}ms")
    print(f"{'Avg latency':20s} {regex_total_ms/total:>10.1f}ms {haiku_total_ms/total:>10.1f}ms")
    print(f"{'Cost per call':20s} {'$0.000':>12s} {'~$0.0001':>12s}")
    print(f"{'Cost per 1000':20s} {'$0.00':>12s} {'~$0.10':>12s}")

    # Show failures
    regex_misses = [r for r in results if not r["regex_ok"]]
    haiku_misses = [r for r in results if not r["haiku_ok"]]

    if regex_misses:
        print(f"\nREGEX MISSES ({len(regex_misses)}):")
        for r in regex_misses:
            print(f"  {r['msg'][:45]:45s} expected={r['expected']:20s} got={r['regex_intent']}")

    if haiku_misses:
        print(f"\nHAIKU MISSES ({len(haiku_misses)}):")
        for r in haiku_misses:
            print(f"  {r['msg'][:45]:45s} expected={r['expected']:20s} got={r['haiku_intent']}")

    # Where they disagree
    disagree = [r for r in results if r["regex_intent"] != r["haiku_intent"]]
    print(f"\nDISAGREEMENTS ({len(disagree)}):")
    for r in disagree:
        print(f"  {r['msg'][:45]:45s} regex={r['regex_intent']:16s} haiku={r['haiku_intent']:16s} expected={r['expected']}")


if __name__ == "__main__":
    asyncio.run(run_benchmark())
