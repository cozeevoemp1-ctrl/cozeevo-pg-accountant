"""Unit tests for parsers and categorization rules."""
import pytest
from src.rules.categorization_rules import classify, classify_batch
from src.rules.merchant_rules import normalize_merchant, clean_amount, extract_upi_ref
from src.parsers.base_parser import BaseParser


# ── Categorization ─────────────────────────────────────────────────────────

def test_classify_swiggy():
    result = classify("Swiggy order", "Swiggy", "expense")
    assert result.category == "Food & Beverages"
    assert result.confidence > 0.80
    assert not result.needs_ai


def test_classify_electricity():
    result = classify("BESCOM electricity bill payment", "", "expense")
    assert result.category == "Electricity"
    assert result.confidence > 0.90


def test_classify_rent():
    result = classify("Monthly rent received", "", "income")
    assert result.category == "Rent"


def test_classify_unknown_triggers_ai():
    result = classify("payment to xyz123 pvt ltd", "", "expense")
    assert result.needs_ai


def test_classify_batch():
    txns = [
        {"description": "Swiggy order", "merchant": "Swiggy", "txn_type": "expense"},
        {"description": "Electricity bill", "merchant": "BESCOM", "txn_type": "expense"},
    ]
    result = classify_batch(txns)
    assert result[0]["category"] == "Food & Beverages"
    assert result[1]["category"] == "Electricity"


# ── Merchant normalization ─────────────────────────────────────────────────

def test_normalize_phonepe():
    assert normalize_merchant("PHONEPE-XXXXXXXXXX") == "PhonePe"


def test_normalize_swiggy():
    assert normalize_merchant("SWIGGY*ORDER_12345") == "Swiggy"


def test_normalize_bescom():
    assert normalize_merchant("BESCOM online payment") == "BESCOM"


# ── Amount cleaning ────────────────────────────────────────────────────────

def test_clean_amount_inr():
    assert clean_amount("₹1,234.56") == 1234.56


def test_clean_amount_negative():
    assert clean_amount("-500.00") == -500.0


def test_clean_amount_debit():
    assert clean_amount("1000 Dr") == -1000.0


def test_clean_amount_credit():
    assert clean_amount("2000 Cr") == 2000.0


# ── UPI reference extraction ──────────────────────────────────────────────

def test_extract_upi_ref_12digit():
    ref = extract_upi_ref("UPI/123456789012/payment")
    assert ref == "123456789012"


def test_extract_upi_ref_none():
    ref = extract_upi_ref("cash payment at store")
    assert ref is None
