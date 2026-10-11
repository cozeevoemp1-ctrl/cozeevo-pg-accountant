"""
tests/sandbox/sandbox_server.py
===============================
Run the real FastAPI app against the LOCAL sandbox Postgres with every
side-effect that could reach a real person or a real system blocked and
recorded instead.

    venv/Scripts/python tests/sandbox/sandbox_server.py [--port 8100]

Blocked (request never leaves the machine; a fake success is returned and the
request is appended to tests/sandbox/outbound.jsonl):
  - graph.facebook.com        WhatsApp sends (text, template, document, media)
  - *.googleapis.com / oauth2 Google Sheets / Drive / Gmail
  - *.supabase.co             Supabase Storage + REST (KYC, agreements)

Also blocked by default: api.groq.com, api.anthropic.com, api.openai.com (paid).
Set SANDBOX_ALLOW_LLM=1 only for a deliberate LLM-fallback run.

Refuses to start unless DATABASE_URL points at localhost, so it can never run
against production by accident.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
OUTBOUND_LOG = Path(__file__).with_name("outbound.jsonl")
SANDBOX_DB = "postgresql+asyncpg://postgres@localhost:55432/pgtest"

BLOCKED_SUFFIXES = ("graph.facebook.com", "googleapis.com", "accounts.google.com",
                    "oauth2.googleapis.com", "supabase.co", "supabase.in")
# Paid LLM APIs are blocked by default (cost). Set SANDBOX_ALLOW_LLM=1 for a run that
# deliberately exercises the Groq/Claude fallback.
if os.getenv("SANDBOX_ALLOW_LLM") != "1":
    BLOCKED_SUFFIXES += ("api.groq.com", "api.anthropic.com", "api.openai.com")
_lock = threading.Lock()


def _blocked(url: str) -> bool:
    host = (urlparse(str(url)).hostname or "").lower()
    return any(host == s or host.endswith("." + s) for s in BLOCKED_SUFFIXES)


def _record(method: str, url: str, body) -> None:
    if isinstance(body, (bytes, bytearray)):
        try:
            body = body.decode("utf-8")
        except UnicodeDecodeError:
            body = f"<{len(body)} bytes>"
    try:
        body = json.loads(body) if isinstance(body, str) and body[:1] in "{[" else body
    except ValueError:
        pass
    entry = {"ts": time.time(), "method": method, "url": str(url), "body": body}
    with _lock, OUTBOUND_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def _fake_payload(url: str) -> dict:
    host = urlparse(str(url)).hostname or ""
    if "facebook" in host:
        return {"messaging_product": "whatsapp",
                "messages": [{"id": f"wamid.SANDBOX{int(time.time()*1000)}"}],
                "id": "sandbox-media-id", "url": "https://sandbox.invalid/media"}
    return {"sandbox": True, "Key": "sandbox/blocked", "values": [], "updates": {}}


def install_guards() -> None:
    import httpx

    def _fake_httpx(request: "httpx.Request") -> "httpx.Response":
        body = request.content if request.content else None
        _record(request.method, str(request.url), body)
        return httpx.Response(200, json=_fake_payload(str(request.url)), request=request)

    _orig_send = httpx.Client.send
    _orig_asend = httpx.AsyncClient.send

    def send(self, request, *a, **kw):
        if _blocked(request.url):
            return _fake_httpx(request)
        return _orig_send(self, request, *a, **kw)

    async def asend(self, request, *a, **kw):
        if _blocked(request.url):
            return _fake_httpx(request)
        return await _orig_asend(self, request, *a, **kw)

    httpx.Client.send = send
    httpx.AsyncClient.send = asend

    try:
        import requests
        from requests.models import Response

        _orig_rsend = requests.Session.send

        def rsend(self, request, *a, **kw):
            if _blocked(request.url):
                _record(request.method, request.url, request.body)
                r = Response()
                r.status_code = 200
                r._content = json.dumps(_fake_payload(request.url)).encode()
                r.headers["Content-Type"] = "application/json"
                r.url = request.url
                r.request = request
                return r
            return _orig_rsend(self, request, *a, **kw)

        requests.Session.send = rsend
    except ImportError:
        pass


def allow_finance() -> None:
    """Opt-in (--allow-finance), sandbox only: staff FINANCIAL_INTENTS go to account_handler
    instead of the production WhatsApp finance block. For recording demo footage; the
    production gatekeeper is untouched and gate.json keeps testing the block (flag off)."""
    import src.whatsapp.gatekeeper as gk
    import src.whatsapp.chat_api as ca
    from src.whatsapp.handlers.account_handler import FINANCIAL_INTENTS, handle_account
    orig = gk.route

    async def route(intent, entities, ctx, message, session):
        if intent in FINANCIAL_INTENTS and ctx.role in ("admin", "owner", "receptionist"):
            entities.setdefault("_raw_message", message)
            return await handle_account(intent, entities, ctx, session)
        return await orig(intent, entities, ctx, message, session)

    gk.route = ca.route = route  # chat_api imported `route` by name
    print("[sandbox] finance intents ENABLED for staff (demo only)", flush=True)


def fake_sheets() -> None:
    """Opt-in (--fake-sheets), sandbox only: Google Sheets write-backs (async update_*/add_*
    in src.integrations.gsheets) report success instead of failing on the blocked network,
    so demo replies match production ("Sheet update failed" would otherwise be appended)."""
    import inspect
    import src.integrations.gsheets as gs

    async def _ok(*a, **kw):
        return {"success": True}

    n = 0
    for name, fn in list(vars(gs).items()):
        if inspect.iscoroutinefunction(fn) and name.startswith(("update_", "add_", "record_", "append_")):
            setattr(gs, name, _ok)
            n += 1
    print(f"[sandbox] {n} Sheets write-backs faked as success (demo only)", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8100)
    ap.add_argument("--allow-finance", action="store_true", help="demo only: lift the WhatsApp finance block")
    ap.add_argument("--fake-sheets", action="store_true", help="demo only: Sheets write-backs report success")
    args = ap.parse_args()

    os.environ.setdefault("DATABASE_URL", SANDBOX_DB)
    db = os.environ["DATABASE_URL"]
    if "localhost" not in db and "127.0.0.1" not in db:
        sys.exit(f"REFUSING: DATABASE_URL is not local ({urlparse(db).hostname}).")
    os.environ["TEST_MODE"] = "1"
    os.environ["SANDBOX"] = "1"

    install_guards()
    os.chdir(ROOT)
    if args.allow_finance:
        allow_finance()
    if args.fake_sheets:
        fake_sheets()
    import uvicorn
    print(f"[sandbox] DB={urlparse(db).hostname}:{urlparse(db).port} port={args.port} "
          f"outbound -> {OUTBOUND_LOG}", flush=True)
    uvicorn.run("main:app", host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
