"""Unit tests for Yes Bank CSV parser."""
import io
from src.parsers.yes_bank import read_yes_bank_csv, parse_date, parse_amt
from datetime import date

SAMPLE_CSV = """some header line
another line
Transaction Date,Value Date,Description,Ref No,Withdrawals,Deposits,Balance
01/05/2026,01/05/2026,UPI/9876543210/PAYMENT/ref123,,5000.00,,100000.00
02/05/2026,02/05/2026,UPI-COLL-RAZORPAY,,, 28000.00,128000.00
"""

def test_parse_date_dmy():
    assert parse_date("01/05/2026") == date(2026, 5, 1)

def test_parse_date_ymd():
    assert parse_date("2026-05-01") == date(2026, 5, 1)

def test_parse_amt_comma():
    assert parse_amt("1,23,456.78") == 123456.78

def test_parse_amt_empty():
    assert parse_amt("") == 0.0

def test_read_yes_bank_csv_from_file_obj():
    f = io.StringIO(SAMPLE_CSV)
    rows = read_yes_bank_csv(f)
    # one expense + one income
    assert len(rows) == 2
    types = [r[2] for r in rows]
    amts  = [r[3] for r in rows]
    assert "expense" in types
    assert "income" in types
    assert 5000.0 in amts
    assert 28000.0 in amts


# HULK collection account: header ALSO starts with 'Transaction Date' but has
# only a Deposits column (no Withdrawals). Regression for the bug where this was
# misdetected as THOR layout and every collection was booked as an expense.
HULK_DEPOSITS_ONLY = """124563400000881 ,COZEEVO COLIVING HULK
Opening Balance,814941.0
Closing Balance,2026040.66
Transaction Date,Value Date,Description,Reference Number,Deposits,Running Balance
2026-05-31,2026-05-31,115063600001082/547273772 UPI Collection Settlement/COZEEVO/CBS,YESF26151,9338.00,
2026-05-30,2026-05-30,115063600001082/545871346 UPI Collection Settlement/COZEEVO/CBS,YESF26150,35516.00,
"""

def test_hulk_deposits_only_booked_as_income():
    rows = read_yes_bank_csv(io.StringIO(HULK_DEPOSITS_ONLY))
    assert len(rows) == 2
    assert all(r[2] == "income" for r in rows), "HULK deposits must be income, not expense"
    assert sum(r[3] for r in rows) == 9338.0 + 35516.0


def test_thor_withdrawals_and_deposits_split():
    # THOR full layout: withdrawal → expense, deposit → income (by header name)
    csv = (
        "Transaction Date,Value Date,Description,Reference Number,Withdrawals,Deposits,Running Balance\n"
        "2026-05-31,2026-05-31,UPI/x/To:vendor,REF1,2273.00,,INR 914857.74\n"
        "2026-05-30,2026-05-30,UPI Collection Settlement,REF2,,108000.00,INR 999999.00\n"
    )
    rows = read_yes_bank_csv(io.StringIO(csv))
    by_type = {r[2]: r[3] for r in rows}
    assert by_type["expense"] == 2273.0
    assert by_type["income"] == 108000.0
