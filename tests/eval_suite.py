"""
tests/eval_suite.py
===================
pytest integration suite for PG Accountant WhatsApp bot.

Reads multi-step conversation scenarios from tests/test_scenarios.json,
POSTs each message to the running FastAPI server, and asserts on the
response (intent, confidence, reply keywords).

Usage:
    pytest tests/eval_suite.py -v                          # all scenarios
    pytest tests/eval_suite.py -v -k "payment"            # filter by name
    pytest tests/eval_suite.py -v -k "checkin or notice"  # multiple filters
    pytest tests/eval_suite.py --flow checkout            # filter by flow tag

Prerequisites:
    - START_API.bat must be running  (FastAPI on port 8000)
    - TEST_MODE=1 in .env            (bypasses rate limiting)

Environment overrides:
    API_PORT=8000   — override default port
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from dotenv import load_dotenv

load_dotenv()

# ── Config ─────────────────────────────────────────────────────────────────────
_PORT    = int(os.getenv("API_PORT", "8000"))
API_URL  = f"http://localhost:{_PORT}/api/whatsapp/process"
SCENARIOS_FILE = Path(__file__).parent / "test_scenarios.json"

# Delay between steps in a multi-step scenario (avoids rate-limit collisions)
STEP_DELAY_SEC = 0.3


# ── Fixtures ───────────────────────────────────────────────────────────────────

def _load_scenarios() -> list[dict]:
    data = json.loads(SCENARIOS_FILE.read_text(encoding="utf-8"))
    return [s for s in data if "name" in s and "steps" in s]


def pytest_addoption(parser: Any) -> None:
    parser.addoption(
        "--flow",
        action="store",
        default=None,
        help="Only run scenarios whose 'flow' field matches this value (e.g. --flow payment)",
    )


def pytest_collection_modifyitems(config: Any, items: Any) -> None:
    flow_filter = config.getoption("--flow", default=None)
    if not flow_filter:
        return
    keep = []
    skip_marker = pytest.mark.skip(reason=f"flow != {flow_filter!r}")
    for item in items:
        if hasattr(item, "callargs") and item.callargs.get("scenario", {}).get("flow") == flow_filter:
            keep.append(item)
        elif flow_filter in item.name:
            keep.append(item)
        else:
            item.add_marker(skip_marker)


def _scenario_id(scenario: dict) -> str:
    return scenario.get("name", "unnamed").replace(" ", "_").lower()


# ── Server health check ────────────────────────────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def assert_server_running() -> None:
    """Fail fast if the API server is not reachable."""
    try:
        r = httpx.get(f"http://localhost:{_PORT}/docs", timeout=5)
        assert r.status_code < 500, f"API returned {r.status_code}"
    except httpx.ConnectError:
        pytest.fail(
            f"\n\n  ❌  FastAPI not reachable at {API_URL}\n"
            "  Run START_API.bat first, then wait for 'Uvicorn running' before running pytest.\n"
        )


# ── Parametrised test ──────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "scenario",
    _load_scenarios(),
    ids=[_scenario_id(s) for s in _load_scenarios()],
)
def test_scenario(scenario: dict) -> None:
    """
    Execute all steps in a scenario sequentially.
    Each step POSTs to the bot and asserts on the response.
    """
    with httpx.Client(timeout=20.0) as client:
        for step_idx, step in enumerate(scenario["steps"]):
            phone   = step["phone"]
            message = step["message"]
            expect  = step.get("expect", {})

            resp = client.post(
                API_URL,
                json={
                    "phone":      phone,
                    "message":    message,
                    "message_id": f"eval_{_scenario_id(scenario)}_s{step_idx}_{int(time.time())}",
                },
            )

            # ── HTTP-level assertion ───────────────────────────────────────────
            assert resp.status_code == 200, (
                f"Step {step_idx+1} HTTP {resp.status_code}: {resp.text[:300]}"
            )

            data = resp.json()
            actual_intent = data.get("intent", "ERROR")
            actual_conf   = float(data.get("confidence", 0.0))
            actual_reply  = (data.get("reply") or "").lower()

            # ── Intent assertion ──────────────────────────────────────────────
            expected_intent = expect.get("intent")
            if expected_intent:
                assert actual_intent == expected_intent, (
                    f"\nScenario : {scenario['name']!r}\n"
                    f"Step {step_idx+1} : {message!r}\n"
                    f"Expected intent : {expected_intent}\n"
                    f"Got intent      : {actual_intent}  (conf={actual_conf:.2f})\n"
                    f"Bot reply       : {data.get('reply','')[:120]!r}\n\n"
                    f"Fix hint: check intent_detector.py rule priority for {expected_intent}."
                )

            # ── Confidence assertion ───────────────────────────────────────────
            min_conf = float(expect.get("min_confidence", 0.0))
            if min_conf > 0:
                assert actual_conf >= min_conf, (
                    f"\nScenario : {scenario['name']!r}\n"
                    f"Step {step_idx+1} : {message!r}\n"
                    f"Confidence {actual_conf:.2f} < minimum {min_conf:.2f}\n"
                    f"Fix hint: tighten the {expected_intent} regex so it only fires on high-signal phrases."
                )

            # ── Reply keyword assertions ──────────────────────────────────────
            keywords = [k.lower() for k in expect.get("reply_contains", [])]
            if keywords:
                found = [k for k in keywords if k in actual_reply]
                # OR logic: at least ONE keyword must appear
                assert found, (
                    f"\nScenario : {scenario['name']!r}\n"
                    f"Step {step_idx+1} : {message!r}\n"
                    f"Expected reply to contain one of: {keywords}\n"
                    f"Bot reply: {data.get('reply','')[:200]!r}\n\n"
                    f"Fix hint: check handler for {actual_intent} — confirm it includes expected keywords."
                )

            if step_idx < len(scenario["steps"]) - 1:
                time.sleep(STEP_DELAY_SEC)


# ── Property logic unit tests (no server needed) ───────────────────────────────

class TestPropertyLogic:
    """
    Fast unit tests for services/property_logic.py.
    These run without a server — just import and assert.
    """

    def test_checkin_prorate_mid_month(self) -> None:
        from decimal import Decimal
        from datetime import date
        from services.property_logic import calc_checkin_prorate
        # March 15 in a 31-day month: 17 days remaining
        result = calc_checkin_prorate(Decimal("9000"), date(2026, 3, 15))
        assert result == int(9000 * 17 / 31)

    def test_checkin_prorate_first_day(self) -> None:
        from decimal import Decimal
        from datetime import date
        from services.property_logic import calc_checkin_prorate
        # Check-in on day 1 = full month
        result = calc_checkin_prorate(Decimal("9000"), date(2026, 3, 1))
        assert result == 9000

    def test_checkout_prorate(self) -> None:
        from decimal import Decimal
        from datetime import date
        from services.property_logic import calc_checkout_prorate
        # Checkout on April 20 (30-day month): 20 days stayed
        result = calc_checkout_prorate(Decimal("9000"), date(2026, 4, 20))
        assert result == int(9000 * 20 / 30)

    def test_notice_on_time_last_day_eom(self) -> None:
        from datetime import date
        from services.property_logic import calc_notice_last_day
        # Notice on March 3 (before 5th) → last day = March 31
        last = calc_notice_last_day(date(2026, 3, 3))
        assert last == date(2026, 3, 31)

    def test_notice_late_last_day_next_month(self) -> None:
        from datetime import date
        from services.property_logic import calc_notice_last_day
        # Notice on March 10 (after 5th) → last day = April 30
        last = calc_notice_last_day(date(2026, 3, 10))
        assert last == date(2026, 4, 30)

    def test_notice_december_rollover(self) -> None:
        from datetime import date
        from services.property_logic import calc_notice_last_day
        # Late notice in December → January 31 of next year
        last = calc_notice_last_day(date(2026, 12, 15))
        assert last == date(2027, 1, 31)

    def test_is_deposit_eligible_on_time(self) -> None:
        from datetime import date
        from services.property_logic import is_deposit_eligible
        assert is_deposit_eligible(date(2026, 3, 5)) is True   # exactly on the 5th

    def test_is_deposit_eligible_late(self) -> None:
        from datetime import date
        from services.property_logic import is_deposit_eligible
        assert is_deposit_eligible(date(2026, 3, 6)) is False   # one day late

    def test_payment_status_paid(self) -> None:
        from decimal import Decimal
        from services.property_logic import calc_payment_status
        status, effective, remaining, overpay = calc_payment_status(
            Decimal("9000"), Decimal("9000"), Decimal("0")
        )
        assert status == "paid"
        assert remaining == Decimal("0")
        assert overpay == Decimal("0")

    def test_payment_status_partial(self) -> None:
        from decimal import Decimal
        from services.property_logic import calc_payment_status
        status, _, remaining, _ = calc_payment_status(
            Decimal("5000"), Decimal("9000"), Decimal("0")
        )
        assert status == "partial"
        assert remaining == Decimal("4000")

    def test_payment_status_with_discount(self) -> None:
        from decimal import Decimal
        from services.property_logic import calc_payment_status
        # Rs.500 discount → effective = 8500; paid 8500 → should be paid
        status, effective, remaining, _ = calc_payment_status(
            Decimal("8500"), Decimal("9000"), Decimal("-500")
        )
        assert status == "paid"
        assert effective == Decimal("8500")
        assert remaining == Decimal("0")

    def test_settlement_positive_refund(self) -> None:
        from decimal import Decimal
        from services.property_logic import calc_settlement
        net = calc_settlement(
            deposit=Decimal("20000"),
            outstanding_rent=Decimal("5000"),
            damages=Decimal("1000"),
        )
        assert net == Decimal("14000")

    def test_settlement_tenant_owes(self) -> None:
        from decimal import Decimal
        from services.property_logic import calc_settlement
        net = calc_settlement(
            deposit=Decimal("10000"),
            outstanding_rent=Decimal("15000"),
        )
        assert net == Decimal("-5000")


# ── Phone normalisation unit tests ─────────────────────────────────────────────

class TestPhoneNormalisation:
    """
    Fast unit tests for role_service._normalize().
    These run without a DB or server.
    """

    def _norm(self, phone: str) -> str:
        from src.whatsapp.role_service import _normalize
        return _normalize(phone)

    def test_whatsapp_standard(self) -> None:
        assert self._norm("+917845952289") == "7845952289"

    def test_no_plus(self) -> None:
        assert self._norm("917845952289") == "7845952289"

    def test_already_10_digit(self) -> None:
        assert self._norm("7845952289") == "7845952289"

    def test_international_dialling_00(self) -> None:
        assert self._norm("00917845952289") == "7845952289"

    def test_non_indian_preserved(self) -> None:
        assert self._norm("+966534015243") == "+966534015243"

    def test_whatsapp_prefix_stripped(self) -> None:
        assert self._norm("whatsapp:+917845952289") == "7845952289"

    def test_spaces_stripped(self) -> None:
        assert self._norm("+91 78459 52289") == "7845952289"
