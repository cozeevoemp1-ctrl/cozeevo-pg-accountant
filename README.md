# PG Accountant — AI-Powered Bookkeeping for PG Businesses

A production-ready, locally-runnable accounting system for PG (paying guest) businesses.
Handles income, expenses, rent tracking, and salary management with WhatsApp integration.

> **Clone-friendly:** Each PG owner gets their own isolated instance with their own API keys, data, and LLM tokens.

---

## Features

- **Multi-source ingestion** — PhonePe, Paytm, HDFC/SBI/ICICI bank statements, UPI, cash
- **Smart deduplication** — SHA-256 hash prevents double-counting across imports
- **97% rule-based classification** — fast, free, deterministic
- **~3% AI classification** — Claude API for unknown merchants only
- **WhatsApp interface** — query summaries, export reports, check rent status
- **Interactive approval** — new tenants/vendors need your confirmation before being added
- **Auto-reports** — text, CSV, Excel, and 24h HTML dashboards
- **n8n automation** — file ingestion, daily reconciliation, WhatsApp replies
- **VS Code friendly** — all prompts work in the integrated terminal

---

## Quick Start

### Prerequisites
- Python 3.11+
- VS Code (recommended)
- n8n (Docker or cloud)
- Twilio account (for WhatsApp)

### Installation

```bash
# 1. Clone / copy this project
git clone <repo_url> my-pg-accountant
cd my-pg-accountant

# 2. Create virtual environment
python -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.template .env
# Edit .env with your API keys (see Configuration section)

# 5. Start the API server
python -m cli.start_api

# API docs available at: http://localhost:8000/docs
```

---

## Configuration

Edit `.env` with your settings:

```env
# Your identity
PG_OWNER_NAME="Your Name"
PG_BUSINESS_NAME="My PG House"

# Claude API (for ~3% AI classification)
ANTHROPIC_API_KEY="sk-ant-..."

# WhatsApp via Twilio
TWILIO_ACCOUNT_SID="AC..."
TWILIO_AUTH_TOKEN="..."
TWILIO_WHATSAPP_FROM="whatsapp:+14155238886"

# n8n automation
N8N_BASE_URL="http://localhost:5678"
N8N_API_KEY="..."
```

---

## CLI Commands

### Ingest a File
```bash
# Auto-detect source (PhonePe/Paytm/Bank/UPI)
python -m cli.ingest_file data/raw/phonepe_march_2025.csv

# Preview without saving
python -m cli.ingest_file data/raw/statement.pdf --dry-run

# Skip interactive approval prompts
python -m cli.ingest_file data/raw/file.csv --no-interactive
```

### Run Reconciliation
```bash
# Monthly (current month)
python -m cli.run_reconciliation --period monthly

# Specific month
python -m cli.run_reconciliation --period monthly --year 2025 --month 3

# Daily / Weekly
python -m cli.run_reconciliation --period daily
python -m cli.run_reconciliation --period weekly
```

### Generate Reports
```bash
# Text summary in terminal
python -m cli.generate_report --format text --period monthly

# CSV export
python -m cli.generate_report --format csv --period monthly

# Excel with charts
python -m cli.generate_report --format excel --period monthly --open

# HTML Dashboard (opens in browser)
python -m cli.generate_report --format dashboard --open
```

### Configure n8n Workflows (Interactive)
```bash
python -m cli.configure_workflow
# Walks through: n8n connection → Twilio setup → generate JSONs → deploy
```

### Start API Server
```bash
python -m cli.start_api              # production
python -m cli.start_api --reload     # development with hot-reload
python -m cli.start_api --port 9000  # custom port
```

---

## File Ingestion

Drop any supported file in `data/raw/` and either:
- Run `python -m cli.ingest_file data/raw/<file>`, or
- Let the n8n 15-min scheduled workflow pick it up automatically

### Supported Formats

| Source | CSV | PDF |
|---|---|---|
| PhonePe | ✓ | ✓ |
| Paytm | ✓ | ✓ |
| HDFC Bank | ✓ | ✓ |
| SBI Bank | ✓ | ✓ |
| ICICI Bank | ✓ | ✓ |
| Axis Bank | ✓ | ✓ |
| Generic UPI | ✓ | ✓ |
| Google Pay | ✓ | - |
| Any CSV | ✓ | - |

---

## WhatsApp Commands

Send these messages to your WhatsApp number:

```
show march summary
show this month summary
export expenses csv
export excel
show dashboard
show rent collected this month
rent pending march
salary status
help
approve 42        (approve a pending entity by ID)
reject 42         (reject a pending entity by ID)
```

Send a PDF or CSV file directly — it will be ingested automatically.

---

## Project Structure

```
.
├── src/
│   ├── agents/          LangGraph router, intent detector, master data agent
│   ├── database/        SQLAlchemy models, DB manager, schema
│   ├── parsers/         PhonePe, Paytm, bank, UPI, PDF, CSV parsers
│   ├── rules/           Categorization, deduplication, merchant normalization
│   ├── llm_gateway/     Claude API client and prompt templates
│   ├── reports/         Reconciliation engine, report generator, Excel exporter
│   ├── dashboard/       HTML dashboard generator + 24h cleanup
│   ├── whatsapp/        Webhook handler + response formatter
│   └── n8n_hooks/       Workflow generator + n8nMCP REST client
├── cli/                 Click CLI commands
├── data/
│   ├── raw/             Drop input files here
│   ├── processed/       Files moved here after ingestion
│   └── exports/         CSV/Excel reports
├── dashboards/          HTML dashboards (auto-deleted after 24h)
├── workflows/n8n/       Generated n8n workflow JSON files
├── tests/               Unit tests
├── main.py              FastAPI application
├── setup.py             Package entry points
├── docker-compose.yml   Docker setup (API + n8n + Redis)
├── .env.template        Configuration template
├── BRAIN.md             Architecture memory (auto-updated)
├── SYSTEM_ARCHITECTURE.md   Technical diagrams
└── CHANGELOG.md         Version history
```

---

## Docker Deployment

```bash
# Copy and configure environment
cp .env.template .env
# Edit .env ...

# Start all services
docker-compose up -d

# Access:
# API:   http://localhost:8000
# n8n:   http://localhost:5678  (admin/pgaccountant2024)
# Docs:  http://localhost:8000/docs
```

---

## Master Data Management

When a new tenant, vendor, or employee appears in a transaction:
1. System detects they don't exist in master data
2. Queued in `pending_entities` table
3. VS Code terminal shows an approval prompt (or WhatsApp if from mobile)
4. You approve/reject with details
5. Only then is the entity added to the master table

**Approve via terminal:**
```
============================================================
  New CUSTOMER detected in transaction:
  Date:   2025-03-15
  Amount: ₹8000
  Desc:   UPI payment from Rahul Sharma
  Party:  Rahul Sharma
============================================================
Add 'Rahul Sharma' as a new customer? [Y/n]: Y
Name: Rahul Sharma
Phone (optional): 9876543210
UPI ID (optional): rahul@ybl
Room number (optional): 101
Monthly rent amount (optional): 8000
```

**Approve via WhatsApp:**
```
You: approve 42
Bot: ✅ Approved: Rahul Sharma
```

---

## Running Tests

```bash
pytest tests/ -v
pytest tests/test_deduplication.py
pytest tests/test_parsers.py
```

---

## Contributing / Cloning

This is a **template** — fork it and make it yours:
1. Replace `PG_OWNER_NAME` and `PG_BUSINESS_NAME` in `.env`
2. Add your own API keys
3. Drop your first statement in `data/raw/` and run `ingest-file`
4. Your data stays in `data/pg_accountant.db` — never shared

---

## Security Notes

- Never commit `.env` to version control (it's in `.gitignore`)
- SQLite DB file (`data/pg_accountant.db`) contains financial data — back it up regularly
- Dashboard files auto-delete after 24h
- Twilio credentials give access to your WhatsApp number — keep them secret

---

## License

MIT — use freely, clone for every PG you own.
