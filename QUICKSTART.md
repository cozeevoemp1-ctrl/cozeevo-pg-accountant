
# Cozeevo PG Accountant — Local Setup Guide

> **Goal:** Get everything running on your laptop so you can test before going live.
> **Time:** ~30 minutes (mostly waiting for Docker to install).

---

## What you'll have running locally

```
Your WhatsApp
    ↓
Meta Cloud API (free, already configured)
    ↓  webhook
n8n (Docker on port 5678)  ← you'll install this
    ↓  calls
FastAPI (port 8000)  ← already works, start it with START_API.bat
    ↓
Supabase (cloud DB)  ← already live with all your data
```

---

## STEP 1 — Start FastAPI (already works)

Double-click **`START_API.bat`** (in the project folder).

Or in a terminal:
```
cd "c:\Users\kiran\Desktop\AI Watsapp PG Accountant"
venv\Scripts\activate
uvicorn main:app --reload
```

Test it: open your browser → `http://localhost:8000/healthz`
You should see: `{"status":"ok","service":"pg-accountant"}`

**API docs:** `http://localhost:8000/docs` (Swagger UI — explore all endpoints here)

---

## STEP 2 — Install Docker Desktop (needed for n8n)

1. Go to **https://www.docker.com/products/docker-desktop/**
2. Click **"Download for Windows"**
3. Run the installer — accept all defaults
4. Restart your computer when asked
5. Open Docker Desktop — wait for the green "Running" indicator

---

## STEP 3 — Start n8n

In the project folder, open a terminal and run:
```
docker-compose up -d
```

This starts n8n in the background. First time takes 1-2 minutes (downloads the n8n image).

Check it's running: open `http://localhost:5678`
- Username: `admin`
- Password: `pgaccountant2024`

---

## STEP 4 — Set n8n Variable (FastAPI URL)

In n8n:
1. Go to **Settings → Variables** (left sidebar)
2. Click **Add Variable**
3. Name: `FASTAPI_URL`
4. Value: `http://host.docker.internal:8000`
5. Save

> `host.docker.internal` is how Docker containers talk to your laptop's localhost.

---

## STEP 5 — Import the WhatsApp Workflow

In n8n:
1. Click **Workflows** in the left sidebar
2. Click **Import from File**
3. Select: `workflows/WA-01-whatsapp-router.json`
4. Open the workflow → click **Active** toggle (top right) to activate it
5. Copy the **Webhook URL** shown on the WhatsApp Trigger node

---

## STEP 6 — Connect WhatsApp (Meta Cloud API)

You need to make n8n's webhook reachable from the internet (Meta needs to send messages to it).

**Option A: Use ngrok (free, for testing)**
1. Download ngrok: https://ngrok.com/download
2. In a terminal: `ngrok http 5678`
3. Copy the `https://xxxx.ngrok.io` URL

**Option B: Deploy to Hostinger VPS (permanent, ~$5/month)**
- See `DEPLOYMENT.md` for full cloud setup guide

Then in Meta Developer Console:
1. Go to **developers.facebook.com** → your app → **WhatsApp → Configuration**
2. Set **Webhook URL**: `https://your-ngrok-url/webhook/pg-whatsapp-trigger`
3. Set **Verify Token**: `pg-accountant-verify`
4. Subscribe to: **messages**

---

## STEP 7 — Test End-to-End

Send a WhatsApp message to your business number:
- `"price"` → should get room prices reply
- `"who hasn't paid"` (from your number +917845952289) → should get dues list
- Any message from an unknown number → should get the lead welcome message

---

## WhatsApp Commands Reference

### Your number (+917845952289) — Admin
```
who hasn't paid          → dues list for this month
Raj paid 15000 upi       → logs payment for Raj
Raj balance              → show Raj's account
monthly report           → this month's summary
help                     → full command list
```

### Tenant number (any registered tenant)
```
my balance               → their pending rent
my payments              → last 6 payments
my details               → room + checkin info
```

### Unknown number (leads)
```
price / rent             → room prices
available                → availability
single / double          → room type info
visit                    → book a tour
```

---

## Daily Use

| Task | How |
|------|-----|
| Start the app | Double-click `START_API.bat` |
| Start n8n | `docker-compose up -d` (in project folder) |
| Stop n8n | `docker-compose down` |
| View logs | `docker-compose logs -f n8n` |
| View API logs | Terminal where START_API.bat is running |
| API docs | `http://localhost:8000/docs` |
| n8n dashboard | `http://localhost:5678` |

---

## Common Problems

| Problem | Fix |
|---------|-----|
| `START_API.bat` shows import errors | Run `pip install -r requirements.txt` first |
| Docker not found | Restart your computer after installing Docker Desktop |
| n8n can't reach FastAPI | Set FASTAPI_URL variable to `http://host.docker.internal:8000` in n8n |
| WhatsApp not replying | Check ngrok is running + Meta webhook URL is correct |
| DB connection error | Check DATABASE_URL in `.env` points to Supabase |

---

## File Structure (what matters)

```
AI Watsapp PG Accountant/
├── .env                         ← YOUR SETTINGS — DB URL, phone numbers, tokens
├── main.py                      ← FastAPI app entry point
├── START_API.bat                ← Start FastAPI
├── docker-compose.yml           ← Start n8n
├── workflows/
│   └── WA-01-whatsapp-router.json   ← Import this into n8n
├── src/
│   ├── database/
│   │   ├── models.py            ← 19-table schema
│   │   ├── db_manager.py        ← DB operations
│   │   ├── seed.py              ← Initial data (already run)
│   │   └── excel_import.py      ← One-time Excel import (already done)
│   └── whatsapp/
│       ├── chat_api.py          ← Main WhatsApp endpoint
│       ├── role_service.py      ← Detects caller role
│       ├── intent_detector.py   ← Understands what they're asking
│       └── handlers/
│           ├── owner_handler.py    ← Admin/partner commands
│           ├── tenant_handler.py   ← Tenant self-service
│           └── lead_handler.py     ← Room enquiry bot
```
