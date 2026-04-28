#!/bin/bash
# Post-deploy smoke test — hit every critical API endpoint and fail loudly.
# Usage: ./scripts/smoke_test.sh [BASE_URL]
# Run automatically after every VPS deploy.

BASE="${1:-https://api.getkozzy.com}"
PASS=0
FAIL=0

check() {
  local label="$1"
  local url="$2"
  local expected="${3:-200}"
  local code
  code=$(curl -s -o /dev/null -w "%{http_code}" "$url" 2>/dev/null)
  if [ "$code" = "$expected" ]; then
    echo "  ✓  $label ($code)"
    PASS=$((PASS + 1))
  else
    echo "  ✗  $label — expected $expected, got $code  ← BROKEN"
    FAIL=$((FAIL + 1))
  fi
}

echo ""
echo "Smoke test → $BASE"
echo "────────────────────────────────"

# Public / health
check "Root health"       "$BASE/"              200
check "API reachable"     "$BASE/api/v2/app/health" 401   # 401 = auth works, endpoint alive
check "KPI endpoint"      "$BASE/api/v2/app/reporting/kpi" 401
check "Activity endpoint" "$BASE/api/v2/app/activity/recent" 401
check "Collection endpoint" "$BASE/api/v2/app/reporting/collection?period_month=2026-04" 401
check "Tenants search"    "$BASE/api/v2/app/tenants/search?q=test" 401
check "Tenants list"      "$BASE/api/v2/app/tenants/list" 401
check "Reminders overdue" "$BASE/api/v2/app/reminders/overdue" 401
check "Checkin preview"   "$BASE/api/v2/app/tenants/1/checkin-preview?actual_date=2026-04-01" 401

echo "────────────────────────────────"
echo "  Passed: $PASS  Failed: $FAIL"

if [ "$FAIL" -gt 0 ]; then
  echo ""
  echo "  DEPLOY FAILED — $FAIL endpoint(s) are broken."
  echo "  Check: journalctl -u pg-accountant -n 50 --no-pager"
  exit 1
else
  echo ""
  echo "  All endpoints healthy."
  exit 0
fi
