# Deployment Guide — Cozeevo PG Accountant

> Cloud deployment on Hostinger VPS (Ubuntu 22.04).
> Target: ~$5/month for a single PG instance.
> Last updated: 2026-03-14

---

## Architecture on the Server

```
Internet
    │
    ▼ HTTPS (443)
nginx (reverse proxy + SSL)
    │
    ├──► /webhook/*    → FastAPI (port 8000, systemd service)
    └──► /api/*        → FastAPI (port 8000, systemd service)

FastAPI
    └──► Supabase (cloud PostgreSQL — no local DB needed)
    └──► Ollama (port 11434 — local LLM on same server)
```

---

## Prerequisites

- **Hostinger VPS KVM 1** (~$5/month) — Ubuntu 22.04 LTS, 1 vCPU, 1 GB RAM
- **Domain name** — point an A record to your VPS IP (e.g. `api.yourpg.com`)
- **Supabase account** — free tier, already set up with 21 tables and data
- **Meta WhatsApp Business account** — app created at [developers.facebook.com](https://developers.facebook.com), phone number verified

---

## Step 1 — Server Initial Setup

SSH into your VPS:

```bash
ssh root@your-server-ip
```

Update and install dependencies:

```bash
apt update && apt upgrade -y
apt install -y python3.11 python3.11-venv python3-pip git nginx certbot python3-certbot-nginx
```

---

## Step 2 — Clone the Repository

```bash
cd /opt
git clone https://github.com/cozeevoemp1-ctrl/cozeevo-pg-accountant.git pg-accountant
cd pg-accountant
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## Step 3 — Configure `.env`

```bash
cp .env.example .env
nano .env
```

Fill in:

```env
# Supabase
DATABASE_URL=postgresql+asyncpg://postgres:[password]@db.[ref].supabase.co:5432/postgres
SUPABASE_URL=https://[ref].supabase.co
SUPABASE_KEY=your-anon-key

# Meta WhatsApp Cloud API
META_WHATSAPP_TOKEN=your-permanent-access-token
PHONE_NUMBER_ID=your-phone-number-id
VERIFY_TOKEN=pg-accountant-verify

# LLM
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2

# App
SECRET_KEY=generate-a-random-secret-here
ENVIRONMENT=production
```

---

## Step 4 — Install Ollama

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.2
```

Test: `ollama run llama3.2 "hello"` — should respond.

Enable as a service:

```bash
systemctl enable ollama
systemctl start ollama
```

---

## Step 5 — FastAPI as systemd Service

Create the service file:

```bash
nano /etc/systemd/system/pg-accountant.service
```

```ini
[Unit]
Description=Cozeevo PG Accountant FastAPI
After=network.target

[Service]
User=root
WorkingDirectory=/opt/pg-accountant
Environment="PATH=/opt/pg-accountant/venv/bin"
ExecStart=/opt/pg-accountant/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
systemctl daemon-reload
systemctl enable pg-accountant
systemctl start pg-accountant
```

Test: `curl http://localhost:8000/healthz` → `{"status":"ok"}`

---

## Step 6 — nginx + SSL

Create nginx config:

```bash
nano /etc/nginx/sites-available/pg-accountant
```

```nginx
server {
    server_name api.yourpg.com;

    # WhatsApp webhook — Meta Cloud API sends messages here
    location /webhook/ {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    # Internal API (healthz, docs etc.)
    location /api/ {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    location /healthz {
        proxy_pass http://localhost:8000;
    }

}
```

Enable and get SSL:

```bash
# Remove default site to avoid port 80 conflict
rm -f /etc/nginx/sites-enabled/default
ln -s /etc/nginx/sites-available/pg-accountant /etc/nginx/sites-enabled/
nginx -t
systemctl reload nginx
certbot --nginx -d api.yourpg.com
```

---

## Step 7 — Meta Cloud API Webhook

In your Meta Developer Console ([developers.facebook.com](https://developers.facebook.com)):

1. Go to your app → **WhatsApp → Configuration**
2. **Webhook URL:** `https://api.yourpg.com/webhook/whatsapp`
3. **Verify Token:** `pg-accountant-verify` (matches `VERIFY_TOKEN` in `.env`)
4. Click **Verify and Save**
5. Subscribe to: **messages**

Test: Send a WhatsApp message to your business number → should get a reply.

---

## Step 8 — Run Database Migrations

```bash
cd /opt/pg-accountant
source venv/bin/activate

# Master migration (creates all tables — idempotent, safe to re-run)
python -m src.database.migrate_all

# WiFi columns (v2.0+ — adds wifi_ssid, wifi_password, wifi_floor_map to properties)
python -m src.database.migrate_wifi
```

---

## Step 9 — Health Check

```bash
# FastAPI
curl https://api.yourpg.com/healthz

# Check services
systemctl status pg-accountant
systemctl status ollama
```

---

## Maintenance

### View logs

```bash
# FastAPI logs
journalctl -u pg-accountant -f

# nginx logs
tail -f /var/log/nginx/access.log
```

### Update the code

```bash
cd /opt/pg-accountant
git pull origin master
source venv/bin/activate
pip install -r requirements.txt
systemctl restart pg-accountant
```

### Database migrations (after code updates)

```bash
cd /opt/pg-accountant
source venv/bin/activate
python src/database/migrate_all.py
```

---

## Multi-PG Deployment

For a second PG customer:

1. Create new Supabase project → get new `DATABASE_URL` + `SUPABASE_KEY`
2. Get new WhatsApp Business phone number
3. Copy the repo to `/opt/pg-accountant-customer2/`
4. Create new `.env` with new Supabase + WhatsApp credentials
5. Create new systemd service on a different port (e.g. 8001)
6. Add new nginx location block for the new customer's domain

Each instance is fully isolated — no shared DB, no shared phone number.

---

## Cost Breakdown (per PG instance)

| Service | Cost |
|---------|------|
| Hostinger VPS KVM 1 (shared across instances) | ~$5/month |
| Supabase (free tier — up to 500 MB) | Free |
| Meta WhatsApp Cloud API (up to 1,000 msgs/day) | Free |
| Ollama llama3.2 (runs on VPS) | Free |
| **Total** | **~$5/month** |

For multiple PG customers: upgrade to VPS KVM 2 (~$10/month) to handle load.
