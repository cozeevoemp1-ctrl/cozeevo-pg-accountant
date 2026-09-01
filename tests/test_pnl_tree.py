"""
Parity tests for the SOP P&L tree (spec 01, Phase 1).

The tree served by GET /finance/pnl/month must carry EXACTLY the numbers the
Excel builder would place in that month's column. These tests pin the reshape
layer to the Excel translation (`pnl_builder._dynamic_line_values`) and to the
SOP formulas:
    True Revenue  = Gross Inflows − deposits held − deposits refunded
    Net Operating = True Revenue − Total Opex
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.api.v2.finance import (  # noqa: E402
    _VERIFIED_YM,
    _build_pnl_tree_dynamic,
    _build_pnl_tree_frozen,
)
from src.reports.pnl_builder import _dynamic_line_values  # noqa: E402

# A representative engine record (same shape _compute_dynamic_pnl_months emits)
RECORD = {
    "label": "Aug'26",
    "income_thor": 1_00_000.0,
    "income_hulk": 50_000.0,
    "cash": 25_000.0,  # engine already includes offline_cash in this figure
    "opex_by_cat": {"Electricity": 12_000.0, "Water": 3_000.0, "Other Expenses": 500.0},
    "dep_refunded": 7_000.0,
    "non_op": 20_000.0,
    "non_op_detail": {"Hand Loan to Bava (Bunk)": 20_000.0},
    "sec_dep": 40_000.0,
    "maint": 9_000.0,
    "rent_paid_cash": 60_000.0,
    "cash_expense": 1_500.0,
    "cash_holding": 0.0,
    "bank_thor_close": 0.0,
    "bank_hulk_close": 0.0,
    "sec_owed_total": 0.0,
}


def _flat(nodes):
    for n in nodes:
        yield n
        yield from _flat(n.get("children") or [])


def test_dynamic_totals_follow_sop_formulas():
    tree, totals = _build_pnl_tree_dynamic(RECORD)
    gross = 1_00_000 + 50_000 + 25_000
    opex = 12_000 + 3_000 + 500 + 60_000 + 1_500
    true_rev = gross - 40_000 - 7_000
    assert totals["gross"] == gross
    assert totals["opex_total"] == opex
    assert totals["true_revenue"] == true_rev
    assert totals["net_operating"] == true_rev - opex


def test_dynamic_tree_matches_excel_translation():
    """The tree's section sums == what pnl_builder would write into the Excel column."""
    tree, totals = _build_pnl_tree_dynamic(RECORD)
    income, opex, excluded = _dynamic_line_values(RECORD)
    assert totals["gross"] == sum(income.values())
    assert totals["opex_total"] == sum(opex.values())
    # Excel subtracts the refund line from True Revenue — tree must agree
    refund_key = "Tenant Deposit Refund (balance sheet)"
    assert excluded[refund_key] == RECORD["dep_refunded"]
    assert totals["true_revenue"] == sum(income.values()) - RECORD["sec_dep"] - excluded[refund_key]


def test_node_amounts_sum_to_parent():
    tree, totals = _build_pnl_tree_dynamic(RECORD)
    by_key = {n["key"]: n for n in _flat(tree)}
    income = by_key["income"]
    assert round(sum(c["amount"] for c in income["children"]), 2) == income["amount"]
    opex = by_key["opex"]
    assert round(sum(c["amount"] for c in opex["children"]), 2) == opex["amount"]
    # deposits node = the two real subtractions; maintenance is display-only
    deposits = by_key["deposits"]
    real = [c for c in deposits["children"] if not c["display_only"]]
    assert round(sum(c["amount"] for c in real), 2) == deposits["amount"]
    assert by_key["deposits.maintenance"]["display_only"] is True


def test_manual_figures_are_marked():
    tree, _ = _build_pnl_tree_dynamic(RECORD)
    by_key = {n["key"]: n for n in _flat(tree)}
    assert by_key["opex.manual.rent_paid_cash"]["manual"] is True
    assert by_key["opex.manual.cash_expense"]["manual"] is True
    assert by_key["opex.manual.rent_paid_cash"]["amount"] == -60_000
    # bank-backed lines are drillable; manual figures are not
    assert by_key["opex.Electricity"]["drillable"] is True
    assert by_key["opex.manual.rent_paid_cash"]["drillable"] is False


def test_frozen_month_consistent_and_not_drillable():
    ym = sorted(_VERIFIED_YM)[-1]  # latest verified month
    tree, totals = _build_pnl_tree_frozen(ym)
    by_key = {n["key"]: n for n in _flat(tree)}
    income = by_key["income"]
    assert round(sum(c["amount"] for c in income["children"]), 2) == income["amount"]
    assert totals["net_operating"] == round(totals["true_revenue"] - totals["opex_total"], 2)
    assert all(not n["drillable"] for n in _flat(tree))


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))


def test_sub_buckets_sum_to_category_and_are_drillable():
    """Food & Groceries expands into sub-buckets (Chicken / Eggs / …) whose amounts
    sum exactly to the category line; blank sub_category rows surface as Unsorted.
    Sub-buckets never change a total — they only regroup the drill-down."""
    rec = dict(RECORD)
    rec["opex_by_cat"] = dict(RECORD["opex_by_cat"], **{"Food & Groceries": 10_000.0})
    rec["opex_sub_by_cat"] = {"Food & Groceries": {"Chicken": 6_000.0, "Eggs": 3_500.0, "Unsorted": 500.0}}
    tree, totals = _build_pnl_tree_dynamic(rec)
    by_key = {n["key"]: n for n in _flat(tree)}
    food = by_key["opex.Food & Groceries"]
    assert round(sum(c["amount"] for c in food["children"]), 2) == food["amount"] == -10_000.0
    assert [c["key"] for c in food["children"]] == [
        "opex.Food & Groceries::Chicken", "opex.Food & Groceries::Eggs", "opex.Food & Groceries::Unsorted",
    ]
    assert all(c["drillable"] for c in food["children"])
    # categories without sub-buckets carry no children and totals are unchanged
    assert "children" not in by_key["opex.Electricity"]
    base_tree, base_totals = _build_pnl_tree_dynamic(dict(rec, opex_sub_by_cat={}))
    assert totals == base_totals
