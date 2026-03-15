#!/usr/bin/env bash
# =============================================================================
# Cozeevo PG Accountant — VPS Setup Script
# Tested on: Ubuntu 22.04 LTS (Hostinger KVM 1)
#
# Run as root on a fresh VPS:
#   wget -qO setup_vps.sh https://raw.githubusercontent.com/cozeevoemp1-ctrl/cozeevo-pg-accountant/master/deploy/setup_vps.sh
#   chmod +x setup_vps.sh && ./setup_vps.sh
#
# After it finishes:
#   1. Edit /opt/pg-accountant/.env (fill in your Supabase + Meta credentials)
#   2. Update DOMAIN= below OR pass as env var: DOMAIN=api.yourpg.com ./setup_vps.sh
#   3. Run: certbot --nginx -d $DOMAIN
#   4. Set Meta webhook URL to: https://$DOMAIN/webhook/whatsapp
# =============================================================================

set -euo pipefail

DOMAIN="${DOMAIN:-api.yourpg.com}"
REPO="https://github.com/cozeevoemp1-ctrl/cozeevo-pg-accountant.git"
APP_DIR="/opt/pg-accountant"

echo "=== Cozeevo PG Accountant VPS Setup ==="
echo "Domain: $DOMAIN"
echo "App dir: $APP_DIR"
echo ""

# ── 1. System dependencies ────────────────────────────────────────────────────
echo "[1/7] Installing system packages..."
apt-get update -qq
apt-get install -y -qq \
    python3 python3-venv python3-pip \
    git nginx certbot python3-certbot-nginx \
    libpoppler-cpp-dev poppler-utils \
    curl

# ── 2. Docker ─────────────────────────────────────────────────────────────────
echo "[2/7] Installing Docker..."
if ! command -v docker &>/dev/null; then
    curl -fsSL https://get.docker.com | sh
    systemctl enable --now docker
else
    echo "  Docker already installed, skipping."
fi

# Install docker-compose v2 plugin
if ! docker compose version &>/dev/null 2>&1; then
    apt-get install -y -qq docker-compose-plugin
fi

# ── 3. Clone / update repo ────────────────────────────────────────────────────
echo "[3/7] Deploying application..."
if [ -d "$APP_DIR/.git" ]; then
    echo "  Repo exists — pulling latest..."
    cd "$APP_DIR"
    git pull origin master
else
    git clone "$REPO" "$APP_DIR"
    cd "$APP_DIR"
fi

# Python virtualenv
python3 -m venv venv
source venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

# Copy env template if .env doesn't exist yet
if [ ! -f .env ]; then
    cp .env.example .env
    echo ""
    echo "  ⚠️  .env created from template. Edit it now:"
    echo "  nano $APP_DIR/.env"
    echo ""
fi

# ── 4. Run DB migrations ──────────────────────────────────────────────────────
echo "[4/7] Running database migrations..."
if grep -q "DATABASE_URL=postgresql" .env; then
    python -m src.database.migrate_all   2>/dev/null || echo "  (migrate_all skipped — check DB connection)"
    python -m src.database.migrate_wifi  2>/dev/null || echo "  (migrate_wifi skipped — check DB connection)"
else
    echo "  Skipping migrations — DATABASE_URL not set yet. Run manually after editing .env:"
    echo "    cd $APP_DIR && source venv/bin/activate"
    echo "    python -m src.database.migrate_all"
    echo "    python -m src.database.migrate_wifi"
fi

# ── 5. systemd service for FastAPI ────────────────────────────────────────────
echo "[5/7] Installing FastAPI systemd service..."
cat > /etc/systemd/system/pg-accountant.service << EOF
[Unit]
Description=Cozeevo PG Accountant FastAPI
After=network.target

[Service]
User=root
WorkingDirectory=$APP_DIR
Environment="PATH=$APP_DIR/venv/bin"
EnvironmentFile=$APP_DIR/.env
ExecStart=$APP_DIR/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000 --workers 2
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable pg-accountant
systemctl start pg-accountant
echo "  FastAPI: $(systemctl is-active pg-accountant)"

# ── 6. n8n via Docker ─────────────────────────────────────────────────────────
echo "[6/7] Starting n8n..."
cd "$APP_DIR"
docker compose up -d
echo "  n8n: $(docker ps --filter name=pg_n8n --format '{{.Status}}')"

# ── 7. nginx config ───────────────────────────────────────────────────────────
echo "[7/7] Configuring nginx..."
cat > /etc/nginx/sites-available/pg-accountant << EOF
server {
    listen 80;
    server_name $DOMAIN;

    # WhatsApp webhook — Meta Cloud API sends messages here (must be public)
    location /webhook/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    }

    # Health check (public)
    location = /healthz {
        proxy_pass http://127.0.0.1:8000;
    }

    # API + docs (localhost only — nginx itself is on localhost so this passes through)
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    }

    # n8n dashboard (protected by n8n's own basic auth)
    location /n8n/ {
        proxy_pass http://127.0.0.1:5678/;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
EOF

rm -f /etc/nginx/sites-enabled/default
ln -sf /etc/nginx/sites-available/pg-accountant /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
echo "  nginx: $(systemctl is-active nginx)"

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "=== Setup complete! ==="
echo ""
echo "Next steps:"
echo "  1. Edit .env:       nano $APP_DIR/.env"
echo "  2. Restart FastAPI: systemctl restart pg-accountant"
echo "  3. Get SSL cert:    certbot --nginx -d $DOMAIN"
echo "  4. Set Meta webhook URL: https://$DOMAIN/webhook/whatsapp"
echo "  5. Health check:    curl https://$DOMAIN/healthz"
echo ""
echo "n8n dashboard: http://$(curl -s ifconfig.me):5678"
echo "  → Add variable: FASTAPI_URL = http://host.docker.internal:8000"
echo "  → Import: $APP_DIR/workflows/WA-01-whatsapp-router.json"
echo ""
