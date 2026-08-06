AI_FINANCE_RECONCILIATION_SYSTEM_SPEC.md

AI_FINANCE_RECONCILIATION_SYSTEM_SPEC.md
1. System Name

Unified Financial Transaction Extraction & Reconciliation Engine

2. Purpose

Build a scalable system capable of:

Extracting transactions from bank statements, UPI apps, and payment gateways

Normalizing them into one canonical schema

Detecting duplicate transactions

Reconciling multiple data sources

Enriching transactions with merchant intelligence

Categorizing spending

Producing analytics-ready datasets

The system must operate in:

Local mode (single user personal finance)

Server mode (multi-user SaaS)

Batch mode (large dataset processing)

3. Supported Input Sources
Bank Statements

Supported formats:

PDF
CSV
XLS
XLSX

Banks:

HDFC
ICICI
SBI
Axis
Kotak
Yes Bank
UPI Applications
PhonePe
Google Pay
Paytm
Amazon Pay
Wallets
Paytm Wallet
Amazon Pay Wallet
Mobikwik
Payment Gateways
Razorpay
BharatPe
Stripe
Cashfree
4. High Level Architecture
File Upload / API Input
        │
        ▼
File Detection Engine
        │
        ▼
Format Identification
        │
        ▼
Parser Selection
        │
        ▼
Extraction Layer
        │
        ▼
Transaction Reconstruction
        │
        ▼
Column Mapping Engine
        │
        ▼
Canonical Normalization
        │
        ▼
Fingerprint Generator
        │
        ▼
Matching Engine
        │
        ▼
Deduplication Engine
        │
        ▼
Merchant Normalization
        │
        ▼
Categorization Engine
        │
        ▼
Analytics Engine
        │
        ▼
Output Data Tables
5. Canonical Transaction Schema

Every transaction must map to this schema.

transaction_id
transaction_date
transaction_time
transaction_datetime
amount
currency
direction
merchant_name
merchant_raw
description
category
subcategory
payment_method
payment_channel
utr
order_id
gateway_reference
payer_name
payer_upi
payee_name
payee_upi
bank_account
bank_name
card_last4
source_type
source_name
source_file
source_row
confidence_score
raw_text
fingerprint
created_at
updated_at
6. Source Types
bank
upi_app
wallet
payment_gateway
merchant_export
7. Payment Methods
UPI
CARD
NETBANKING
BANK_TRANSFER
WALLET
CASH
8. File Detection Engine

Determine file type automatically.

Detection signals:

file extension
mime type
header names
column count
text patterns
merchant keywords
9. Parser Architecture

Each parser must implement:

parse(file) -> List[Transaction]
Parser Registry
bank_hdfc_parser
bank_icici_parser
bank_sbi_parser
upi_phonepe_parser
upi_gpay_parser
upi_paytm_parser
gateway_razorpay_parser
gateway_bharatpe_parser
10. Column Mapping Engine

Mappings stored in config.

Example:

phonepe:

  Date: transaction_date
  Transaction Details: description
  Type: direction
  Amount: amount

paytm:

  Date: transaction_date
  Time: transaction_time
  UPI Ref No.: utr
  Amount: amount

The engine performs:

column rename
datatype conversion
value transformation
11. PDF Parsing Engine

Preferred strategy:

Layout-aware parsing

Use coordinate extraction.

Algorithm:

extract characters with positions
group by y-coordinate
cluster rows
cluster columns
reconstruct table

Libraries recommended:

pdfplumber
pdfminer

Fallback strategy:

raw text extraction
regex grouping
12. Transaction Reconstruction

PDF rows may be fragmented.

Example:

12 Mar 2025 Grocery Store
UPI: store@okicici
UTR 123456
₹200

Algorithm:

detect transaction start
group lines
extract fields
create transaction object
13. Field Extraction
Amount Regex
₹?\s?([\d,]+\.\d+|[\d,]+)
UPI ID
[a-zA-Z0-9.\-_]+@[a-zA-Z]+
UTR
\d{10,16}
Card Last 4
XXXX\d{4}
14. Fingerprint Engine

Purpose: identify identical transactions.

Primary fingerprint:

hash(date + amount + utr)

Fallback fingerprint:

hash(date + amount + merchant)

Advanced fingerprint:

hash(date + amount + normalized_merchant + direction)
15. Matching Engine

Matching priority:

1 UTR match
2 gateway reference
3 fingerprint match
4 amount + time window
5 fuzzy merchant similarity

Fuzzy matching library:

rapidfuzz

Threshold:

similarity > 85
16. Deduplication Rules

If duplicates detected:

bank transaction becomes canonical
upi transaction enriches metadata
gateway transaction enriches metadata

Merged transaction retains:

bank amount
bank date
upi merchant name
gateway references
17. Merchant Normalization

Example merchant variations:

swiggy instamart
swiggy online
swiggy bangalore

Normalized merchant:

SWIGGY

Normalization pipeline:

lowercase
remove numbers
remove stopwords
dictionary lookup
fuzzy matching
18. Categorization Engine

Categories stored in config.

Example:

food:
  swiggy
  zomato

shopping:
  amazon
  flipkart

transport:
  uber
  ola

Matching strategy:

merchant keyword
description keyword
fallback ML classifier
19. Output Data Tables
transactions_raw

Stores original extracted rows.

transactions_normalized

Transactions mapped to canonical schema.

transactions_reconciled

Final merged transactions.

merchant_dictionary

Normalized merchants.

category_summary
category
total_spend
transaction_count
income_vs_expense
type
total_amount
20. API Layer (Optional)

Recommended framework:

FastAPI

Example endpoints:

POST /upload_statement
GET /transactions
GET /summary
GET /categories
21. Processing Pipeline
upload service
processing queue
worker nodes
database storage
analytics engine

Recommended stack:

Python
FastAPI
PostgreSQL
Redis
Celery
DuckDB
S3
22. Performance Goals

Target performance:

PDF parsing accuracy 98%
Transaction matching accuracy 99%
Duplicate removal 100%
23. Security Considerations

Sensitive fields:

bank_account
card numbers
upi ids

Security requirements:

encrypt stored data
mask sensitive fields
role based access
audit logs
24. Testing Strategy

Test coverage must include:

parser tests
matching tests
deduplication tests
schema validation
edge cases
25. Extensibility Design

New banks must be added by:

creating parser
adding column mapping
registering parser

No core code changes required.

26. AI Implementation Instructions

When generating code:

Use Python

Implement modular architecture

Build pluggable parsers

Include unit tests

Use type hints

Ensure high performance

Follow clean architecture principles

27. Final Output Goal

Provide users with:

clean financial ledger
monthly expense summary
category breakdown
income vs expense
duplicate detection
merchant insights

✅ This AI-ready specification is designed so a coding AI can generate:

parser modules

matching engine

reconciliation engine

API layer

database schema


if neededed also go ahead with specific MD files such as 

README.md
ARCHITECTURE.md
SCHEMA.md
PARSERS.md
MATCHING_ENGINE.md
PDF_EXTRACTION.md
MERCHANT_NORMALIZATION.md
CATEGORIZATION.md
PIPELINE.md
API_SPEC.md
CONFIG_FORMATS.md

analytics queries

from one document.