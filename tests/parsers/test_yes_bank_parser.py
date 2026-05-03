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
    dates, descs, types, amts = zip(*rows)
    assert "expense" in types
    assert "income" in types
    assert 5000.0 in amts
    assert 28000.0 in amts
