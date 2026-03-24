# -*- coding: utf-8 -*-
"""
Cleanup script for Google Sheet "History" tab.
Separates mixed text+number columns, moves text to Comments column.
"""
import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import re
import sys
import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = "1T4YE7RK2eIZRg330kaOaNb5-8o8kJbxpDzK_7MfoyiA"
CREDS_FILE = "credentials/gsheets_service_account.json"

# Column indices (0-indexed)
COL_BOOKING = 5
COL_SECURITY_DEPOSIT = 6
COL_DAY_WISE_RENT = 8
COL_COMMENTS = 14
COL_MARCH_BALANCE = 30
COL_MARCH_CASH = 31
COL_MARCH_UPI = 32
COL_REFUND_STATUS = 38
COL_REFUND_AMOUNT = 39

# Human-readable names for comments
COL_NAMES = {
    COL_BOOKING: "Booking",
    COL_SECURITY_DEPOSIT: "Security Deposit",
    COL_DAY_WISE_RENT: "Day wise Rent",
    COL_MARCH_BALANCE: "March Balance",
    COL_MARCH_CASH: "March Cash",
    COL_MARCH_UPI: "March UPI",
    COL_REFUND_AMOUNT: "Refund Amount",
}

# Rows to skip (0-indexed data rows, so row index 264-270 = sheet rows 266-272 after header)
# The instruction says "DO NOT touch rows 265-271" — assuming these are 1-indexed sheet rows
# Sheet row 1 = header, data starts row 2 = index 0
# "rows 265-271" in sheet = data indices 263-269
SKIP_ROW_INDICES = set(range(263, 270))  # 0-indexed data rows


def extract_number(text):
    """
    Extract a numeric value from a text string.
    Returns (number, is_pure_number) where is_pure_number means the original was just a number.
    """
    s = str(text).strip()
    if s == "" or s.lower() == "none":
        return None, True  # empty = no change needed

    # Already a pure number?
    try:
        val = float(s)
        return val, True
    except ValueError:
        pass

    # Try int directly
    try:
        val = int(s)
        return val, True
    except ValueError:
        pass

    return None, False  # contains text


def parse_mixed_value(raw, col_idx):
    """
    Parse a mixed text+number cell.
    Returns (numeric_value, comment_text_or_None).
    numeric_value: int/float to put back, or 0 if no number
    comment_text: text to append to Comments, or None if no comment needed
    """
    s = str(raw).strip()

    if s == "" or s.lower() == "none":
        return None, None  # no change

    # Try pure number first
    try:
        return int(s), None
    except ValueError:
        pass
    try:
        return float(s), None
    except ValueError:
        pass

    col_name = COL_NAMES.get(col_idx, f"Col{col_idx}")

    # ---- Special cases by column ----

    if col_idx == COL_MARCH_CASH:
        sl = s.lower()
        if "hitachi" in sl:
            return 0, f"[March Cash: Hitachi - pending ₹23,850]"
        if "paid in feb" in sl:
            return 0, f"[March Cash: paid in feb]"
        # "13000 Received by Chandra /5000 Lakshmi gorjala" — has amounts, sum them
        if "received by chandra" in sl:
            nums = re.findall(r'\d+', s.replace(",", ""))
            if nums and len(nums) >= 2:
                total = sum(int(n) for n in nums)
                return total, f"[March Cash: {s}]"
            elif nums:
                return int(nums[0]), f"[March Cash: {s}]"
            return 0, f"[March Cash: Received by Chandra anna - amount = monthly rent]"
        # generic with numbers
        nums = re.findall(r'\d+(?:,\d+)*(?:\.\d+)?', s.replace(",", ""))
        if nums:
            total = sum(int(n) for n in nums)
            return total, f"[March Cash: {s}]"
        return 0, f"[March Cash: {s}]"

    if col_idx == COL_MARCH_UPI:
        sl = s.lower()
        if "paid in feb" in sl:
            return 0, f"[March UPI: paid in feb]"
        nums = re.findall(r'\d+(?:,\d+)*(?:\.\d+)?', s.replace(",", ""))
        if nums:
            return int(nums[0]), f"[March UPI: {s}]"
        return 0, f"[March UPI: {s}]"

    if col_idx == COL_MARCH_BALANCE:
        sl = s.lower()
        # Exit notes → 0
        if re.search(r'exit', sl):
            return 0, f"[March Balance: {s}]"
        if "received by chandra" in sl:
            return 0, f"[March Balance: Received by Chandra anna - amount = monthly rent]"
        # "deposit 6750 on march 1st"
        if "deposit" in sl:
            nums = re.findall(r'\d+(?:,\d+)*(?:\.\d+)?', s.replace(",", ""))
            if nums:
                return int(nums[0]), f"[March Balance: {s}]"
            return 0, f"[March Balance: {s}]"
        # Calculation like "516*16=8256" → take final result after last "="
        eq_match = re.findall(r'=\s*(-?\d+)', s)
        if eq_match:
            return int(eq_match[-1]), f"[March Balance: {s}]"
        # "5500 on april 1st" → first number
        nums = re.findall(r'\d+', s.replace(",", ""))
        if nums:
            return int(nums[0]), f"[March Balance: {s}]"
        return 0, f"[March Balance: {s}]"

    if col_idx == COL_SECURITY_DEPOSIT:
        if s in ("-", "Nil", "nil", "NIL"):
            return 0, None
        if s.lower() == "eqaro":
            return None, None  # keep as-is per instructions
        nums = re.findall(r'\d+', s.replace(",", ""))
        if nums:
            return int(nums[0]), f"[Security Deposit: {s}]"
        return 0, f"[Security Deposit: {s}]"

    if col_idx == COL_BOOKING:
        sl = s.lower()
        text_keywords = ["hitachi", "total deposit", "maintence", "maintenance",
                         "in thor bank", "in hulk bank", "cash", "chandra collection"]
        if any(k in sl for k in text_keywords):
            nums = re.findall(r'\d+', s.replace(",", ""))
            num_val = int(nums[0]) if nums else 0
            return num_val, f"[Booking: {s}]"
        # Try to extract number anyway
        nums = re.findall(r'\d+', s.replace(",", ""))
        if nums:
            return int(nums[0]), f"[Booking: {s}]"
        return 0, f"[Booking: {s}]"

    if col_idx == COL_DAY_WISE_RENT:
        # "3102/2400" → take first number (3102)
        # "903*10=9030-28000=18970" → take final result (18970)
        # "28000-6000=22000" → take final result (22000)
        # Find last "=NUMBER" pattern
        eq_match = re.findall(r'=\s*(-?\d+)', s)
        if eq_match:
            return int(eq_match[-1]), f"[Day wise Rent: {s}]"
        # slash division: take first part
        slash_match = re.match(r'(\d+)\s*/\s*(\d+)', s)
        if slash_match:
            return int(slash_match.group(1)), f"[Day wise Rent: {s}]"
        nums = re.findall(r'\d+', s.replace(",", ""))
        if nums:
            return int(nums[0]), f"[Day wise Rent: {s}]"
        return 0, f"[Day wise Rent: {s}]"

    if col_idx == COL_REFUND_AMOUNT:
        sl = s.lower()
        if "no deposit" in sl or "not clear" in sl or "retuened" in sl or "returned" in sl:
            nums = re.findall(r'\d+', s.replace(",", ""))
            if nums:
                return int(nums[0]), f"[Refund Amount: {s}]"
            return 0, f"[Refund Amount: {s}]"
        if "5000 upi" in sl:
            return 5000, f"[Refund Amount: {s}]"
        # "Return 110" / "Return 100"
        ret_match = re.search(r'return\s+(\d+)', sl)
        if ret_match:
            return int(ret_match.group(1)), f"[Refund Amount: {s}]"
        nums = re.findall(r'\d+', s.replace(",", ""))
        if nums:
            return int(nums[0]), f"[Refund Amount: {s}]"
        return 0, f"[Refund Amount: {s}]"

    # Generic fallback
    nums = re.findall(r'\d+', s.replace(",", ""))
    if nums:
        return int(nums[0]), f"[{col_name}: {s}]"
    return 0, f"[{col_name}: {s}]"


def append_comment(existing, new_comment):
    ex = str(existing).strip() if existing and str(existing).strip() not in ("", "None") else ""
    if ex:
        return ex + " | " + new_comment
    return new_comment


def main():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
    ]
    creds = Credentials.from_service_account_file(CREDS_FILE, scopes=scopes)
    gc = gspread.authorize(creds)

    print("Opening spreadsheet...")
    sh = gc.open_by_key(SPREADSHEET_ID)
    ws = sh.worksheet("History")

    print("Reading all data...")
    all_data = ws.get_all_values()
    header = all_data[0]
    data_rows = all_data[1:]  # 0-indexed list, row index 0 = sheet row 2

    print(f"Total data rows: {len(data_rows)}")
    print(f"Columns in header: {len(header)}")
    print()

    # Print header names for the relevant columns
    for ci in [COL_BOOKING, COL_SECURITY_DEPOSIT, COL_DAY_WISE_RENT, COL_COMMENTS,
               COL_MARCH_BALANCE, COL_MARCH_CASH, COL_MARCH_UPI,
               COL_REFUND_STATUS, COL_REFUND_AMOUNT]:
        name = header[ci] if ci < len(header) else f"[col {ci}]"
        print(f"  Col {ci}: {name}")
    print()

    # Columns to process for mixed text/number cleanup
    mixed_cols = [
        COL_BOOKING, COL_SECURITY_DEPOSIT, COL_DAY_WISE_RENT,
        COL_MARCH_BALANCE, COL_MARCH_CASH, COL_MARCH_UPI, COL_REFUND_AMOUNT
    ]

    # Track all changes: {(row_idx, col_idx): new_value}
    changes = {}  # (row_idx_0based, col_0based) -> new_val
    change_log = []  # human readable

    for row_idx, row in enumerate(data_rows):
        if row_idx in SKIP_ROW_INDICES:
            continue

        # Ensure row is long enough
        while len(row) <= max(COL_REFUND_AMOUNT, COL_COMMENTS, COL_REFUND_STATUS):
            row.append("")

        # Process mixed columns
        for col_idx in mixed_cols:
            raw = row[col_idx] if col_idx < len(row) else ""
            if raw == "" or str(raw).strip() in ("", "None"):
                continue

            # Try pure number first
            s = str(raw).strip()
            try:
                int(s)
                continue  # pure int, no change needed
            except ValueError:
                pass
            try:
                float(s)
                continue  # pure float, no change needed
            except ValueError:
                pass

            # Security deposit: keep "Eqaro" as-is
            if col_idx == COL_SECURITY_DEPOSIT and s.lower() == "eqaro":
                continue

            # It's mixed — process it
            num_val, comment = parse_mixed_value(raw, col_idx)

            if num_val is None and comment is None:
                continue  # no change (e.g. Eqaro, empty)

            sheet_row = row_idx + 2  # 1-indexed, +1 for header
            col_name = COL_NAMES.get(col_idx, f"Col{col_idx}")

            if num_val is not None:
                changes[(row_idx, col_idx)] = num_val
                change_log.append(f"  Row {sheet_row} | {col_name}: '{raw}' → {num_val}")

            if comment:
                existing_comment = row[COL_COMMENTS] if COL_COMMENTS < len(row) else ""
                new_comment = append_comment(existing_comment, comment)
                changes[(row_idx, COL_COMMENTS)] = new_comment
                change_log.append(f"  Row {sheet_row} | Comments appended: {comment}")
                # Update in-memory so subsequent appends stack
                while len(row) <= COL_COMMENTS:
                    row.append("")
                row[COL_COMMENTS] = new_comment

        # ---- Fix Refund Status (col 38) ----
        refund_status_raw = row[COL_REFUND_STATUS] if COL_REFUND_STATUS < len(row) else ""
        refund_amount_raw = row[COL_REFUND_AMOUNT] if COL_REFUND_AMOUNT < len(row) else ""
        sheet_row = row_idx + 2

        if refund_status_raw:
            s_rs = str(refund_status_raw).strip()
            # "paid" → "Paid"
            if s_rs.lower() == "paid" and s_rs != "Paid":
                changes[(row_idx, COL_REFUND_STATUS)] = "Paid"
                change_log.append(f"  Row {sheet_row} | Refund Status: '{s_rs}' → 'Paid'")

            # Numeric value in Refund Status → move to Refund Amount, set status to "Paid"
            try:
                numeric_status = int(s_rs)
                # Move to Refund Amount
                existing_amount = row[COL_REFUND_AMOUNT] if COL_REFUND_AMOUNT < len(row) else ""
                if existing_amount == "" or existing_amount is None:
                    changes[(row_idx, COL_REFUND_AMOUNT)] = numeric_status
                else:
                    changes[(row_idx, COL_REFUND_AMOUNT)] = existing_amount  # keep existing
                changes[(row_idx, COL_REFUND_STATUS)] = "Paid"
                change_log.append(
                    f"  Row {sheet_row} | Refund Status was number {numeric_status} → "
                    f"moved to Refund Amount, Status set to 'Paid'"
                )
            except ValueError:
                pass

    print(f"Total changes to apply: {len(changes)}")
    print()
    print("=== CHANGE SUMMARY ===")
    for line in change_log:
        print(line)
    print()

    if not change_log:
        print("No changes needed.")
        return

    # Ask for confirmation
    confirm = input("Apply these changes? [y/N]: ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        return

    # Build batch update requests
    # gspread batch_update uses A1 notation ranges
    # We'll build a list of ValueRange objects
    print("Building batch update...")

    batch_data = []
    for (row_idx, col_idx), new_val in changes.items():
        sheet_row = row_idx + 2  # 1-indexed + header
        # Convert col_idx to A1 column letter
        col_letter = col_index_to_letter(col_idx)
        cell_range = f"{col_letter}{sheet_row}"
        batch_data.append({
            "range": cell_range,
            "values": [[new_val]]
        })

    # Split into chunks of 500 to avoid API limits
    chunk_size = 500
    total = len(batch_data)
    for i in range(0, total, chunk_size):
        chunk = batch_data[i:i + chunk_size]
        ws.batch_update(chunk, value_input_option="USER_ENTERED")
        print(f"  Applied chunk {i//chunk_size + 1}/{(total + chunk_size - 1)//chunk_size} ({len(chunk)} cells)")

    print()
    print(f"Done! Applied {len(changes)} cell updates.")


def col_index_to_letter(idx):
    """Convert 0-indexed column number to A1 column letter(s)."""
    result = ""
    idx += 1  # 1-indexed
    while idx > 0:
        idx, remainder = divmod(idx - 1, 26)
        result = chr(65 + remainder) + result
    return result


if __name__ == "__main__":
    main()
