"""Unit tests for the deduplication engine."""
import pytest
from src.rules.deduplication import compute_hash, batch_deduplicate, enrich_with_hash


def test_same_upi_ref_same_hash():
    t1 = {"date": "2025-03-01", "amount": 5000, "upi_reference": "123456789012", "source": "upi_phonepe"}
    t2 = {"date": "2025-03-01", "amount": 5000, "upi_reference": "123456789012", "source": "upi_gpay"}
    assert compute_hash(t1) == compute_hash(t2)   # UPI ref takes priority over source


def test_different_amount_different_hash():
    t1 = {"date": "2025-03-01", "amount": 5000, "upi_reference": "AAA"}
    t2 = {"date": "2025-03-01", "amount": 5001, "upi_reference": "AAA"}
    assert compute_hash(t1) != compute_hash(t2)


def test_batch_deduplicate_removes_intra_batch_dupes():
    txns = [
        {"date": "2025-03-01", "amount": 1000, "upi_reference": "REF001", "source": "x"},
        {"date": "2025-03-01", "amount": 1000, "upi_reference": "REF001", "source": "y"},  # dupe
        {"date": "2025-03-01", "amount": 2000, "upi_reference": "REF002", "source": "x"},
    ]
    unique, dupes = batch_deduplicate(txns)
    assert len(unique) == 2
    assert len(dupes)  == 1


def test_enrich_with_hash_adds_key():
    txn = {"date": "2025-03-01", "amount": 500, "merchant": "swiggy", "source": "upi_gpay"}
    result = enrich_with_hash(txn)
    assert "unique_hash" in result
    assert len(result["unique_hash"]) == 64


def test_zero_amount_does_not_crash():
    txn = {"date": "2025-03-01", "amount": 0, "upi_reference": "", "source": "cash"}
    h = compute_hash(txn)
    assert isinstance(h, str)
