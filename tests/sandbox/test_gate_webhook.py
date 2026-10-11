"""
tests/sandbox/test_gate_webhook.py
==================================
Gate area — exercises the REAL Meta webhook (POST /webhook/whatsapp) in-process
against the sandbox DB, with signed synthetic payloads for text / image /
document / audio messages.

    DATABASE_URL=postgresql+asyncpg://postgres@localhost:55432/pgtest \
        venv/Scripts/python tests/sandbox/test_gate_webhook.py

Safety: refuses a non-local DATABASE_URL; installs the sandbox_server guards
(Meta / Google / Supabase calls are faked + recorded to outbound.jsonl).
WHATSAPP_APP_SECRET is read from .env to sign payloads and never printed.

Stubbed (Meta CDN is unreachable in the sandbox): media download returns a
local file, Whisper transcription returns a scripted value, Claude vision
returns None (forces the caption / menu paths).

Checks:
  - blocked numbers (unknown + a real tenant phone) get NO send for any type,
    including "approve 5" / "reject 5", statement uploads and voice notes
  - staff get replies; voice-failure notice only to staff
  - bank statement CSV upload works for admin/owner, refused for receptionist
  - receipt / expense image paths end in a Kozzy-app pointer, never a
    WhatsApp finance command
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

SANDBOX_DB = "postgresql+asyncpg://postgres@localhost:55432/pgtest"
os.environ.setdefault("DATABASE_URL", SANDBOX_DB)
if "localhost" not in os.environ["DATABASE_URL"] and "127.0.0.1" not in os.environ["DATABASE_URL"]:
    sys.exit("REFUSING: DATABASE_URL is not local")
os.environ["TEST_MODE"] = "1"
os.environ["SANDBOX"] = "1"
os.chdir(ROOT)

from sandbox_server import install_guards, OUTBOUND_LOG  # noqa: E402

install_guards()

import httpx  # noqa: E402

import main  # noqa: E402  (load_dotenv here — does not override DATABASE_URL)
from src.database import db_manager  # noqa: E402
from src.whatsapp import webhook_handler as wh  # noqa: E402
from src.whatsapp import media_handler  # noqa: E402
from src.whatsapp.handlers import receipt_handler  # noqa: E402

ADMIN, OWNER_L, OWNER_P, RECEP = "917845952289", "917358341775", "919444296681", "917680814628"
UNKNOWN, TENANT = "919999900001", "919000000000"   # 9000000000 = Pratik Rastogi (sandbox tenant)
STAFF = (ADMIN, OWNER_L, OWNER_P, RECEP)
BLOCKED = (UNKNOWN, TENANT)

SENT: list[tuple[str, str]] = []          # (to, text) captured from webhook sends
TRANSCRIBE = {"value": None}
CSV_PATH = HERE / "results" / "gate_bank_statement.csv"
FAKE_IMG = "sandbox/gate_test.jpg"

_orig_send = wh._send_whatsapp
_orig_send_inter = wh._send_whatsapp_interactive


async def _cap_send(to_number, message, **kw):
    SENT.append((to_number, message))
    return await _orig_send(to_number, message, **kw)   # → guarded httpx → outbound.jsonl


async def _cap_send_inter(to_number, payload):
    SENT.append((to_number, json.dumps(payload)))
    return await _orig_send_inter(to_number, payload)


async def _fake_download(media_id, media_mime):
    return str(CSV_PATH)


async def _fake_fetch_bytes(media_id):
    return b"OggS-fake-voice"


async def _fake_transcribe(audio_bytes, mime_type):
    return TRANSCRIBE["value"]


async def _fake_wa_media(media_id, mime_type, subfolder="id_proofs", filename_prefix=""):
    return f"{subfolder}/{filename_prefix or 'x'}_{media_id}.jpg"


async def _no_vision(media_id, media_mime):
    return None


wh._send_whatsapp = _cap_send
wh._send_whatsapp_interactive = _cap_send_inter
wh._download_media = _fake_download
wh._fetch_media_bytes = _fake_fetch_bytes
wh._transcribe_audio_bytes = _fake_transcribe
media_handler.download_whatsapp_media = _fake_wa_media
receipt_handler._claude_read_image = _no_vision


def _payload(phone: str, mtype: str, *, text: str = "", caption: str = "",
             mime: str = "", filename: str = "") -> dict:
    mid = f"wamid.GATE{time.time_ns()}"
    msg: dict = {"from": phone, "id": mid, "timestamp": str(int(time.time())), "type": mtype}
    if mtype == "text":
        msg["text"] = {"body": text}
    else:
        obj = {"id": f"media{time.time_ns()}", "mime_type": mime}
        if caption:
            obj["caption"] = caption
        if filename:
            obj["filename"] = filename
        msg[mtype] = obj
    return {"object": "whatsapp_business_account", "entry": [{"id": "x", "changes": [{
        "field": "messages", "value": {
            "messaging_product": "whatsapp",
            "metadata": {"display_phone_number": "910000000000", "phone_number_id": "sandbox-pnid"},
            "contacts": [{"wa_id": phone, "profile": {"name": "t"}}],
            "messages": [msg]}}]}]}


def _outbound_to(phone: str) -> int:
    if not OUTBOUND_LOG.exists():
        return 0
    n = 0
    with OUTBOUND_LOG.open(encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            body = e.get("body")
            if "graph.facebook.com" in e.get("url", "") and isinstance(body, dict) \
                    and str(body.get("to", "")).endswith(phone[-10:]):
                n += 1
    return n


async def _db(sql: str):
    import asyncpg
    conn = await asyncpg.connect("postgresql://postgres@localhost:55432/pgtest")
    try:
        return await conn.fetchval(sql)
    finally:
        await conn.close()


RESULTS: list[tuple[str, bool, str]] = []


def check(cid: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((cid, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'} {cid} {detail[:160]}")


async def post(client, secret: str, payload: dict) -> int:
    raw = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    r = await client.post("/webhook/whatsapp", content=raw,
                          headers={"X-Hub-Signature-256": sig, "Content-Type": "application/json"})
    return r.status_code


async def send(client, secret, phone, mtype="text", **kw) -> list[str]:
    before = len(SENT)
    status = await post(client, secret, _payload(phone, mtype, **kw))
    if status != 200:
        return [f"<HTTP {status}>"]
    return [t for (to, t) in SENT[before:] if to.endswith(phone[-10:])]


async def clear_pending(client, phone):
    await client.post("/api/test/clear-pending", json={"phone": phone})


async def main_async() -> int:
    secret = os.getenv("WHATSAPP_APP_SECRET", "")
    if not secret or secret == "PASTE_YOUR_META_APP_SECRET_HERE":
        print("WHATSAPP_APP_SECRET not set in .env — cannot sign payloads")
        return 2
    await db_manager.init_db(os.environ["DATABASE_URL"])
    CSV_PATH.parent.mkdir(exist_ok=True)
    CSV_PATH.write_text(
        "Transaction Date,Description,Reference,Withdrawals,Deposits,Balance\n"
        "02/09/2026,UPI/GATE-TEST/PRATIK RASTOGI/RENT,UTR90001,,14000,514000\n"
        "03/09/2026,BESCOM ELECTRICITY GATE-TEST,UTR90002,8200,,505800\n"
        "04/09/2026,NEFT GATE-TEST VIKRAM NAGAR,UTR90003,,12500,518300\n",
        encoding="utf-8")

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://sandbox") as c:
        # 0. signature enforcement
        bad = await c.post("/webhook/whatsapp", content=b"{}", headers={"X-Hub-Signature-256": "sha256=00"})
        check("GW-000 unsigned payload rejected", bad.status_code == 403, f"HTTP {bad.status_code}")

        # 1. Blocked numbers: silence for every message type
        for ph in BLOCKED:
            await clear_pending(c, ph)
            ob0 = _outbound_to(ph)
            replies = []
            for t in ("hi", "help", "approve 5", "reject 5", "Approve 12", "what is my balance",
                      "Raj paid 5000 cash", "who owes", "occupancy"):
                replies += await send(c, secret, ph, text=t)
            replies += await send(c, secret, ph, "image", caption="electricity 5000", mime="image/jpeg")
            replies += await send(c, secret, ph, "image", caption="", mime="image/jpeg")
            replies += await send(c, secret, ph, "document", caption="statement", mime="text/csv",
                                  filename="stmt.csv")
            replies += await send(c, secret, ph, "document", mime="application/pdf", filename="aadhaar.pdf")
            TRANSCRIBE["value"] = None
            replies += await send(c, secret, ph, "audio", mime="audio/ogg; codecs=opus")
            TRANSCRIBE["value"] = "what is my balance"
            replies += await send(c, secret, ph, "audio", mime="audio/ogg; codecs=opus")
            check(f"GW-1xx blocked {ph[-4:]} silent (15 msgs: text/image/doc/audio)",
                  not replies, f"replies={replies[:2]}")
            check(f"GW-1xx blocked {ph[-4:]} no outbound recorded",
                  _outbound_to(ph) == ob0, f"outbound delta={_outbound_to(ph) - ob0}")
            logged = await _db(
                f"select count(*) from whatsapp_log where from_number like '%{ph[-10:]}' "
                f"and created_at > now() - interval '5 minutes'")
            check(f"GW-1xx blocked {ph[-4:]} inbound still logged (24h-window record)",
                  (logged or 0) >= 10, f"logged={logged}")

        # 2. Staff text: replies, approve/reject no longer a stub path
        for ph in STAFF:
            await clear_pending(c, ph)
            r = await send(c, secret, ph, text="occupancy")
            check(f"GW-200 staff {ph[-4:]} gets reply", bool(r) and "bed" in r[0].lower(), r[0][:80] if r else "none")
            r = await send(c, secret, ph, text="approve 5")
            check(f"GW-201 staff {ph[-4:]} 'approve 5' not the dead stub",
                  not any(x.startswith(("Approved:", "Not found: #", "Rejected:")) for x in r), (r or ["none"])[0][:80])
            await clear_pending(c, ph)

        # 3. Voice: failure notice is staff-only; success flows into pipeline
        TRANSCRIBE["value"] = None
        r = await send(c, secret, ADMIN, "audio", mime="audio/ogg; codecs=opus")
        check("GW-300 staff voice failure gets notice", any("voice note" in x for x in r), (r or ["none"])[0][:80])
        TRANSCRIBE["value"] = "occupancy"
        r = await send(c, secret, RECEP, "audio", mime="audio/ogg")
        check("GW-301 staff voice transcribed → answered", any("bed" in x.lower() for x in r), (r or ["none"])[0][:80])
        TRANSCRIBE["value"] = "Raj paid 5000 cash"
        r = await send(c, secret, OWNER_L, "audio", mime="audio/ogg")
        check("GW-302 staff voice finance → Kozzy app block", any("Kozzy app" in x for x in r), (r or ["none"])[0][:80])

        # 4. Bank statement upload
        up0 = await _db("select count(*) from bank_uploads")
        ob0 = _outbound_to(ADMIN)
        r = await send(c, secret, ADMIN, "document", caption="", mime="text/csv", filename="sep.csv")
        ok = any("Bank Statement Uploaded" in x and "Transactions parsed: 3" in x for x in r)
        check("GW-400 admin CSV upload parsed (3 txns)", ok, (r or ["none"])[0][:200])
        check("GW-401 upload reply has no blocked command",
              not any("bank report" in x.lower() or "match deposits" in x.lower() for x in r), "")
        check("GW-402 bank_uploads row written", (await _db("select count(*) from bank_uploads")) == up0 + 1, "")
        n_txn = await _db("select count(*) from bank_transactions where description like '%GATE-TEST%'")
        check("GW-403 bank_transactions present (dedup by hash on repeat)", n_txn == 3, f"rows={n_txn}")
        check("GW-404 reply captured in outbound.jsonl, not sent", _outbound_to(ADMIN) > ob0, "")
        r = await send(c, secret, OWNER_P, "document", mime="application/octet-stream", filename="sep.csv")
        check("GW-405 owner CSV re-upload → duplicates skipped",
              any("Duplicates skipped:  3" in x for x in r), (r or ["none"])[0][:200])
        r = await send(c, secret, RECEP, "document", mime="text/csv", filename="sep.csv")
        check("GW-406 receptionist CSV → admin-only notice",
              any("only available for admins" in x for x in r), (r or ["none"])[0][:80])

        # 5. Media flows (staff) — every path ends in the archive + Kozzy app pointer
        FIN_CMDS = ("electricity 5000", "[category] [amount]", "[name] [amount]",
                    "type the tenant name", "or type a tenant name", "log the payment first")
        await clear_pending(c, ADMIN)
        r = await send(c, secret, ADMIN, "image", caption="electricity bill 5000", mime="image/jpeg")
        check("GW-500 expense image (caption) → saved + Kozzy app",
              any("Expense bill saved" in x and "Kozzy app" in x for x in r), (r or ["none"])[0][:120])
        check("GW-501 expense image reply has no blocked command",
              not any(k in x.lower() for x in r for k in FIN_CMDS), "")
        await clear_pending(c, OWNER_L)
        r = await send(c, secret, OWNER_L, "image", caption="EB bill", mime="image/jpeg")
        check("GW-502 'EB bill' image → expense saved",
              any("Expense bill saved" in x for x in r), (r or ["none"])[0][:120])
        await clear_pending(c, RECEP)
        r = await send(c, secret, RECEP, "image", caption="Pratik Rastogi paid 8000 upi", mime="image/jpeg")
        check("GW-503 receipt image w/ tenant caption → confirm prompt (no finance block)",
              any("Pratik Rastogi" in x for x in r) and not any("not available via WhatsApp" in x for x in r),
              (r or ["none"])[0][:120])
        r = await send(c, secret, RECEP, text="yes")
        check("GW-504 confirm → attached or Kozzy-app pointer (no WhatsApp payment cmd)",
              any(("Receipt saved" in x) or ("Kozzy app" in x) for x in r)
              and not any(k in x.lower() for x in r for k in FIN_CMDS), (r or ["none"])[0][:160])
        await send(c, secret, RECEP, "image", caption="Vikram Nagar paid 12500", mime="image/jpeg")
        r = await send(c, secret, RECEP, text="2")
        check("GW-504b confirm prompt accepts digit '2' = No",
              any("Cancelled" in x for x in r), (r or ["none"])[0][:120])
        await clear_pending(c, RECEP)
        await clear_pending(c, OWNER_P)
        r = await send(c, secret, OWNER_P, "image", caption="", mime="image/jpeg")
        first = (r or [""])[0]
        if "What is this?" in first:
            r2 = await send(c, secret, OWNER_P, text="2")
            check("GW-505 uncaptioned image → menu → '2' expense saved + Kozzy app",
                  any("Expense bill saved" in x and "Kozzy app" in x for x in r2), (r2 or ["none"])[0][:120])
            await send(c, secret, OWNER_P, "image", caption="", mime="image/jpeg")
            r3 = await send(c, secret, OWNER_P, text="3")
            check("GW-506 menu → '3' ID proof saved, no 'type the tenant name'",
                  any("ID proof saved" in x for x in r3) and not any("type the tenant name" in x.lower() for x in r3),
                  (r3 or ["none"])[0][:120])
        else:
            # recent unattached payments in the window → receipt selection instead
            check("GW-505 uncaptioned image → receipt selection without free-text name prompt",
                  "or type a tenant name" not in first and bool(first), first[:120])
        await clear_pending(c, OWNER_P)
        r = await send(c, secret, ADMIN, "image", caption="receipt Zzqxw Nobody", mime="image/jpeg")
        check("GW-507 receipt image, no tenant / no payment → archive + Kozzy app",
              any(("Kozzy app" in x) or ("Which payment" in x) or ("Is this receipt" in x) for x in r)
              and not any(k in x.lower() for x in r for k in FIN_CMDS), (r or ["none"])[0][:160])
        await clear_pending(c, ADMIN)

        # 6. HELP for staff advertises no blocked finance command
        from src.whatsapp.handlers.account_handler import FINANCIAL_INTENTS
        r = await send(c, secret, OWNER_L, text="help")
        joined = " ".join(r)
        fin_rows = [i for i in FINANCIAL_INTENTS if f'"id": "{i}"' in joined]
        check("GW-600 owner help menu (interactive) has no finance rows",
              bool(r) and not fin_rows, f"finance rows={fin_rows}")
        await clear_pending(c, RECEP)
        r = await send(c, secret, RECEP, text="help")
        joined = " ".join(r)
        check("GW-601 receptionist help text → Kozzy app, no finance commands",
              "Kozzy app" in joined and not any(k in joined for k in ("Raj paid", "who owes", "void payment",
                                                                       "Raj balance", "log EB bill")),
              joined[:120])

    passed = sum(ok for _, ok, _ in RESULTS)
    print(f"[gate-webhook] {passed}/{len(RESULTS)} passed")
    out = HERE / "results" / f"gate_webhook_{time.strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps([{"id": i, "pass": ok, "detail": d} for i, ok, d in RESULTS], indent=2),
                   encoding="utf-8")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main_async()))
