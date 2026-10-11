"""
tests/sandbox/check_intents.py
==============================
Offline regex-classification check — no server, no DB, no LLM. Runs
detect_intent() on the FIRST turn of every case in tests/sandbox/cases/*.json
that declares expect_intent, using the role implied by the case phone.

Run after ANY edit to src/whatsapp/intent_detector.py — it catches a regex fix
for one intent stealing phrases from another.

    venv/Scripts/python tests/sandbox/check_intents.py [files...]

Note: the live pipeline can still route differently (pending state, LLM
fallback below the confidence threshold). This only guards the regex layer.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.whatsapp.intent_detector import detect_intent  # noqa: E402

ROLE_BY_PHONE = {
    "917845952289": "admin",
    "917358341775": "owner",
    "919444296681": "owner",
    "917680814628": "receptionist",
}


def main() -> int:
    files = sys.argv[1:] or sorted(str(p) for p in (ROOT / "tests/sandbox/cases").glob("*.json"))
    total = bad = 0
    for f in files:
        spec = json.loads(Path(f).read_text(encoding="utf-8"))
        for case in spec["cases"]:
            turn = case["turns"][0]
            exp = turn.get("expect_intent")
            if not exp or turn.get("skip_offline"):
                continue
            role = ROLE_BY_PHONE.get(case.get("phone", "917845952289"))
            if role is None:
                continue  # blocked phones never reach the detector
            got = detect_intent(turn["msg"], role).intent
            total += 1
            ok = got in exp if isinstance(exp, list) else got == exp
            if not ok:
                bad += 1
                print(f"MISMATCH {Path(f).stem}:{case['id']}  {turn['msg']!r}  got={got} want={exp}")
    print(f"{total - bad}/{total} first-turn intents match")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
