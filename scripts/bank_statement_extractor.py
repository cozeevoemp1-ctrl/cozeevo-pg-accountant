"""
Bank Statement PDF → Excel Extractor
Supports YES Bank and other Indian bank statements.

Fixes the ChatGPT version's row-skipping bug:
  - pdfplumber extract_table() merges multi-line description cells and drops
    amounts/dates for transactions 2+ on a page.
  - This script uses word-position extraction instead, grouping words by
    y-coordinate and assigning them to columns by x-coordinate.

Usage:
    python scripts/bank_statement_extractor.py                 # auto-picks PDF in CWD
    python scripts/bank_statement_extractor.py my_file.pdf     # explicit file
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pandas as pd
import pdfplumber

# ──────────────────────────────────────────────────────────────────────────────
# UPI / Description Parser (unchanged from original)
# ──────────────────────────────────────────────────────────────────────────────

UTR_PATTERN = re.compile(r"\b\d{10,16}\b")
UPI_PATTERN = re.compile(r"[a-zA-Z0-9.\-_]+@[a-zA-Z]+")

KEYWORDS: dict[str, list[str]] = {
    "salary":    ["salary"],
    "fuel":      ["diesel", "petrol", "fuel"],
    "food":      ["milk", "eggs", "restaurant", "food", "grocery", "groceries"],
    "shopping":  ["amazon", "flipkart", "myntra", "meesho"],
    "transport": ["uber", "ola", "rapido"],
    "utilities": ["electricity", "bescom", "bwssb", "gas", "lpg"],
    "banking":   ["neft", "rtgs", "imps", "cash withdrawal", "atm"],
}


def parse_description(text: str) -> dict:
    result = {
        "transaction_type": "",
        "utr": "",
        "payer_upi": "",
        "payee_upi": "",
        "context_keywords": "",
        "category": "other",
    }
    if not isinstance(text, str):
        return result

    lower = text.lower()

    if "upi" in lower:
        result["transaction_type"] = "UPI"
    elif "neft" in lower:
        result["transaction_type"] = "NEFT"
    elif "rtgs" in lower:
        result["transaction_type"] = "RTGS"
    elif "imps" in lower:
        result["transaction_type"] = "IMPS"
    elif "atm" in lower or "cash" in lower:
        result["transaction_type"] = "CASH"

    m = UTR_PATTERN.search(text)
    if m:
        result["utr"] = m.group()

    upis = UPI_PATTERN.findall(text)
    if upis:
        result["payer_upi"] = upis[0]
    if len(upis) >= 2:
        result["payee_upi"] = upis[1]

    found = []
    for cat, words in KEYWORDS.items():
        for word in words:
            if word in lower:
                found.append(word)
                result["category"] = cat
    result["context_keywords"] = ", ".join(found)

    return result


def clean_amount(value: str) -> float | str:
    if not value:
        return ""
    value = str(value).replace(",", "").strip()
    if re.match(r"^\d+(\.\d+)?$", value):
        return float(value)
    return ""


# ──────────────────────────────────────────────────────────────────────────────
# Core Extractor — word-position based (fixes the ChatGPT bug)
# ──────────────────────────────────────────────────────────────────────────────

# Regex that matches Indian bank date formats: 2026-03-10 / 10/03/2026 / 10-03-2026
DATE_RE = re.compile(r"\b(\d{2,4}[-/]\d{2}[-/]\d{2,4})\b")


def _words_to_row(words: list[dict], col_bounds: dict[str, tuple[float, float]]) -> dict[str, str]:
    """Map a list of words to named columns based on x-position."""
    buckets: dict[str, list[str]] = {col: [] for col in col_bounds}
    for w in words:
        cx = (w["x0"] + w["x1"]) / 2
        for col, (lo, hi) in col_bounds.items():
            if lo <= cx < hi:
                buckets[col].append(w["text"])
                break
    return {col: " ".join(v) for col, v in buckets.items()}


def _detect_col_bounds(header_words: list[dict], page_width: float) -> dict[str, tuple[float, float]] | None:
    """
    Detect column x-boundaries from header words.
    Returns a dict of column_name → (x_min, x_max) or None if header not found.
    """
    HEADER_KEYS = {
        "transaction_date": ["transaction", "txn", "trans"],
        "value_date":       ["value"],
        "description":      ["description", "particulars", "narration", "details"],
        "reference":        ["reference", "cheque", "chq", "instrument"],
        "withdrawal":       ["withdrawal", "debit", "dr"],
        "deposit":          ["deposit", "credit", "cr"],
        "balance":          ["balance", "running"],
    }

    # Find approximate x-centre of each column header
    found: dict[str, float] = {}
    for w in header_words:
        t = w["text"].lower()
        cx = (w["x0"] + w["x1"]) / 2
        for col, keys in HEADER_KEYS.items():
            if any(k in t for k in keys):
                # value_date must not match transaction_date
                if col == "value_date" and "transaction" in t:
                    continue
                # balance must come after deposit in x
                if col in found:
                    if col == "balance" and cx > found[col]:
                        found[col] = cx  # keep rightmost
                    continue
                found[col] = cx
                break

    required = {"transaction_date", "description", "balance"}
    if not required.issubset(found):
        return None

    # Build boundaries: midpoint between consecutive columns
    ordered = sorted(found.items(), key=lambda x: x[1])
    bounds: dict[str, tuple[float, float]] = {}
    for i, (col, cx) in enumerate(ordered):
        lo = ordered[i - 1][1] + (cx - ordered[i - 1][1]) / 2 if i > 0 else 0.0
        hi = cx + (ordered[i + 1][1] - cx) / 2 if i < len(ordered) - 1 else page_width
        bounds[col] = (lo, hi)

    return bounds


def extract_transactions(pdf_path: str | Path) -> pd.DataFrame:
    """
    Extract all transactions from an Indian bank statement PDF.
    Uses word-position grouping to avoid pdfplumber's merged-cell bug.
    """
    pdf_path = Path(pdf_path)
    all_rows: list[dict] = []

    with pdfplumber.open(pdf_path) as pdf:
        col_bounds: dict | None = None
        header_y_bottom: float = 0.0  # ignore words above this on each page

        for page_num, page in enumerate(pdf.pages):
            words = page.extract_words(
                keep_blank_chars=False,
                x_tolerance=3,
                y_tolerance=3,
            )
            if not words:
                continue

            page_width = float(page.width)

            # ── Step 1: find header row if not yet found ──────────────────────
            if col_bounds is None:
                # Scan for a row containing both "date" and "balance"
                by_y: dict[int, list[dict]] = {}
                for w in words:
                    yk = int(w["top"])
                    by_y.setdefault(yk, []).append(w)

                for yk in sorted(by_y):
                    row_text = " ".join(w["text"].lower() for w in by_y[yk])
                    if ("date" in row_text or "transaction" in row_text) and (
                        "balance" in row_text or "description" in row_text
                    ):
                        cb = _detect_col_bounds(by_y[yk], page_width)
                        if cb:
                            col_bounds = cb
                            header_y_bottom = max(w["bottom"] for w in by_y[yk]) + 5
                            break

                # Also check a two-line header (Transaction\nDate)
                if col_bounds is None:
                    combined: dict[int, list[dict]] = {}
                    for w in words:
                        yk = int(w["top"] / 20) * 20  # bucket into 20-px bands
                        combined.setdefault(yk, []).append(w)
                    for yk in sorted(combined):
                        row_text = " ".join(w["text"].lower() for w in combined[yk])
                        if "transaction" in row_text and "balance" in row_text:
                            cb = _detect_col_bounds(combined[yk], page_width)
                            if cb:
                                col_bounds = cb
                                header_y_bottom = max(w["bottom"] for w in combined[yk]) + 5
                                break

            if col_bounds is None:
                print(f"  [Page {page_num + 1}] Could not detect column layout — skipping")
                continue

            # ── Step 2: group words into visual rows by y-coordinate ──────────
            data_words = [w for w in words if w["top"] >= header_y_bottom]
            # On pages after the first, skip repeated column headers.
            # Only look in the first 60px of data area to avoid matching
            # header keywords that appear inside transaction descriptions.
            if page_num > 0:
                header_search_limit = header_y_bottom + 60
                skip_y = 0.0
                for w in data_words:
                    if w["top"] > header_search_limit:
                        break
                    t = w["text"].lower()
                    if t in ("transaction", "date", "description", "balance", "withdrawals", "deposits"):
                        skip_y = max(skip_y, w["bottom"] + 5)
                if skip_y:
                    data_words = [w for w in data_words if w["top"] >= skip_y]

            # Cluster words into rows using 3-pixel y-tolerance
            y_clusters: list[tuple[float, list[dict]]] = []
            for w in sorted(data_words, key=lambda x: x["top"]):
                placed = False
                for cluster_y, cluster_words in y_clusters:
                    if abs(w["top"] - cluster_y) <= 4:
                        cluster_words.append(w)
                        placed = True
                        break
                if not placed:
                    y_clusters.append((w["top"], [w]))

            # ── Step 3: build transactions from row clusters ──────────────────
            current_txn: dict | None = None

            for cluster_y, cluster_words in y_clusters:
                mapped = _words_to_row(cluster_words, col_bounds)

                txn_date_text = mapped.get("transaction_date", "")
                val_date_text = mapped.get("value_date", "")
                desc_text     = mapped.get("description", "")
                ref_text      = mapped.get("reference", "")
                wd_text       = mapped.get("withdrawal", "")
                dep_text      = mapped.get("deposit", "")
                bal_text      = mapped.get("balance", "")

                has_date   = bool(DATE_RE.search(txn_date_text))
                has_amount = bool(wd_text or dep_text or bal_text)

                if has_date:
                    # New transaction — save previous
                    if current_txn:
                        all_rows.append(current_txn)

                    wd  = clean_amount(wd_text)
                    dep = clean_amount(dep_text)
                    bal = clean_amount(bal_text)

                    # Fix column shift: if deposit empty but balance present & withdrawal empty
                    if dep == "" and bal != "" and wd == "":
                        dep = bal
                        bal = ""

                    current_txn = {
                        "Transaction Date": DATE_RE.search(txn_date_text).group(),
                        "Value Date":       DATE_RE.search(val_date_text).group() if DATE_RE.search(val_date_text) else DATE_RE.search(txn_date_text).group(),
                        "Description":      desc_text,
                        "Reference":        ref_text,
                        "Withdrawals":      wd,
                        "Deposits":         dep,
                        "Balance":          bal,
                    }

                elif has_amount and current_txn:
                    # Same y-group has amounts but no date →
                    # amounts belong to the current transaction if they are missing
                    wd  = clean_amount(wd_text)
                    dep = clean_amount(dep_text)
                    bal = clean_amount(bal_text)
                    if current_txn["Withdrawals"] == "" and wd != "":
                        current_txn["Withdrawals"] = wd
                    if current_txn["Deposits"] == "" and dep != "":
                        current_txn["Deposits"] = dep
                    if current_txn["Balance"] == "" and bal != "":
                        current_txn["Balance"] = bal
                    if desc_text:
                        current_txn["Description"] += " " + desc_text
                    if ref_text:
                        current_txn["Reference"] += " " + ref_text

                else:
                    # Continuation line — append description / reference text
                    if current_txn:
                        if desc_text:
                            current_txn["Description"] += " " + desc_text
                        if ref_text and ref_text not in current_txn["Reference"]:
                            current_txn["Reference"] += " " + ref_text

            # Flush last transaction on page
            if current_txn:
                all_rows.append(current_txn)
                current_txn = None

    # Clean up description whitespace
    df = pd.DataFrame(all_rows)
    if not df.empty:
        df["Description"] = df["Description"].str.strip()
        df["Reference"]   = df["Reference"].str.strip()

    return df


# ──────────────────────────────────────────────────────────────────────────────
# Enrich with UPI metadata
# ──────────────────────────────────────────────────────────────────────────────

def enrich_transactions(df: pd.DataFrame) -> pd.DataFrame:
    parsed_df = pd.DataFrame(df["Description"].apply(parse_description).tolist())
    return pd.concat([df, parsed_df], axis=1)


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def run_pipeline(pdf_path: str | None = None) -> None:
    if pdf_path:
        pdf_file = pdf_path
    else:
        pdf_files = [f for f in os.listdir(".") if f.lower().endswith(".pdf")]
        if not pdf_files:
            print("❌ No PDF found in current folder. Pass path as argument.")
            return
        pdf_file = pdf_files[0]

    print(f"Processing: {pdf_file}")

    df = extract_transactions(pdf_file)

    if df is None or df.empty:
        print("❌ Could not extract any transactions")
        return

    df = enrich_transactions(df)

    output_file = Path(pdf_file).stem + "_extracted.xlsx"
    df.to_excel(output_file, index=False)

    print("=" * 50)
    print("✅ Done")
    print(f"File  : {output_file}")
    print(f"Rows  : {len(df)}")
    if "Withdrawals" in df.columns:
        total_wd = df["Withdrawals"].apply(lambda x: x if isinstance(x, float) else 0).sum()
        total_dep = df["Deposits"].apply(lambda x: x if isinstance(x, float) else 0).sum()
        print(f"Total Withdrawals : ₹{total_wd:,.2f}")
        print(f"Total Deposits    : ₹{total_dep:,.2f}")
    print("=" * 50)


if __name__ == "__main__":
    pdf_arg = sys.argv[1] if len(sys.argv) > 1 else None
    run_pipeline(pdf_arg)
