"""
tests/sandbox/run_cases.py
==========================
Replays WhatsApp conversations against a sandbox server (tests/sandbox/sandbox_server.py)
and checks the reply, the classified intent, the DB effect, and outbound messages.

    venv/Scripts/python tests/sandbox/run_cases.py tests/sandbox/cases/*.json \
        --port 8100 --label cold [--repeat 2] [--only A-001,A-002]

Case file format (JSON):
{
  "area": "lifecycle",
  "cases": [{
    "id": "A-001", "intent": "CHECKOUT", "desc": "checkout with date, confirm",
    "phone": "917845952289",                  # default Kiran (admin)
    "turns": [{
      "msg": "checkout room 214 on 30th",
      "expect_intent": "CHECKOUT",              # str or list of acceptable intents
      "expect_contains": ["confirm"],           # case-insensitive substrings, all required
      "expect_any": ["yes", "confirm"],         # at least one required
      "expect_regex": "Rs\\.?\\s?[0-9,]+",
      "expect_not_contains": ["finance queries"],
      "expect_silent": false,                   # true => reply must be empty/None
      "end_if_contains": ["no active tenant"]   # optional: turn passed + reply has one => skip later turns (repeat runs)
    }],
    "db_checks": [{"sql": "select status from tenancies where id=12", "expect": "exited"}],
    "stop_on_fail": true,                       # optional: stop sending turns after the first failed turn
    "expect_outbound": 0,                       # optional: exact count of blocked sends during case
    "expect_outbound_wa": 0                     # optional: count of WhatsApp (graph.facebook.com) sends only
  }]
}
Every turn also fails on generic error markers (Traceback, "Something went wrong",
HTTP 5xx). db_checks "expect" may be a literal (compared as string) or "nonzero"/"zero".

Results: tests/sandbox/results/<area>_<label>_<timestamp>.json (+ printed summary).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
OUTBOUND = HERE / "outbound.jsonl"
SANDBOX_DSN = "postgresql://postgres@localhost:55432/pgtest"
DEFAULT_PHONE = "917845952289"
ERROR_MARKERS = ("traceback", "something went wrong", "internal server error",
                 "unexpected error", "exception:")


def _outbound_count(host: str | None = None) -> int:
    """Count blocked sends; host='graph.facebook.com' counts only WhatsApp sends
    (Google Sheets token/write calls also land in outbound.jsonl)."""
    if not OUTBOUND.exists():
        return 0
    with OUTBOUND.open(encoding="utf-8") as f:
        return sum(1 for line in f if host is None or host in line)


async def _db_value(sql: str):
    import asyncpg
    conn = await asyncpg.connect(SANDBOX_DSN)
    try:
        return await conn.fetchval(sql)
    finally:
        await conn.close()


def _check_turn(turn: dict, status: int, data: dict) -> list[str]:
    errs = []
    reply = (data.get("reply") or "") if isinstance(data, dict) else ""
    low = reply.lower()
    intent = data.get("intent") if isinstance(data, dict) else None
    if status >= 500:
        errs.append(f"HTTP {status}")
    for m in ERROR_MARKERS:
        if m in low:
            errs.append(f"error marker in reply: {m!r}")
    exp_i = turn.get("expect_intent")
    if exp_i:
        ok = intent in exp_i if isinstance(exp_i, list) else intent == exp_i
        if not ok:
            errs.append(f"intent {intent!r} != expected {exp_i!r}")
    if turn.get("expect_silent"):
        if reply.strip():
            errs.append(f"expected silence, got reply: {reply[:80]!r}")
        return errs
    if not turn.get("allow_empty") and not reply.strip():
        errs.append("empty reply")
    for s in turn.get("expect_contains", []):
        if s.lower() not in low:
            errs.append(f"missing {s!r}")
    anys = turn.get("expect_any")
    if anys and not any(s.lower() in low for s in anys):
        errs.append(f"none of {anys!r}")
    rx = turn.get("expect_regex")
    if rx and not re.search(rx, reply, re.I | re.S):
        errs.append(f"regex {rx!r} not matched")
    for s in turn.get("expect_not_contains", []):
        if s.lower() in low:
            errs.append(f"must not contain {s!r}")
    return errs


async def run_case(client: httpx.AsyncClient, base: str, case: dict, run_tag: str) -> dict:
    phone = case.get("phone", DEFAULT_PHONE)
    try:
        await client.post(f"{base}/api/test/clear-pending", json={"phone": phone}, timeout=10)
    except Exception:
        pass
    out_before = _outbound_count()
    wa_before = _outbound_count("graph.facebook.com")
    turns_out, failed = [], False
    for i, turn in enumerate(case["turns"]):
        t0 = time.perf_counter()
        try:
            r = await client.post(f"{base}/api/whatsapp/process", timeout=120, json={
                "phone": phone, "message": turn["msg"],
                "message_id": f"sbx-{case['id']}-{run_tag}-t{i}-{time.time_ns()}"})
            status = r.status_code
            try:
                data = r.json()
            except ValueError:
                data = {"reply": r.text}
        except Exception as e:
            status, data = 599, {"reply": f"transport error: {e}"}
        errs = _check_turn(turn, status, data)
        failed |= bool(errs)
        turns_out.append({"msg": turn["msg"], "status": status,
                          "intent": data.get("intent") if isinstance(data, dict) else None,
                          "reply": (data.get("reply") if isinstance(data, dict) else None),
                          "ms": int((time.perf_counter() - t0) * 1000), "errors": errs})
        _end = turn.get("end_if_contains")
        _rep = ((data.get("reply") if isinstance(data, dict) else "") or "").lower()
        if not errs and _end and any(x.lower() in _rep for x in _end):
            # repeat-run branch: e.g. the tenant was already checked out on run 1 —
            # the flow legitimately ends here; db_checks still run
            break
        if errs and case.get("stop_on_fail"):
            # don't send "1"/"yes" into whatever the bot is asking now — on a shared
            # DB a blind follow-up can confirm a write on someone else's tenant
            turns_out.append({"msg": "<remaining turns skipped>", "errors": ["stopped after failed turn"]})
            break
    db_out = []
    for chk in case.get("db_checks", []):
        try:
            val = await _db_value(chk["sql"])
            exp = chk["expect"]
            ok = (val not in (None, 0, "0") if exp == "nonzero" else
                  val in (None, 0, "0") if exp == "zero" else str(val) == str(exp))
        except Exception as e:
            val, ok = f"ERR {e}", False
        failed |= not ok
        db_out.append({"sql": chk["sql"], "expect": chk["expect"], "got": str(val), "ok": ok})
    out_delta = _outbound_count() - out_before
    if "expect_outbound" in case and out_delta != case["expect_outbound"]:
        failed = True
        db_out.append({"sql": "outbound sends", "expect": case["expect_outbound"],
                       "got": out_delta, "ok": False})
    if "expect_outbound_wa" in case:
        await asyncio.sleep(1.5)  # fire-and-forget sends land after the reply
        wa_delta = _outbound_count("graph.facebook.com") - wa_before
        if wa_delta != case["expect_outbound_wa"]:
            failed = True
            db_out.append({"sql": "whatsapp sends", "expect": case["expect_outbound_wa"],
                           "got": wa_delta, "ok": False})
    return {"id": case["id"], "intent": case.get("intent"), "desc": case.get("desc", ""),
            "pass": not failed, "turns": turns_out, "db_checks": db_out,
            "outbound_sends": out_delta}


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--port", type=int, default=8100)
    ap.add_argument("--label", default="run")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--only", default="")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    base = f"http://127.0.0.1:{args.port}"
    only = {s.strip() for s in args.only.split(",") if s.strip()}
    RESULTS.mkdir(exist_ok=True)
    total_fail = 0
    async with httpx.AsyncClient() as client:
        for f in args.files:
            spec = json.loads(Path(f).read_text(encoding="utf-8"))
            area = spec.get("area", Path(f).stem)
            cases = [c for c in spec["cases"] if not only or c["id"] in only]
            for rep in range(1, args.repeat + 1):
                label = args.label if args.repeat == 1 else f"{args.label}-r{rep}"
                results = [await run_case(client, base, c, label) for c in cases]
                passed = sum(r["pass"] for r in results)
                total_fail += len(results) - passed
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                out = RESULTS / f"{area}_{label}_{stamp}.json"
                out.write_text(json.dumps({"area": area, "label": label, "port": args.port,
                                           "passed": passed, "total": len(results),
                                           "results": results}, indent=2, ensure_ascii=False),
                               encoding="utf-8")
                print(f"[{area}:{label}] {passed}/{len(results)} passed -> {out.name}")
                if not args.quiet:
                    for r in results:
                        if not r["pass"]:
                            errs = [e for t in r["turns"] for e in t["errors"]] + \
                                   [f"db {d['sql'][:50]} got {d['got']} want {d['expect']}"
                                    for d in r["db_checks"] if not d["ok"]]
                            print(f"  FAIL {r['id']} {r['intent']}: {'; '.join(errs)[:300]}")
    return 1 if total_fail else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
