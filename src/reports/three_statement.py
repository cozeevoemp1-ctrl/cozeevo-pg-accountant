"""
Three-statement financial model — P&L, Balance Sheet, Cash Flow.
Built entirely from live DB data. Zero dependency on pnl_builder.py.

Data sources:
  Revenue  : bank_transactions (Rent Income, Other Income) + payments (cash rent)
  OPEX     : bank_transactions (expense, OPEX categories) + cash_expenses
  Assets   : bank_transactions (cumulative cash) + investment_expenses (Whitefield tracker)
  Deposits : tenancies.security_deposit (active at month-end)
  CapEx    : bank_transactions (Furniture & Fittings, Capital Investment)
  Financing: bank_transactions (Partner Capital / Advance Deposit)
"""

from datetime import date, timedelta
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

# ── Category classification (mirrors finance.py) ─────────────────────────────
OPEX_CATS = {
    "Property Rent", "Electricity", "Water", "IT & Software", "Internet & WiFi",
    "Food & Groceries", "Fuel & Diesel", "Staff & Labour",
    "Maintenance & Repairs", "Cleaning Supplies", "Waste Disposal",
    "Shopping & Supplies", "Operational Expenses", "Marketing",
    "Govt & Regulatory", "Bank Charges", "Other Expenses",
}
CAPEX_CATS = {"Furniture & Fittings", "Capital Investment"}
EXCL_CATS  = {"Tenant Deposit Refund", "Non-Operating"}
# Financing inflows from investor/partner capital transfers
FINANCING_CATS = {"Partner Capital (Whitefield)", "Advance Deposit"}

# Fixed assets depreciation — 5-year straight line from Nov 2025
OPERATIONS_START = date(2025, 11, 1)
DEPRECIATION_MONTHS = 60


def _f(val) -> float:
    return float(val or 0)


def _month_end(month: str) -> date:
    y, m = int(month[:4]), int(month[5:7])
    if m == 12:
        return date(y + 1, 1, 1) - timedelta(days=1)
    return date(y, m + 1, 1) - timedelta(days=1)


def _month_start(month: str) -> date:
    y, m = int(month[:4]), int(month[5:7])
    return date(y, m, 1)


def _prev_month(month: str) -> str:
    y, m = int(month[:4]), int(month[5:7])
    if m == 1:
        return f"{y - 1}-12"
    return f"{y}-{m - 1:02d}"


def _months_since_start(month: str) -> int:
    """Months of depreciation to accumulate up to end of this month."""
    end = _month_end(month)
    if end < OPERATIONS_START:
        return 0
    y1, m1 = OPERATIONS_START.year, OPERATIONS_START.month
    y2, m2 = end.year, end.month
    return (y2 - y1) * 12 + (m2 - m1) + 1


async def build_three_statement(session: AsyncSession, month: str) -> dict:
    """
    month: 'YYYY-MM'
    Returns full three-statement dict for that month.
    """
    m_start = _month_start(month)
    m_end   = _month_end(month)
    prev    = _prev_month(month)
    p_start = _month_start(prev)
    p_end   = _month_end(prev)

    # ── P&L ──────────────────────────────────────────────────────────────────

    # Revenue: bank UPI/digital rent income
    r = await session.execute(text("""
        SELECT COALESCE(SUM(amount), 0)
        FROM bank_transactions
        WHERE txn_type = 'income' AND category = 'Rent Income'
          AND txn_date BETWEEN :s AND :e
    """), {"s": m_start, "e": m_end})
    bank_rent = _f(r.scalar())

    # Revenue: other income (interest, etc.) from bank
    r = await session.execute(text("""
        SELECT COALESCE(SUM(amount), 0)
        FROM bank_transactions
        WHERE txn_type = 'income' AND category = 'Other Income'
          AND txn_date BETWEEN :s AND :e
    """), {"s": m_start, "e": m_end})
    other_income = _f(r.scalar())

    # Revenue: cash rent (payments table, not in bank)
    r = await session.execute(text("""
        SELECT COALESCE(SUM(amount), 0)
        FROM payments
        WHERE is_void = false AND for_type = 'rent' AND payment_mode = 'cash'
          AND payment_date BETWEEN :s AND :e
    """), {"s": m_start, "e": m_end})
    cash_rent = _f(r.scalar())

    total_revenue = bank_rent + cash_rent + other_income

    # OPEX: bank expenses
    r = await session.execute(text("""
        SELECT category, COALESCE(SUM(amount), 0) as total
        FROM bank_transactions
        WHERE txn_type = 'expense'
          AND txn_date BETWEEN :s AND :e
          AND category = ANY(:cats)
        GROUP BY category
    """), {"s": m_start, "e": m_end, "cats": list(OPEX_CATS)})
    bank_opex: dict[str, float] = {row[0]: _f(row[1]) for row in r.fetchall()}

    # OPEX: cash expenses
    r = await session.execute(text("""
        SELECT COALESCE(SUM(amount), 0)
        FROM cash_expenses
        WHERE is_void = false AND date BETWEEN :s AND :e
    """), {"s": m_start, "e": m_end})
    cash_opex = _f(r.scalar())
    if cash_opex:
        bank_opex["Cash Expenses"] = bank_opex.get("Cash Expenses", 0) + cash_opex

    total_opex   = sum(bank_opex.values())
    net_income   = total_revenue - total_opex

    # CapEx this month (investing outflows from bank)
    r = await session.execute(text("""
        SELECT COALESCE(SUM(amount), 0)
        FROM bank_transactions
        WHERE txn_type = 'expense' AND category = ANY(:cats)
          AND txn_date BETWEEN :s AND :e
    """), {"s": m_start, "e": m_end, "cats": list(CAPEX_CATS)})
    capex_month = _f(r.scalar())

    # Tenant deposit refunds this month (investing/balance-sheet outflow)
    r = await session.execute(text("""
        SELECT COALESCE(SUM(amount), 0)
        FROM bank_transactions
        WHERE txn_type = 'expense' AND category = 'Tenant Deposit Refund'
          AND txn_date BETWEEN :s AND :e
    """), {"s": m_start, "e": m_end})
    deposit_refunds_month = _f(r.scalar())

    # Financing inflows this month (investor/partner capital received in bank)
    r = await session.execute(text("""
        SELECT COALESCE(SUM(amount), 0)
        FROM bank_transactions
        WHERE txn_type = 'income' AND category = ANY(:cats)
          AND txn_date BETWEEN :s AND :e
    """), {"s": m_start, "e": m_end, "cats": list(FINANCING_CATS)})
    financing_in_month = _f(r.scalar())

    # ── Balance Sheet ─────────────────────────────────────────────────────────

    # Cash: cumulative all bank activity up to month end (income - expense)
    r = await session.execute(text("""
        SELECT
          COALESCE(SUM(CASE WHEN txn_type='income' THEN amount ELSE 0 END), 0) -
          COALESCE(SUM(CASE WHEN txn_type='expense' THEN amount ELSE 0 END), 0)
        FROM bank_transactions
        WHERE txn_date <= :e
    """), {"e": m_end})
    cash_balance = _f(r.scalar())

    # Previous month cash (for cash flow calc)
    r = await session.execute(text("""
        SELECT
          COALESCE(SUM(CASE WHEN txn_type='income' THEN amount ELSE 0 END), 0) -
          COALESCE(SUM(CASE WHEN txn_type='expense' THEN amount ELSE 0 END), 0)
        FROM bank_transactions
        WHERE txn_date <= :e
    """), {"e": p_end})
    prev_cash = _f(r.scalar())

    # Fixed assets (gross) = all investment_expenses (fixed_asset) + cumulative bank CapEx
    r = await session.execute(text("""
        SELECT COALESCE(SUM(amount), 0) FROM investment_expenses
        WHERE notes = 'fixed_asset' AND is_void = false
    """))
    whitefield_fixed = _f(r.scalar())

    r = await session.execute(text("""
        SELECT COALESCE(SUM(amount), 0)
        FROM bank_transactions
        WHERE txn_type = 'expense' AND category = ANY(:cats)
          AND txn_date <= :e
    """), {"e": m_end, "cats": list(CAPEX_CATS)})
    bank_capex_cumul = _f(r.scalar())

    gross_fixed_assets = whitefield_fixed + bank_capex_cumul

    # Accumulated depreciation (straight-line, 60 months from Nov 2025)
    months_depr = _months_since_start(month)
    monthly_depr = gross_fixed_assets / DEPRECIATION_MONTHS if DEPRECIATION_MONTHS else 0
    accum_depr   = min(monthly_depr * months_depr, gross_fixed_assets)
    net_fixed_assets = gross_fixed_assets - accum_depr

    # Lease deposit (refundable, permanent asset)
    r = await session.execute(text("""
        SELECT COALESCE(SUM(amount), 0) FROM investment_expenses
        WHERE notes = 'lease_deposit' AND is_void = false
    """))
    lease_deposit = _f(r.scalar())

    total_assets = cash_balance + net_fixed_assets + lease_deposit

    # Tenant security deposits held (liability)
    r = await session.execute(text("""
        SELECT COALESCE(SUM(security_deposit), 0)
        FROM tenancies
        WHERE status NOT IN ('exited', 'cancelled')
          AND checkin_date <= :e
    """), {"e": m_end})
    deposits_held = _f(r.scalar())

    # Previous month deposits held (for cash flow calc)
    r = await session.execute(text("""
        SELECT COALESCE(SUM(security_deposit), 0)
        FROM tenancies
        WHERE status NOT IN ('exited', 'cancelled')
          AND checkin_date <= :e
    """), {"e": p_end})
    prev_deposits_held = _f(r.scalar())

    # Investor capital (total from Whitefield tracker, treated as long-term liability/equity)
    r = await session.execute(text("""
        SELECT paid_by, COALESCE(SUM(amount), 0) as total
        FROM investment_expenses WHERE is_void = false
        GROUP BY paid_by ORDER BY total DESC
    """))
    investor_capital: dict[str, float] = {row[0]: _f(row[1]) for row in r.fetchall()}
    total_investor_capital = sum(investor_capital.values())

    # Retained earnings = cumulative net income from start up to this month
    r_hist = await session.execute(text("""
        SELECT
          COALESCE(SUM(CASE WHEN txn_type='income' AND category IN ('Rent Income','Other Income') THEN amount ELSE 0 END), 0) -
          COALESCE(SUM(CASE WHEN txn_type='expense' AND category = ANY(:opex) THEN amount ELSE 0 END), 0)
        FROM bank_transactions
        WHERE txn_date <= :e
    """), {"e": m_end, "opex": list(OPEX_CATS)})
    cumul_bank_ni = _f(r_hist.scalar())

    r_cash_rent_hist = await session.execute(text("""
        SELECT COALESCE(SUM(amount), 0) FROM payments
        WHERE is_void = false AND for_type = 'rent' AND payment_mode = 'cash'
          AND payment_date <= :e
    """), {"e": m_end})
    cumul_cash_rent = _f(r_cash_rent_hist.scalar())

    r_cash_exp_hist = await session.execute(text("""
        SELECT COALESCE(SUM(amount), 0) FROM cash_expenses
        WHERE is_void = false AND date <= :e
    """), {"e": m_end})
    cumul_cash_exp = _f(r_cash_exp_hist.scalar())

    retained_earnings = cumul_bank_ni + cumul_cash_rent - cumul_cash_exp

    total_liabilities = deposits_held
    total_equity      = total_investor_capital + retained_earnings
    total_liab_equity = total_liabilities + total_equity

    # ── Cash Flow (indirect method) ───────────────────────────────────────────

    # Operating
    depr_month       = monthly_depr
    deposit_change   = deposits_held - prev_deposits_held  # increase = cash in (positive)

    total_operating = net_income + depr_month + deposit_change

    # Investing (negative = cash out)
    total_investing = -(capex_month + deposit_refunds_month)

    # Financing
    total_financing = financing_in_month

    net_cash_flow = total_operating + total_investing + total_financing
    ending_cash   = cash_balance
    beginning_cash = prev_cash

    return {
        "month": month,
        "pnl": {
            "bank_rent": round(bank_rent, 2),
            "cash_rent": round(cash_rent, 2),
            "other_income": round(other_income, 2),
            "total_revenue": round(total_revenue, 2),
            "opex_breakdown": {k: round(v, 2) for k, v in sorted(bank_opex.items())},
            "total_opex": round(total_opex, 2),
            "net_income": round(net_income, 2),
        },
        "balance_sheet": {
            "assets": {
                "cash_and_bank": round(cash_balance, 2),
                "net_fixed_assets": round(net_fixed_assets, 2),
                "gross_fixed_assets": round(gross_fixed_assets, 2),
                "accumulated_depreciation": round(accum_depr, 2),
                "lease_deposit": round(lease_deposit, 2),
            },
            "total_assets": round(total_assets, 2),
            "liabilities": {
                "tenant_deposits_held": round(deposits_held, 2),
            },
            "total_liabilities": round(total_liabilities, 2),
            "equity": {
                "investor_capital": round(total_investor_capital, 2),
                "investor_breakdown": {k: round(v, 2) for k, v in investor_capital.items()},
                "retained_earnings": round(retained_earnings, 2),
            },
            "total_equity": round(total_equity, 2),
            "total_liabilities_equity": round(total_liab_equity, 2),
            "check_balanced": abs(total_assets - total_liab_equity) < 1000,
        },
        "cash_flow": {
            "operating": {
                "net_income": round(net_income, 2),
                "depreciation": round(depr_month, 2),
                "change_in_deposits_held": round(deposit_change, 2),
            },
            "total_operating": round(total_operating, 2),
            "investing": {
                "capex": round(-capex_month, 2),
                "deposit_refunds_paid": round(-deposit_refunds_month, 2),
            },
            "total_investing": round(total_investing, 2),
            "financing": {
                "investor_capital_received": round(financing_in_month, 2),
            },
            "total_financing": round(total_financing, 2),
            "net_cash_flow": round(net_cash_flow, 2),
            "beginning_cash": round(beginning_cash, 2),
            "ending_cash": round(ending_cash, 2),
            "cash_reconciled": abs((beginning_cash + net_cash_flow) - ending_cash) < 5000,
        },
    }
