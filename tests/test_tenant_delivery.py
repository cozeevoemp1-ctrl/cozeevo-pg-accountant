"""Phone normalisation for the 24-hr-window check (src/services/tenant_delivery.py).

The window lookup matches on the last 10 digits, so anything that mangles the
number silently sends a first-time tenant a free-form message Meta will reject.
"""
from src.services.tenant_delivery import normalize_wa


def test_ten_digit_gets_country_code():
    assert normalize_wa("9348767967") == "919348767967"


def test_already_prefixed_is_unchanged():
    assert normalize_wa("919348767967") == "919348767967"


def test_punctuation_and_plus_are_stripped():
    assert normalize_wa("+91 93487-67967") == "919348767967"


def test_empty_is_empty():
    assert normalize_wa("") == ""
    assert normalize_wa(None) == ""


def test_tpl_param_flattens_newlines():
    """Meta 400s (#132018) on any body param with a newline — the send just vanishes."""
    from src.services.tenant_delivery import tpl_param
    assert tpl_param("line one\nline two") == "line one line two"
    assert tpl_param("tab\there") == "tab here"
    assert tpl_param("four    spaces") == "four spaces"
    assert tpl_param("") == ""
