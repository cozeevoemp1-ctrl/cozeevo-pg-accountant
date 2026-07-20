#!/usr/bin/env bash
# =============================================================================
# Kozzy DEMO instance — VPS setup (runs alongside production on the same box)
#
#   Production: /opt/pg-accountant  api  :8000  api.getkozzy.com
#               kozzy-pwa.service   pwa  :3000  app.getkozzy.com
#   Demo:       /opt/pg-demo        api  :8100  api-demo.getkozzy.com
#               kozzy-pwa-demo      pwa  :3100  demo.getkozzy.com
#
# Prereqs (manual, before running):
#   1. Demo Supabase project created; /opt/pg-demo/.env filled (see bottom)
#   2. Cloudflare DNS A records: demo + api-demo → this VPS IP (proxied off
#      until certbot done, then on)
#
# Run as root:  DOMAIN_API=api-demo.getkozzy.com DOMAIN_PWA=demo.getkozzy.com ./setup_demo_vps.sh
# =============================================================================

set -euo pipefail

DOMAIN_API="${DOMAIN_API:-api-demo.getkozzy.com}"
DOMAIN_PWA="${DOMAIN_PWA:-demo.getkozzy.com}"
# URL of the DEMO repo (not the live repo) — pass explicitly, no default:
#   REPO=https://github.com/<org>/<demo-repo>.git ./setup_demo_vps.sh
REPO="${REPO:?Set REPO=<git url of the demo repo>}"
APP_DIR="/opt/pg-demo"
API_PORT=8100
PWA_PORT=3100

echo "=== Kozzy DEMO setup ==="

# ── 1. Clone / update ────────────────────────────────────────────────────────
if [ -d "$APP_DIR/.git" ]; then
    cd "$APP_DIR" && git pull origin master
else
    git clone "$REPO" "$APP_DIR" && cd "$APP_DIR"
fi

python3 -m venv venv
source venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

if [ ! -f .env ]; then
    cp .env.example .env
    echo "⚠️  Fill $APP_DIR/.env with the DEMO Supabase credentials, set DEMO_MODE=1,"
    echo "    leave WHATSAPP_TOKEN empty, then re-run this script."
    exit 1
fi

grep -q '^DEMO_MODE=1' .env || { echo "ABORT: DEMO_MODE=1 not set in $APP_DIR/.env"; exit 1; }

# ── 2. Migrate + seed ────────────────────────────────────────────────────────
python -m src.database.migrate_all
python scripts/seed_demo_data.py --confirm || echo "  (seed skipped — already seeded?)"

# ── 3. PWA build ─────────────────────────────────────────────────────────────
cd "$APP_DIR/web"
if [ ! -f .env.production ]; then
    cat > .env.production << ENVEOF
NEXT_PUBLIC_API_URL=https://$DOMAIN_API
NEXT_PUBLIC_SUPABASE_URL=CHANGE_ME_demo_supabase_url
NEXT_PUBLIC_SUPABASE_ANON_KEY=CHANGE_ME_demo_anon_key
NEXT_PUBLIC_DEMO_MODE=1
ENVEOF
    echo "⚠️  Fill $APP_DIR/web/.env.production (demo Supabase URL + anon key), then re-run."
    exit 1
fi
npm ci
npm run build
cd "$APP_DIR"

# ── 4. systemd services ──────────────────────────────────────────────────────
cat > /etc/systemd/system/pg-demo.service << EOF
[Unit]
Description=Kozzy DEMO FastAPI
After=network.target

[Service]
User=root
WorkingDirectory=$APP_DIR
Environment="PATH=$APP_DIR/venv/bin"
EnvironmentFile=$APP_DIR/.env
ExecStart=$APP_DIR/venv/bin/uvicorn main:app --host 127.0.0.1 --port $API_PORT --workers 1
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/kozzy-pwa-demo.service << EOF
[Unit]
Description=Kozzy DEMO PWA (Next.js)
After=network.target

[Service]
User=root
WorkingDirectory=$APP_DIR/web
Environment="PORT=$PWA_PORT"
ExecStart=/usr/bin/npm run start -- -p $PWA_PORT
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now pg-demo kozzy-pwa-demo

# ── 5. nginx ─────────────────────────────────────────────────────────────────
cat > /etc/nginx/sites-available/pg-demo << EOF
server {
    listen 80;
    server_name $DOMAIN_API;
    location / {
        proxy_pass http://127.0.0.1:$API_PORT;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    }
}
server {
    listen 80;
    server_name $DOMAIN_PWA;
    location / {
        proxy_pass http://127.0.0.1:$PWA_PORT;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
EOF

ln -sf /etc/nginx/sites-available/pg-demo /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx

echo ""
echo "=== Demo setup done ==="
echo "  1. SSL:   certbot --nginx -d $DOMAIN_API -d $DOMAIN_PWA"
echo "  2. Users: cd $APP_DIR && venv/bin/python scripts/create_auth_users.py   (demo Supabase)"
echo "  3. Check: curl https://$DOMAIN_API/healthz ; open https://$DOMAIN_PWA"
