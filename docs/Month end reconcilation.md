# UPI / Bank Statement Extraction & Reconciliation System Design

## Overview

This document describes the design of a system that:

1. Extracts transactions from **PDF/CSV statements**
2. Normalizes different formats into a **single schema**
3. Reconstructs rows from messy PDF layouts
4. Reconciles duplicate transactions across sources
5. Categorizes income and expenses
6. Produces analysis-ready datasets

The system supports statements exported from apps such as **Paytm**, **PhonePe**, **Google Pay**, and merchant gateways like **Razorpay** or **BharatPe**, along with bank statements.

---

# 1. Core Problem

UPI transactions often appear in multiple places:

Example:

* UPI app statement
* Bank statement
* Merchant gateway export

A single transaction can therefore appear **2–3 times**.

Goal:

* **Merge duplicates**
* **Keep one canonical transaction**
* **Use other sources for enrichment**

---

# 2. Source of Truth Strategy

### Primary Ledger

Bank statement

### Metadata Sources

UPI apps

### Merchant Sources

Payment gateways

Rule:

Bank transactions are the **financial truth**.
UPI apps provide **better descriptions and metadata**.

---

# 3. User Upload Flow

Users upload statements monthly.

Example:

Upload:

* HDFC bank statement
* PhonePe export
* Paytm export

System automatically:

* extracts transactions
* matches duplicates
* categorizes expenses
* generates reports

---

# 4. System Architecture

```
User Upload
    ↓
File Type Detection
    ↓
Raw Extraction (PDF/CSV)
    ↓
Transaction Reconstruction
    ↓
Column Mapping
    ↓
Normalization
    ↓
Matching Engine
    ↓
Deduplication
    ↓
Categorization
    ↓
Reports
```

---

# 5. Project Folder Structure

```
finance_parser/

config/
    column_mappings.yaml
    category_rules.yaml

extractors/
    pdf_extractor.py
    csv_extractor.py

reconstruction/
    transaction_builder.py

parsers/
    paytm_parser.py
    phonepe_parser.py
    bank_parser.py

normalization/
    normalize_schema.py

matching/
    transaction_matcher.py
    fingerprint.py

categorization/
    categorizer.py

output/
    excel_exporter.py

main.py
```

---

# 6. Canonical Master Schema

All transactions must map to this format.

```
transaction_id
date
time
datetime
amount
direction
merchant
description
category
payment_method
utr
order_id
payer_upi
payee_upi
bank_account
source_type
source_name
source_file
confidence_score
raw_text
```

Key metadata fields:

| Field            | Meaning                       |
| ---------------- | ----------------------------- |
| source_type      | bank / upi_app / gateway      |
| source_name      | Paytm / PhonePe / HDFC        |
| source_file      | original uploaded file        |
| raw_text         | extracted line before parsing |
| confidence_score | extraction quality            |

---

# 7. Column Mapping System

Different apps export different column names.

Example mapping config:

```
paytm:
  Date: date
  Time: time
  Amount: amount
  UPI Ref No.: utr
  Order ID: order_id
  Transaction Details: description

phonepe:
  Date: date
  Transaction Details: description
  Type: direction
  Amount: amount

gpay:
  Date: date
  Description: description
  UPI ID: payee_upi
  Amount: amount
  UTR: utr

razorpay:
  Created At: datetime
  Amount: amount
  Payment ID: transaction_id
  Order ID: order_id
```

Normalization renames columns to canonical schema.

---

# 8. PDF Extraction Strategy

PDF tables are unreliable.

Instead:

* Extract **all lines**
* Reconstruct transactions

Example:

```
12 Mar 2025 Grocery Store
UPI: store@okicici
UTR 123456
₹200
```

Algorithm groups these lines into a single transaction.

---

# 9. Transaction Reconstruction

Steps:

1. Extract text lines
2. Detect transaction start
3. Group lines until next transaction

Transaction start patterns:

```
DATE
DATE + TIME
```

Example regex:

```
\d{1,2}[-/ ](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|\d{1,2})[-/ ]\d{2,4}
```

---

# 10. Field Extraction

Regex patterns:

Amount:

```
₹?\s?([\d,]+\.\d+|[\d,]+)
```

UPI ID:

```
[a-zA-Z0-9.\-_]+@[a-zA-Z]+
```

UTR:

```
\d{10,16}
```

---

# 11. Transaction Fingerprint

Used for deduplication.

Primary fingerprint:

```
hash(date + amount + utr)
```

Fallback fingerprint:

```
hash(date + amount + merchant)
```

---

# 12. Matching Engine

Matching priority:

1. UTR match
2. fingerprint match
3. amount + time window
4. fuzzy merchant match

Merge rule:

Bank transaction = canonical
UPI transaction = metadata

---

# 13. Deduplication Example

Bank row:

| date   | amount | description |
| ------ | ------ | ----------- |
| 12 Mar | -500   | UPI-XYZ     |

UPI row:

| date   | amount | merchant |
| ------ | ------ | -------- |
| 12 Mar | 500    | Swiggy   |

Merged result:

| date   | amount | merchant |
| ------ | ------ | -------- |
| 12 Mar | -500   | Swiggy   |

---

# 14. Categorization

Rules stored in config file.

Example:

```
food:
  - swiggy
  - zomato
  - dominos

shopping:
  - amazon
  - flipkart

transport:
  - ola
  - uber
```

Matching is keyword-based.

---

# 15. Output Reports

Generated datasets:

### Transactions

All normalized transactions.

### Reconciled

Merged bank + UPI transactions.

### Unmatched

Transactions not reconciled.

### Category Summary

| Category | Amount |

### Income vs Expense

| Type | Amount |

---

# 16. Excel Output

Workbook sheets:

```
Transactions
Reconciled
Unmatched
Category Summary
Income vs Expense
```

---

# 17. Recommended Libraries

```
pdfplumber
pandas
rapidfuzz
regex
dateparser
openpyxl
```

---

# 18. Advanced Improvement (Layout-Based Parsing)

Many fintech systems parse PDFs using **text coordinates** instead of raw text order.

Benefits:

* prevents row merge errors
* handles multi-line cells
* improves extraction accuracy

Tools:

* pdfplumber bounding boxes
* layout clustering
* coordinate grouping

Accuracy improves from ~70% → ~98%.

---

# 19. Key Design Principles

1. Bank statements are the **source of truth**
2. UPI apps are **metadata enrichment**
3. All formats normalize into **one schema**
4. Matching uses **UTR + fingerprints**
5. Always store **raw text and source metadata**

---

# 20. Final Output Goal

Provide users with:

* Monthly expense summary
* Income vs expense analysis
* Category breakdown
* Duplicate detection
* Clean transaction ledger

---
