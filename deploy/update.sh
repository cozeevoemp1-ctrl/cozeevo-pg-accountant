#!/usr/bin/env bash
# =============================================================================
# Cozeevo PG Accountant — Fast Update Script
# Run on VPS after pushing code changes from local machine:
#   ssh root@your-vps-ip "cd /opt/pg-accountant && bash deploy/update.sh"
# =============================================================================

set -euo pipefail

APP_DIR="/opt/pg-accountant"
cd "$APP_DIR"

echo "=== Updating PG Accountant ==="

# Pull latest code
git pull origin master

# Update Python deps (only if requirements.txt changed)
source venv/bin/activate
pip install --quiet -r requirements.txt

# Run any new migrations (all idempotent — safe to re-run)
python -m src.database.migrate_all  2>/dev/null && echo "  migrations: ok"
python -m src.database.migrate_wifi 2>/dev/null && echo "  wifi migration: ok"

# Restart FastAPI
systemctl restart pg-accountant
sleep 2
echo "  FastAPI: $(systemctl is-active pg-accountant)"

# Health check
STATUS=$(curl -s http://localhost:8000/healthz | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status','?'))" 2>/dev/null || echo "unreachable")
echo "  Health: $STATUS"

echo "=== Update complete ==="
