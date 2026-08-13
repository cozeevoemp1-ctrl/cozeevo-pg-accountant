"""Unit tests for broadcast delivery report compilation (summarize_statuses).

Pure-function tests — no DB, no network. The wamid_map is what a broadcast
script collects at send time; rows are what the status webhook wrote.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.whatsapp.broadcast_report import summarize_statuses  # noqa: E402

WAMIDS = {
    "wamid.A": ("Kiran", "7845952289"),
    "wamid.B": ("Lokesh", "7680814628"),
    "wamid.C": ("Lakshmi Mam", "7358341775"),
    "wamid.D": ("Rakesh", "9000000001"),
}


def test_all_delivered_no_failures():
    rows = [
        ("wamid.A", "sent", None, None),
        ("wamid.A", "delivered", None, None),
        ("wamid.A", "read", None, None),
        ("wamid.B", "delivered", None, None),
        ("wamid.C", "delivered", None, None),
        ("wamid.D", "read", None, None),
    ]
    s = summarize_statuses(rows, WAMIDS, "test notice")
    assert "4 messages" in s
    assert "4 delivered (2 read)" in s
    assert "No failures" in s
    assert "FAILED" not in s


def test_failed_named_with_reason():
    rows = [
        ("wamid.A", "delivered", None, None),
        ("wamid.B", "delivered", None, None),
        ("wamid.C", "failed", 131048, "Spam rate limit hit"),
        ("wamid.D", "failed", 131026, "Message undeliverable"),
    ]
    s = summarize_statuses(rows, WAMIDS, "test notice")
    assert "2 delivered" in s
    assert "2 FAILED" in s
    assert "Lakshmi Mam (7358341775) #131048 Spam rate limit hit" in s
    assert "Rakesh (9000000001) #131026 Message undeliverable" in s


def test_sent_but_failed_counts_as_failed_only():
    # Meta often emits 'sent' first, then 'failed' — failed must win.
    rows = [
        ("wamid.A", "sent", None, None),
        ("wamid.A", "failed", 130429, "Rate limit hit"),
    ]
    s = summarize_statuses(rows, {"wamid.A": WAMIDS["wamid.A"]}, "x")
    assert "1 FAILED" in s
    assert "0 delivered" in s
    assert "accepted not yet delivered" not in s


def test_no_status_and_accepted_only_buckets():
    rows = [
        ("wamid.A", "delivered", None, None),
        ("wamid.B", "sent", None, None),
        # wamid.C, wamid.D: no webhook rows at all
    ]
    s = summarize_statuses(rows, WAMIDS, "x")
    assert "1 delivered" in s
    assert "1 accepted not yet delivered" in s
    assert "2 no status yet" in s


def test_unknown_wamids_in_rows_ignored():
    rows = [("wamid.OTHER", "failed", 131048, "Spam rate limit hit")]
    s = summarize_statuses(rows, WAMIDS, "x")
    assert "FAILED" not in s
    assert "4 no status yet" in s


def test_flat_single_paragraph_and_length_cap():
    # 300 failures must not blow the 1024-char template param limit
    big_map = {f"wamid.{i}": (f"Tenant Number {i}", f"9{i:09d}") for i in range(300)}
    rows = [(w, "failed", 131048, "Spam rate limit hit") for w in big_map]
    s = summarize_statuses(rows, big_map, "big broadcast")
    assert "\n" not in s and "\t" not in s
    assert "    " not in s  # 4+ consecutive spaces also rejected by Meta
    assert len(s) <= 960
    assert "(truncated)" in s
