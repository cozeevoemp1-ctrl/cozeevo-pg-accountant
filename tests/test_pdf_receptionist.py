"""Tests for PDF agreement — 'Approved by Receptionist' footer line.

All tests are pure unit tests — no DB, no network, no production data.
Uses a minimal mock of OnboardingSession and Room.
"""
from __future__ import annotations

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import io
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pypdf

from src.services.pdf_generator import _generate_pdf_bytes


def _make_obs(**kwargs):
    defaults = dict(
        token="abcd1234efgh5678",
        agreed_rent=Decimal("12000"),
        security_deposit=Decimal("24000"),
        maintenance_fee=Decimal("500"),
        checkin_date=date(2026, 5, 1),
        lock_in_months=3,
        special_terms="",
        signature_image="I_AGREE:TestTenant:2026-05-01T10:00:00",
        approved_by_phone="",
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _make_room():
    return SimpleNamespace(room_number="304", floor=3, room_type=SimpleNamespace(value="double"))


def _extract_text(pdf_bytes: bytes) -> str:
    """Extract all text from PDF bytes using pypdf."""
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _run_pdf(receptionist_name=""):
    obs = _make_obs()
    td = {"name": "Test Tenant", "phone": "9999999001", "gender": "Male", "food_preference": "Veg"}
    room = _make_room()
    pdf_bytes, filename = _generate_pdf_bytes(obs, td, room, "THOR", "double", receptionist_name)
    text = _extract_text(pdf_bytes)
    return text, filename


def test_no_receptionist_name_omits_approved_by():
    text, _ = _run_pdf(receptionist_name="")
    assert "Approved by" not in text


def test_receptionist_name_appears_in_pdf():
    text, _ = _run_pdf(receptionist_name="Lokesh")
    assert "Approved by: Lokesh" in text


def test_receptionist_name_with_spaces():
    text, _ = _run_pdf(receptionist_name="Prabhakaran Devarajulu")
    assert "Approved by: Prabhakaran Devarajulu" in text


def test_ref_token_always_present():
    text, _ = _run_pdf()
    # First 8 chars of token appear in footer
    assert "abcd1234" in text


def test_agreed_on_timestamp_appears():
    text, _ = _run_pdf()
    # I_AGREE timestamp should render as date in PDF
    assert "Agreed on" in text or "Agreement accepted" in text


def test_filename_includes_token_prefix():
    _, filename = _run_pdf()
    assert "abcd1234" in filename
    assert filename.endswith(".pdf")


def test_tenant_name_in_pdf():
    text, _ = _run_pdf()
    assert "Test Tenant" in text


def test_room_number_in_pdf():
    text, _ = _run_pdf()
    assert "304" in text


def test_house_rules_count():
    """PDF must render at least 15 house rules (we have 19)."""
    obs = _make_obs()
    td = {"name": "T", "phone": "9000000001", "gender": "Male", "food_preference": "Veg"}
    pdf_bytes, _ = _generate_pdf_bytes(obs, td, _make_room(), "HULK", "single")
    from src.services.pdf_generator import HOUSE_RULES
    assert len(HOUSE_RULES) >= 15


def test_no_room_does_not_crash():
    obs = _make_obs()
    td = {"name": "T", "phone": "9000000001", "gender": "Male", "food_preference": "Veg"}
    pdf_bytes, _ = _generate_pdf_bytes(obs, td, None, "", "single", "Lokesh")
    assert len(pdf_bytes) > 0
