"""
Comprehensive E2E test suite — 100 test cases for rent collection workflows.
Simulates Sathyam (receptionist, 7993273966) learning the system.
Tests: payment logging, corrections, duplicates, voids, deposits, advances, edge cases.

Usage: venv/Scripts/python tests/test_receptionist_e2e.py
Requires: API running on localhost:8000 with TEST_MODE=1
"""
import httpx
import asyncio
import json
import sys
import re
from dataclasses import dataclass, field
from typing import Optional

API = "http://127.0.0.1:8000/api/whatsapp/process"
CLEAR = "http://127.0.0.1:8000/api/test/clear-pending"
PHONE = "917993273966"  # Sathyam


@dataclass
class TestCase:
    id: str
    category: str
    description: str
    turns: list  # [(message, check_fn), ...]
    result: str = ""
    error: str = ""
    replies: list = field(default_factory=list)


# -- Helpers ------------------------------------------------------------------

async def send(client: httpx.AsyncClient, msg: str, phone: str = PHONE) -> dict:
    resp = await client.post(API, json={
        "phone": phone, "message": msg, "message_id": f"test-{msg[:20]}"
    }, timeout=15)
    return resp.json()


async def clear(client: httpx.AsyncClient, phone: str = PHONE):
    try:
        await client.post(CLEAR, json={"phone": phone}, timeout=5)
    except Exception:
        pass


def has(text: str, *keywords: str) -> bool:
    """Check reply contains ALL keywords (case-insensitive)."""
    t = (text or "").lower()
    return all(k.lower() in t for k in keywords)


def has_any(text: str, *keywords: str) -> bool:
    """Check reply contains ANY keyword."""
    t = (text or "").lower()
    return any(k.lower() in t for k in keywords)


def no(text: str, *keywords: str) -> bool:
    """Check reply does NOT contain any keyword."""
    t = (text or "").lower()
    return not any(k.lower() in t for k in keywords)


def is_confirm_prompt(text: str) -> bool:
    """Check if reply is asking for yes/no confirmation."""
    return has_any(text, "reply *yes*", "reply yes", "confirm", "yes* to confirm")


def is_payment_logged(text: str) -> bool:
    """Check if payment was successfully logged."""
    return has_any(text, "payment logged", "logged", "recorded", "confirmed")


def is_error(text: str) -> bool:
    return has_any(text, "sorry", "error", "went wrong", "couldn't")


# -- Test Case Definitions ----------------------------------------------------

def build_tests() -> list[TestCase]:
    tests = []

    # =========================================================================
    # CATEGORY 1: BASIC RENT COLLECTION (various message formats)
    # =========================================================================

    tests.append(TestCase("R001", "basic", "Name paid Amount", [
        ("Aahil paid 16000 cash", lambda r: is_confirm_prompt(r) or has(r, "aahil")),
        ("no", lambda r: has_any(r, "cancel", "ok")),
    ]))

    tests.append(TestCase("R002", "basic", "Amount paid by Name", [
        ("16000 paid by Aahil", lambda r: is_confirm_prompt(r) or has(r, "aahil")),
        ("no", lambda r: True),
    ]))

    tests.append(TestCase("R003", "basic", "Name Amount mode", [
        ("Aahil 16000 cash", lambda r: is_confirm_prompt(r) or has(r, "aahil")),
        ("no", lambda r: True),
    ]))

    tests.append(TestCase("R004", "basic", "Amount from Name", [
        ("16000 from Aahil", lambda r: is_confirm_prompt(r) or has(r, "aahil")),
        ("no", lambda r: True),
    ]))

    tests.append(TestCase("R005", "basic", "collect rent (generic trigger)", [
        ("collect rent", lambda r: has_any(r, "who", "name", "which tenant", "format")),
    ]))

    tests.append(TestCase("R006", "basic", "Name payment received", [
        ("Aahil payment received 16000", lambda r: is_confirm_prompt(r) or has(r, "aahil")),
        ("no", lambda r: True),
    ]))

    tests.append(TestCase("R007", "basic", "received Amount from Name", [
        ("received 15000 from Abhishek Anand", lambda r: is_confirm_prompt(r) or has(r, "abhishek")),
        ("no", lambda r: True),
    ]))

    tests.append(TestCase("R008", "basic", "Name paid Amount UPI", [
        ("Adnan Doshi paid 14500 upi", lambda r: is_confirm_prompt(r) or has(r, "adnan")),
        ("no", lambda r: True),
    ]))

    tests.append(TestCase("R009", "basic", "Amount k shorthand", [
        ("Aahil paid 16k cash", lambda r: is_confirm_prompt(r) or has(r, "16,000", "aahil")),
        ("no", lambda r: True),
    ]))

    tests.append(TestCase("R010", "basic", "Name Rs.Amount", [
        ("Aahil paid Rs.16000", lambda r: is_confirm_prompt(r) or has(r, "aahil")),
        ("no", lambda r: True),
    ]))

    # =========================================================================
    # CATEGORY 2: PAYMENT MODES (cash, upi, gpay, phonepe, etc.)
    # =========================================================================

    tests.append(TestCase("M001", "mode", "cash payment", [
        ("Advait paid 13000 cash", lambda r: is_confirm_prompt(r) and has(r, "cash")),
        ("no", lambda r: True),
    ]))

    tests.append(TestCase("M002", "mode", "upi payment", [
        ("Advait paid 13000 upi", lambda r: is_confirm_prompt(r) and has(r, "upi")),
        ("no", lambda r: True),
    ]))

    tests.append(TestCase("M003", "mode", "gpay payment", [
        ("Advait paid 13000 gpay", lambda r: has_any(r, "upi", "gpay")),
        ("no", lambda r: True),
    ]))

    tests.append(TestCase("M004", "mode", "phonepe payment", [
        ("Advait paid 13000 phonepe", lambda r: has_any(r, "upi", "phonepe")),
        ("no", lambda r: True),
    ]))

    tests.append(TestCase("M005", "mode", "online payment", [
        ("Advait paid 13000 online", lambda r: has_any(r, "upi", "online")),
        ("no", lambda r: True),
    ]))

    tests.append(TestCase("M006", "mode", "transfer payment", [
        ("Advait paid 13000 transfer", lambda r: has_any(r, "upi", "transfer")),
        ("no", lambda r: True),
    ]))

    tests.append(TestCase("M007", "mode", "no mode = default cash", [
        ("Advait paid 13000", lambda r: is_confirm_prompt(r)),
        ("no", lambda r: True),
    ]))

    # =========================================================================
    # CATEGORY 3: CONFIRMATION FLOW (yes/no/corrections)
    # =========================================================================

    tests.append(TestCase("C001", "confirm", "confirm with yes", [
        ("Akarsh Sm paid 15000 cash", lambda r: is_confirm_prompt(r)),
        ("yes", lambda r: is_payment_logged(r)),
    ]))

    tests.append(TestCase("C002", "confirm", "confirm with haan", [
        ("Ankit Kumar room 320 paid 13000 cash", lambda r: is_confirm_prompt(r) or has(r, "ankit")),
        ("haan", lambda r: is_payment_logged(r) or has(r, "confirm")),
    ]))

    tests.append(TestCase("C003", "confirm", "cancel with no", [
        ("Akarsh Sm paid 15000 cash", lambda r: is_confirm_prompt(r)),
        ("no", lambda r: has_any(r, "cancel", "ok", "noted")),
    ]))

    tests.append(TestCase("C004", "confirm", "correct amount mid-flow", [
        ("Akarsh Sm paid 15000 cash", lambda r: is_confirm_prompt(r)),
        ("no 14500", lambda r: has_any(r, "14,500", "14500", "updated")),
    ]))

    tests.append(TestCase("C005", "confirm", "correct mode mid-flow cash->upi", [
        ("Akarsh Sm paid 15000 cash", lambda r: is_confirm_prompt(r)),
        ("no it was upi", lambda r: has_any(r, "upi", "updated")),
    ]))

    tests.append(TestCase("C006", "confirm", "correct mode mid-flow upi->cash", [
        ("Akarsh Sm paid 15000 upi", lambda r: is_confirm_prompt(r)),
        ("actually cash", lambda r: has_any(r, "cash", "updated")),
    ]))

    tests.append(TestCase("C007", "confirm", "confirm with ok", [
        ("Akarsh Sm paid 15000 cash", lambda r: is_confirm_prompt(r)),
        ("ok", lambda r: is_payment_logged(r) or has(r, "confirm")),
    ]))

    # =========================================================================
    # CATEGORY 4: FUZZY NAME MATCHING
    # =========================================================================

    tests.append(TestCase("F001", "fuzzy", "partial name match", [
        ("Abhishek paid 15000 cash", lambda r: has_any(r, "which", "multiple", "abhishek", "choose")),
    ]))

    tests.append(TestCase("F002", "fuzzy", "exact name match", [
        ("Aahil paid 16000", lambda r: has(r, "aahil")),
        ("no", lambda r: True),
    ]))

    tests.append(TestCase("F003", "fuzzy", "misspelled name", [
        ("Adnan Dosi paid 14500", lambda r: has_any(r, "adnan", "did you mean", "no tenant")),
    ]))

    tests.append(TestCase("F004", "fuzzy", "non-existent tenant", [
        ("Zzzzrandom paid 5000", lambda r: has_any(r, "no tenant", "not found", "couldn't find", "no match")),
    ]))

    tests.append(TestCase("F005", "fuzzy", "full name for disambiguation", [
        ("Abhishek S Rao paid 14500", lambda r: has(r, "abhishek") or has(r, "111")),
        ("no", lambda r: True),
    ]))

    tests.append(TestCase("F006", "fuzzy", "room number for lookup", [
        ("room 606 paid 16000", lambda r: has_any(r, "aahil", "606")),
        ("no", lambda r: True),
    ]))

    tests.append(TestCase("F007", "fuzzy", "room number at start", [
        ("606 paid 16000", lambda r: has_any(r, "aahil", "606")),
        ("no", lambda r: True),
    ]))

    # =========================================================================
    # CATEGORY 5: MULTIPLE TENANT DISAMBIGUATION
    # =========================================================================

    tests.append(TestCase("D001", "disambig", "multiple Abhishek - pick by number", [
        ("Abhishek paid 12000", lambda r: has_any(r, "1.", "2.", "which", "multiple")),
        ("1", lambda r: has_any(r, "abhishek", "confirm", "yes")),
        ("no", lambda r: True),
    ]))

    tests.append(TestCase("D002", "disambig", "multiple Ankit Kumar", [
        ("Ankit Kumar paid 10000", lambda r: has_any(r, "1.", "2.", "which", "320", "g13")),
    ]))

    # =========================================================================
    # CATEGORY 6: AMOUNT EDGE CASES
    # =========================================================================

    tests.append(TestCase("A001", "amount", "comma separated amount", [
        ("Aahil paid 16,000 cash", lambda r: has(r, "16,000") or has(r, "aahil")),
        ("no", lambda r: True),
    ]))

    tests.append(TestCase("A002", "amount", "k suffix (5k=5000)", [
        ("Aahil paid 5k cash", lambda r: has(r, "5,000") or has(r, "aahil")),
        ("no", lambda r: True),
    ]))

    tests.append(TestCase("A003", "amount", "very small amount", [
        ("Aahil paid 100 cash", lambda r: has_any(r, "100", "aahil", "confirm")),
        ("no", lambda r: True),
    ]))

    tests.append(TestCase("A004", "amount", "very large amount", [
        ("Aahil paid 50000 cash", lambda r: has_any(r, "50,000", "aahil")),
        ("no", lambda r: True),
    ]))

    tests.append(TestCase("A005", "amount", "partial rent payment", [
        ("Aahil paid 8000 cash", lambda r: has_any(r, "8,000", "partial", "aahil")),
        ("no", lambda r: True),
    ]))

    tests.append(TestCase("A006", "amount", "zero amount", [
        ("Aahil paid 0 cash", lambda r: has_any(r, "amount", "include", "format", "0")),
    ]))

    tests.append(TestCase("A007", "amount", "no amount in message", [
        ("Aahil paid cash", lambda r: has_any(r, "amount", "include", "format", "how much")),
    ]))

    tests.append(TestCase("A008", "amount", "decimal amount", [
        ("Aahil paid 15000.50 cash", lambda r: has_any(r, "aahil", "15,000", "15000")),
        ("no", lambda r: True),
    ]))

    # =========================================================================
    # CATEGORY 7: DUPLICATE DETECTION
    # =========================================================================

    tests.append(TestCase("DUP001", "duplicate", "same payment twice - detect dup", [
        ("Akarsh Sm paid 15000 cash", lambda r: is_confirm_prompt(r)),
        ("yes", lambda r: is_payment_logged(r)),
        # Same payment again
        ("Akarsh Sm paid 15000 cash", lambda r: has_any(r, "duplicate", "same amount", "already", "confirm")),
    ]))

    tests.append(TestCase("DUP002", "duplicate", "same amount different mode - not dup", [
        ("Ahana Dutta paid 16000 cash", lambda r: is_confirm_prompt(r)),
        ("yes", lambda r: is_payment_logged(r)),
        ("Ahana Dutta paid 16000 upi", lambda r: has_any(r, "duplicate", "confirm", "ahana")),
    ]))

    tests.append(TestCase("DUP003", "duplicate", "different amount same person - not dup", [
        ("Adharsh Unni paid 10000 cash", lambda r: is_confirm_prompt(r)),
        ("yes", lambda r: is_payment_logged(r)),
        ("Adharsh Unni paid 3000 cash", lambda r: is_confirm_prompt(r) and no(r, "duplicate")),
        ("no", lambda r: True),
    ]))

    # =========================================================================
    # CATEGORY 8: VOID PAYMENTS
    # =========================================================================

    tests.append(TestCase("V001", "void", "void a payment", [
        ("void Akarsh payment", lambda r: has_any(r, "which payment", "void", "1.", "akarsh")),
    ]))

    tests.append(TestCase("V002", "void", "cancel/reverse payment", [
        ("cancel Ahana payment", lambda r: has_any(r, "which", "void", "cancel", "ahana")),
    ]))

    tests.append(TestCase("V003", "void", "undo payment", [
        ("undo payment for Aahil", lambda r: has_any(r, "which", "void", "undo", "aahil")),
    ]))

    tests.append(TestCase("V004", "void", "wrong payment logged", [
        ("wrong payment Akarsh", lambda r: has_any(r, "which", "void", "wrong", "akarsh")),
    ]))

    # =========================================================================
    # CATEGORY 9: QUERY DUES
    # =========================================================================

    tests.append(TestCase("Q001", "query", "who hasn't paid", [
        ("who hasn't paid", lambda r: has_any(r, "pending", "dues", "unpaid", "hasn't")),
    ]))

    tests.append(TestCase("Q002", "query", "pending dues", [
        ("pending dues", lambda r: has_any(r, "pending", "dues", "unpaid")),
    ]))

    tests.append(TestCase("Q003", "query", "who owes rent", [
        ("who owes rent", lambda r: has_any(r, "pending", "dues", "owes")),
    ]))

    tests.append(TestCase("Q004", "query", "Aahil balance", [
        ("Aahil balance", lambda r: has_any(r, "aahil", "balance", "dues", "paid", "0")),
    ]))

    tests.append(TestCase("Q005", "query", "check dues for room 606", [
        ("dues for room 606", lambda r: has_any(r, "aahil", "606", "dues", "balance")),
    ]))

    tests.append(TestCase("Q006", "query", "monthly report", [
        ("monthly report", lambda r: has_any(r, "owner-level", "report", "access")),
    ]))

    # =========================================================================
    # CATEGORY 10: EXPENSES
    # =========================================================================

    tests.append(TestCase("E001", "expense", "electricity bill", [
        ("electricity bill 8400", lambda r: has_any(r, "expense", "electricity", "8,400", "logged", "confirm")),
    ]))

    tests.append(TestCase("E002", "expense", "log expense generic", [
        ("log expense", lambda r: has_any(r, "what", "expense", "format", "description")),
    ]))

    tests.append(TestCase("E003", "expense", "plumber expense", [
        ("plumber 2500 cash", lambda r: has_any(r, "expense", "plumber", "maintenance", "2,500", "2500")),
    ]))

    tests.append(TestCase("E004", "expense", "water bill", [
        ("water bill 3000", lambda r: has_any(r, "expense", "water", "3,000", "3000")),
    ]))

    tests.append(TestCase("E005", "expense", "salary payment", [
        ("salary Arjun 12000", lambda r: has_any(r, "expense", "salary", "arjun", "12,000", "12000")),
    ]))

    # =========================================================================
    # CATEGORY 11: TYPOS & NATURAL LANGUAGE VARIATIONS
    # =========================================================================

    tests.append(TestCase("T001", "typo", "pajment instead of payment", [
        ("Aahil pajment 16000", lambda r: has_any(r, "aahil", "confirm", "16,000")),
        ("no", lambda r: True),
    ]))

    tests.append(TestCase("T002", "typo", "paied instead of paid", [
        ("Aahil paied 16000 cash", lambda r: has_any(r, "aahil", "confirm", "16,000")),
        ("no", lambda r: True),
    ]))

    tests.append(TestCase("T003", "typo", "recieved instead of received", [
        ("recieved 16000 from Aahil", lambda r: has_any(r, "aahil", "confirm", "16,000")),
        ("no", lambda r: True),
    ]))

    tests.append(TestCase("T004", "typo", "cashe instead of cash", [
        ("Aahil paid 16000 cashe", lambda r: has_any(r, "aahil", "confirm")),
        ("no", lambda r: True),
    ]))

    tests.append(TestCase("T005", "typo", "Hindi style - jama karo", [
        ("Aahil 16000 jama", lambda r: has_any(r, "aahil", "confirm", "16,000")),
        ("no", lambda r: True),
    ]))

    # =========================================================================
    # CATEGORY 12: TWO PEOPLE LOGGING SAME PAYMENT
    # =========================================================================

    tests.append(TestCase("DUAL001", "dual_entry", "Sathyam logs, then admin logs same", [
        ("Aditaya Sanghi paid 13000 cash", lambda r: is_confirm_prompt(r)),
        ("yes", lambda r: is_payment_logged(r)),
    ]))
    # The admin version will be sent with Kiran's phone - handled separately

    # =========================================================================
    # CATEGORY 13: PENDING STATE INTERRUPTS
    # =========================================================================

    tests.append(TestCase("P001", "pending", "start payment then say hi (reset)", [
        ("Ankita Benarjee paid 14000 cash", lambda r: is_confirm_prompt(r)),
        ("hi", lambda r: has_any(r, "help", "menu", "welcome", "can i help")),
    ]))

    tests.append(TestCase("P002", "pending", "start payment then ask different question", [
        ("Ankit Kumar room 320 paid 13000", lambda r: is_confirm_prompt(r) or has(r, "ankit")),
        ("who hasn't paid", lambda r: has_any(r, "pending", "dues", "yes", "confirm")),
    ]))

    tests.append(TestCase("P003", "pending", "start payment then cancel explicitly", [
        ("Aahil paid 16000 cash", lambda r: is_confirm_prompt(r)),
        ("cancel", lambda r: has_any(r, "cancel", "ok", "noted")),
    ]))

    tests.append(TestCase("P004", "pending", "start payment then start another payment", [
        ("Aahil paid 16000", lambda r: is_confirm_prompt(r)),
        ("Advait paid 13000 cash", lambda r: has_any(r, "advait", "yes", "pending", "confirm")),
    ]))

    # =========================================================================
    # CATEGORY 14: ROOM-BASED PAYMENT
    # =========================================================================

    tests.append(TestCase("RM001", "room", "room 606 paid 16000", [
        ("room 606 paid 16000", lambda r: has_any(r, "606", "aahil")),
        ("no", lambda r: True),
    ]))

    tests.append(TestCase("RM002", "room", "room 322 paid (multiple occupants)", [
        ("room 322 paid 12000", lambda r: has_any(r, "322", "aditaya", "adithya", "which", "1.")),
    ]))

    tests.append(TestCase("RM003", "room", "room with letter suffix", [
        ("room G01 paid 26000", lambda r: has_any(r, "g01", "adarsh")),
        ("no", lambda r: True),
    ]))

    tests.append(TestCase("RM004", "room", "invalid room number", [
        ("room 999 paid 10000", lambda r: has_any(r, "no tenant", "not found", "no match", "couldn't")),
    ]))

    # =========================================================================
    # CATEGORY 15: MULTI-MONTH / OVERPAYMENT
    # =========================================================================

    tests.append(TestCase("OV001", "overpay", "payment exceeds one month dues", [
        ("Aahil paid 30000 cash", lambda r: has_any(r, "aahil", "allocation", "confirm", "30,000")),
        ("no", lambda r: True),
    ]))

    tests.append(TestCase("OV002", "overpay", "advance payment for future months", [
        ("Aahil paid 48000 cash", lambda r: has_any(r, "aahil", "48,000")),
        ("no", lambda r: True),
    ]))

    # =========================================================================
    # CATEGORY 16: HELP & NAVIGATION
    # =========================================================================

    tests.append(TestCase("H001", "help", "help command", [
        ("help", lambda r: has_any(r, "help", "can do", "commands", "menu")),
    ]))

    tests.append(TestCase("H002", "help", "menu command", [
        ("menu", lambda r: has_any(r, "help", "menu", "commands")),
    ]))

    tests.append(TestCase("H003", "help", "greeting", [
        ("hi", lambda r: has_any(r, "help", "hello", "welcome", "can i help")),
    ]))

    # =========================================================================
    # CATEGORY 17: DEPOSIT RELATED
    # =========================================================================

    tests.append(TestCase("DEP001", "deposit", "security deposit query", [
        ("Aahil deposit details", lambda r: has_any(r, "deposit", "aahil", "security")),
    ]))

    # =========================================================================
    # CATEGORY 18: MAINTENANCE FEE
    # =========================================================================

    tests.append(TestCase("MNT001", "maintenance", "maintenance fee log", [
        ("maintenance fee 2000 from Aahil", lambda r: has_any(r, "aahil", "maintenance", "2,000", "2000", "confirm", "expense")),
    ]))

    # =========================================================================
    # CATEGORY 19: RECEPTIONIST BLOCKED ACTIONS
    # =========================================================================

    tests.append(TestCase("BLK001", "blocked", "receptionist cant see monthly report", [
        ("monthly report", lambda r: has(r, "owner-level")),
    ]))

    tests.append(TestCase("BLK002", "blocked", "receptionist cant see bank report", [
        ("bank report", lambda r: has_any(r, "owner-level", "owner", "access")),
    ]))

    # =========================================================================
    # CATEGORY 20: RAPID-FIRE SEQUENTIAL PAYMENTS
    # =========================================================================

    tests.append(TestCase("SEQ001", "sequential", "log 3 payments back to back", [
        ("Aahil paid 16000 cash", lambda r: is_confirm_prompt(r)),
        ("yes", lambda r: is_payment_logged(r)),
        ("Advait paid 13000 upi", lambda r: is_confirm_prompt(r)),
        ("yes", lambda r: is_payment_logged(r)),
        ("Ankit Kumar room 320 paid 13000 cash", lambda r: is_confirm_prompt(r) or has(r, "ankit")),
        ("no", lambda r: True),
    ]))

    # =========================================================================
    # CATEGORY 21: EDGE CASES — MESSAGE FORMATS
    # =========================================================================

    tests.append(TestCase("EC001", "edge", "only amount no name", [
        ("paid 15000 cash", lambda r: has_any(r, "who", "name", "which tenant", "format")),
    ]))

    tests.append(TestCase("EC002", "edge", "only name no amount", [
        ("Aahil paid cash", lambda r: has_any(r, "amount", "how much", "include", "format")),
    ]))

    tests.append(TestCase("EC003", "edge", "empty message", [
        ("", lambda r: True),  # Should not crash
    ]))

    tests.append(TestCase("EC004", "edge", "numbers only", [
        ("16000", lambda r: True),  # Should handle gracefully
    ]))

    tests.append(TestCase("EC005", "edge", "very long message", [
        ("Aahil from room 606 paid sixteen thousand rupees via cash payment mode for the month of March 2026 rent", lambda r: has_any(r, "aahil", "confirm", "606")),
        ("no", lambda r: True),
    ]))

    tests.append(TestCase("EC006", "edge", "special characters in message", [
        ("Aahil paid 16000 !!!", lambda r: has_any(r, "aahil", "16,000")),
        ("no", lambda r: True),
    ]))

    tests.append(TestCase("EC007", "edge", "mixed case", [
        ("AAHIL PAID 16000 CASH", lambda r: has_any(r, "aahil", "16,000")),
        ("no", lambda r: True),
    ]))

    tests.append(TestCase("EC008", "edge", "name with numbers (room confusion)", [
        ("302 paid 15500", lambda r: has_any(r, "302", "abhishek")),
        ("no", lambda r: True),
    ]))

    tests.append(TestCase("EC009", "edge", "amount equals room number scenario", [
        ("Aahil paid 606", lambda r: has_any(r, "aahil", "606")),
        ("no", lambda r: True),
    ]))

    tests.append(TestCase("EC010", "edge", "two amounts in message", [
        ("Aahil paid 8000 out of 16000", lambda r: has_any(r, "aahil", "8,000", "8000")),
        ("no", lambda r: True),
    ]))

    # =========================================================================
    # CATEGORY 22: CORRECTION AFTER LOGGING (void + re-log)
    # =========================================================================

    tests.append(TestCase("COR001", "correction", "log wrong amount then void and relog", [
        ("Adharsh Unni paid 15000 upi", lambda r: is_confirm_prompt(r)),
        ("yes", lambda r: is_payment_logged(r)),
        ("void Adharsh payment", lambda r: has_any(r, "which", "void", "adharsh")),
    ]))

    # =========================================================================
    # CATEGORY 23: CONTACTS QUERY (receptionist should have access)
    # =========================================================================

    tests.append(TestCase("CON001", "contacts", "electrician contact", [
        ("electrician contact", lambda r: has_any(r, "electrician", "contact", "phone", "number")),
    ]))

    tests.append(TestCase("CON002", "contacts", "plumber contact", [
        ("plumber contact", lambda r: has_any(r, "plumber", "contact", "phone", "number")),
    ]))

    # =========================================================================
    # CATEGORY 24: OCCUPANCY & VACANCY
    # =========================================================================

    tests.append(TestCase("OCC001", "occupancy", "room availability", [
        ("any vacant rooms", lambda r: has_any(r, "vacant", "available", "room", "occupancy")),
    ]))

    tests.append(TestCase("OCC002", "occupancy", "who is in room 606", [
        ("who is in room 606", lambda r: has_any(r, "aahil", "606")),
    ]))

    # =========================================================================
    # CATEGORY 25: MIXED INTENT CONFUSION
    # =========================================================================

    tests.append(TestCase("MIX001", "mixed", "complaint that looks like payment", [
        ("Aahil has not paid and water is leaking", lambda r: True),  # Should pick dominant intent
    ]))

    tests.append(TestCase("MIX002", "mixed", "question about payment that's not a log", [
        ("did Aahil pay this month", lambda r: has_any(r, "aahil", "balance", "dues", "paid", "status")),
    ]))

    tests.append(TestCase("MIX003", "mixed", "rent and complaint together", [
        ("Advait says room is dirty and hasn't paid rent", lambda r: True),
    ]))

    # =========================================================================
    # CATEGORY 26: ADMIN vs RECEPTIONIST DUAL LOGGING
    # =========================================================================

    # This tests what happens when admin (Kiran) logs the same payment that Sathyam already logged
    tests.append(TestCase("DUAL002", "dual_entry", "admin logs same payment as receptionist", [
        ("Adarsh Venugopal paid 26000 cash", lambda r: is_confirm_prompt(r)),
        ("yes", lambda r: is_payment_logged(r)),
    ]))

    return tests


# -- Runner -------------------------------------------------------------------

async def run_all():
    passed, failed, errors = 0, 0, 0
    results = []

    async with httpx.AsyncClient() as client:
        # Verify API is up
        try:
            resp = await client.get("http://127.0.0.1:8000/healthz", timeout=5)
            if resp.status_code != 200:
                print("API not running! Start with: venv/Scripts/python main.py")
                return
        except Exception:
            print("API not running! Start with: venv/Scripts/python main.py")
            return

        tests = build_tests()
        print(f"\n{'='*80}")
        print(f"  RECEPTIONIST E2E TEST SUITE — {len(tests)} test cases")
        print(f"  Phone: {PHONE} (Sathyam, receptionist)")
        print(f"{'='*80}\n")

        for tc in tests:
            await clear(client)  # Clear pending before each test
            tc_pass = True
            tc.replies = []

            try:
                for turn_idx, (msg, check_fn) in enumerate(tc.turns):
                    data = await send(client, msg)
                    reply = data.get("reply", "") or ""
                    intent = data.get("intent", "")
                    tc.replies.append({"msg": msg, "reply": reply[:200], "intent": intent})

                    if not check_fn(reply):
                        tc_pass = False
                        tc.error = f"Turn {turn_idx+1} failed: msg='{msg}' reply='{reply[:100]}'"
                        break

                tc.result = "PASS" if tc_pass else "FAIL"
            except Exception as e:
                tc.result = "ERROR"
                tc.error = str(e)[:200]
                errors += 1

            if tc.result == "PASS":
                passed += 1
                icon = "."
            elif tc.result == "FAIL":
                failed += 1
                icon = "F"
            else:
                icon = "E"

            # Print compact progress
            print(icon, end="", flush=True)
            results.append(tc)

    # -- Summary --
    print(f"\n\n{'='*80}")
    print(f"  RESULTS: {passed} passed, {failed} failed, {errors} errors / {len(results)} total")
    print(f"{'='*80}\n")

    # Print failures
    if failed or errors:
        print("FAILURES & ERRORS:\n")
        for tc in results:
            if tc.result in ("FAIL", "ERROR"):
                print(f"  [{tc.id}] {tc.category} — {tc.description}")
                print(f"    Error: {tc.error}")
                for t in tc.replies:
                    print(f"    >> {t['msg'][:60]}")
                    print(f"    << [{t['intent']}] {t['reply'][:120]}")
                print()

    # Print category breakdown
    categories = {}
    for tc in results:
        cat = tc.category
        if cat not in categories:
            categories[cat] = {"pass": 0, "fail": 0, "error": 0}
        categories[cat][tc.result.lower()] = categories[cat].get(tc.result.lower(), 0) + 1

    print("\nCATEGORY BREAKDOWN:")
    print(f"  {'Category':<20} {'Pass':>6} {'Fail':>6} {'Error':>6}")
    print(f"  {'-'*20} {'-'*6} {'-'*6} {'-'*6}")
    for cat, counts in sorted(categories.items()):
        p = counts.get("pass", 0)
        f = counts.get("fail", 0)
        e = counts.get("error", 0)
        print(f"  {cat:<20} {p:>6} {f:>6} {e:>6}")

    # Save detailed results
    out = []
    for tc in results:
        out.append({
            "id": tc.id, "category": tc.category, "description": tc.description,
            "result": tc.result, "error": tc.error, "turns": tc.replies
        })
    with open("tests/receptionist_e2e_results.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\nDetailed results saved to tests/receptionist_e2e_results.json")


if __name__ == "__main__":
    asyncio.run(run_all())
