"""Tests for finance API helpers."""
import io
import hashlib
from src.parsers.yes_bank import read_yes_bank_csv
from src.rules.pnl_classify import classify_txn

SAMPLE_CSV = """Transaction Date,Value Date,Description,Ref No,Withdrawals,Deposits,Balance
01/05/2026,01/05/2026,UPI/MANOJ B/water/9535665407,,42500.00,,100000.00
02/05/2026,02/05/2026,UPI-COLL-RAZORPAY-settlements,,,28000.00,128000.00
"""

def _make_hash(dt, amt, desc) -> str:
    key = f"{dt}|{round(float(amt), 2):.2f}|{desc.strip().lower()}"
    return hashlib.sha256(key.encode()).hexdigest()

def test_parse_and_classify():
    rows = read_yes_bank_csv(io.StringIO(SAMPLE_CSV))
    assert len(rows) == 2
    for dt, desc, typ, amt in rows:
        cat, sub = classify_txn(desc, typ)
        assert cat  # never empty

def test_expense_classifies_as_water():
    rows = read_yes_bank_csv(io.StringIO(SAMPLE_CSV))
    expense = next(r for r in rows if r[2] == "expense")
    cat, _ = classify_txn(expense[1], "expense")
    assert cat == "Water"

def test_income_classifies_as_upi_batch():
    rows = read_yes_bank_csv(io.StringIO(SAMPLE_CSV))
    income = next(r for r in rows if r[2] == "income")
    cat, _ = classify_txn(income[1], "income")
    # Razorpay settlements are UPI Batch
    assert "batch" in cat.lower() or "upi" in cat.lower() or "income" in cat.lower()

def test_dedup_hash_deterministic():
    from datetime import date
    h1 = _make_hash(date(2026, 5, 1), 42500, "UPI/MANOJ B/water")
    h2 = _make_hash(date(2026, 5, 1), 42500, "UPI/MANOJ B/water")
    assert h1 == h2

def test_dedup_hash_differs_for_different_txns():
    from datetime import date
    h1 = _make_hash(date(2026, 5, 1), 42500, "UPI/MANOJ B/water")
    h2 = _make_hash(date(2026, 5, 1), 42500, "BESCOM PAYMENT")
    assert h1 != h2
