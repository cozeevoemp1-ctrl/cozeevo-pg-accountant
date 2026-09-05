"""Unit tests for src/utils/name_match.names_match — Aadhaar name vs form name."""
import pytest

from src.utils.name_match import names_match


@pytest.mark.parametrize("a,b", [
    ("Raghav", "Raghav Mittal"),
    ("Raghav Mittal", "MITTAL RAGHAV"),
    ("K Raghav", "Raghav Kumar"),
    ("raghav  mittal", "Raghav Mittal"),
    ("Mathew Koshy", "Mathew Koshy"),
    ("Sheetal", "Sheetal S."),
])
def test_matches(a, b):
    assert names_match(a, b)


@pytest.mark.parametrize("a,b", [
    ("Loki", "Lokesh Kumar"),
    ("Raghav Mittal", "Rakesh Mittal"),
    ("Kiran", "Prabhakaran"),
    ("", "Raghav"),
    ("Raghav", ""),
    ("K", "Raghav Kumar"),
])
def test_mismatches(a, b):
    assert not names_match(a, b)
