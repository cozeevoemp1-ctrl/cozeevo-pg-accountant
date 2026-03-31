"""Test all correction/confirmation scenarios end-to-end."""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import httpx
import asyncio
import os

API = "http://127.0.0.1:8000/api/whatsapp/process"
CLEAR = "http://127.0.0.1:8000/api/test/clear-pending"
PHONE = "917993273966"


async def send(client, msg):
    r = await client.post(API, json={"phone": PHONE, "message": msg, "message_id": f"t-{msg[:15]}"}, timeout=15)
    return r.json()


async def clear(client):
    await client.post(CLEAR, json={"phone": PHONE}, timeout=5)


async def scenario(client, name, turns):
    await clear(client)
    print(f"\n{'='*70}")
    print(f"SCENARIO: {name}")
    print("=" * 70)
    ok = True
    for i, msg in enumerate(turns):
        r = await send(client, msg)
        reply = r.get("reply", "")
        intent = r.get("intent", "")
        short = reply[:250].replace("\n", " | ")
        print(f"  [{i+1}] >> {msg}")
        print(f"      << [{intent}] {short}")
        if "went wrong" in reply.lower():
            print("      *** BROKEN ***")
            ok = False
    return ok


async def main():
    async with httpx.AsyncClient() as c:
        results = []

        # 1. Correct amount mid-flow
        results.append(("correct_amount", await scenario(c, "Correct amount: 16000 -> 15000", [
            "Aahil paid 16000 cash", "no 15000", "yes",
        ])))

        # 2. Correct mode cash -> upi
        results.append(("mode_cash_upi", await scenario(c, "Correct mode: cash -> upi", [
            "Aahil paid 16000 cash", "no it was upi", "yes",
        ])))

        # 3. Correct mode upi -> cash
        results.append(("mode_upi_cash", await scenario(c, "Correct mode: upi -> cash", [
            "Aahil paid 16000 upi", "actually cash", "yes",
        ])))

        # 4. Correct mode -> gpay
        results.append(("mode_gpay", await scenario(c, "Correct mode: cash -> gpay", [
            "Aahil paid 16000 cash", "no gpay", "yes",
        ])))

        # 5. Correct mode -> phonepe
        results.append(("mode_phonepe", await scenario(c, "Correct mode: cash -> phonepe", [
            "Aahil paid 16000 cash", "no phonepe", "yes",
        ])))

        # 6. Cancel with 'no'
        results.append(("cancel_no", await scenario(c, "Cancel with no", [
            "Aahil paid 16000 cash", "no",
        ])))

        # 7. Cancel with 'cancel'
        results.append(("cancel_keyword", await scenario(c, "Cancel with cancel", [
            "Aahil paid 16000 cash", "cancel",
        ])))

        # 8. Cancel with 'stop'
        results.append(("cancel_stop", await scenario(c, "Cancel with stop", [
            "Aahil paid 16000 cash", "stop",
        ])))

        # 9. Correct amount with commas
        results.append(("amount_comma", await scenario(c, "Correct amount: 16000 -> 15,500", [
            "Aahil paid 16000 cash", "no 15,500", "yes",
        ])))

        # 10. Correct both amount + mode
        results.append(("both_amt_mode", await scenario(c, "Correct both: 16000->14000 + cash->upi", [
            "Aahil paid 16000 cash", "no 14000 upi", "yes",
        ])))

        # 11. Wrong person - cancel and redo
        results.append(("wrong_person", await scenario(c, "Wrong person: cancel then redo", [
            "Aahil paid 16000 cash", "no", "Advait paid 13000 cash", "yes",
        ])))

        # 12. Disambiguation pick #2
        results.append(("disambig_pick2", await scenario(c, "Disambiguation: pick #2", [
            "Abhishek paid 12000 cash", "2", "yes",
        ])))

        # 13. Disambiguation cancel
        results.append(("disambig_cancel", await scenario(c, "Disambiguation: cancel", [
            "Abhishek paid 12000 cash", "cancel",
        ])))

        # 14. Void payment
        results.append(("void_start", await scenario(c, "Void a payment", [
            "void Aahil payment",
        ])))

        # 15. Hi mid-flow resets
        results.append(("reset_hi", await scenario(c, "Hi mid-flow resets pending", [
            "Aahil paid 16000 cash", "hi",
        ])))

        # 16. Just amount no prefix
        results.append(("amount_no_prefix", await scenario(c, "Just send 15000 mid-flow", [
            "Aahil paid 16000 cash", "15000",
        ])))

        # 17. Confirm with 'ok'
        results.append(("confirm_ok", await scenario(c, "Confirm with ok", [
            "Aahil paid 16000 cash", "ok",
        ])))

        # 18. Confirm with 'ha'
        results.append(("confirm_ha", await scenario(c, "Confirm with ha", [
            "Aahil paid 16000 cash", "ha",
        ])))

        # 19. Confirm with 'confirm'
        results.append(("confirm_keyword", await scenario(c, "Confirm with confirm", [
            "Aahil paid 16000 cash", "confirm",
        ])))

        # 20. Natural correction: wrong amount its 14000
        results.append(("natural_wrong", await scenario(c, "Natural: wrong amount its 14000", [
            "Aahil paid 16000 cash", "wrong amount, its 14000", "yes",
        ])))

        # 21. Change to upi
        results.append(("change_to_upi", await scenario(c, "Natural: change to upi", [
            "Aahil paid 16000 cash", "change to upi", "yes",
        ])))

        # 22. Month correction
        results.append(("month_feb", await scenario(c, "Month correction: for february", [
            "Aahil paid 16000 cash", "no for february", "yes",
        ])))

        # 23. Hindi confirm: haan
        results.append(("confirm_haan", await scenario(c, "Hindi: haan", [
            "Aahil paid 16000 cash", "haan",
        ])))

        # 24. Hindi confirm: theek hai
        results.append(("confirm_theek", await scenario(c, "Hindi: theek hai", [
            "Aahil paid 16000 cash", "theek hai",
        ])))

        # 25. Nonsense mid-flow
        results.append(("nonsense", await scenario(c, "Nonsense mid-flow: asdfgh", [
            "Aahil paid 16000 cash", "asdfgh",
        ])))

        # Void test payments
        from dotenv import load_dotenv
        load_dotenv()
        from sqlalchemy import text as sqtext
        from src.database.db_manager import init_engine, get_session
        init_engine(os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL"))
        async with get_session() as s:
            r = await s.execute(sqtext("UPDATE payments SET is_void=true WHERE created_at >= '2026-03-31' AND is_void=false"))
            await s.commit()
            print(f"\nVoided {r.rowcount} test payments")

        # Summary
        print(f"\n{'='*70}")
        print("SUMMARY")
        print("=" * 70)
        for name, ok in results:
            print(f"  {name:30s} {'PASS' if ok else '** FAIL **'}")
        p = sum(1 for _, ok in results if ok)
        print(f"\n  {p}/{len(results)} passed")


if __name__ == "__main__":
    asyncio.run(main())
