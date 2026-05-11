"""Unit tests for cash position calculation logic."""


def compute_balance(collected: float, expenses: list[float]) -> float:
    return collected - sum(expenses)


def compute_variance(balance: float, counted: float) -> float:
    return balance - counted


def test_balance_no_expenses():
    assert compute_balance(100000, []) == 100000


def test_balance_with_expenses():
    assert compute_balance(100000, [20000, 5000]) == 75000


def test_variance_short():
    # counted less than expected → positive variance = short
    assert compute_variance(100000, 90000) == 10000


def test_variance_over():
    # counted more than expected → negative variance = over
    assert compute_variance(100000, 110000) == -10000


def test_variance_exact():
    assert compute_variance(100000, 100000) == 0
