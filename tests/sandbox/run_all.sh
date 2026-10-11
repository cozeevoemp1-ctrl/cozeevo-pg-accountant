#!/usr/bin/env bash
# Full sandbox regression: cold run (DB reset to the test baseline) then a repeat
# run on the mutated state, every area in turn, one server at a time.
#
#   PG_BIN=.../pgsql/bin TESTBASE=.../pgtest_testbase.dump bash tests/sandbox/run_all.sh
#
# TESTBASE = the synthetic baseline with tests/sandbox/fixtures/*.sql applied
# (see README). ops.json runs on a DEMO_MODE server because it uses extra
# ops-only test phones; DEMO_MODE also mutes WhatsApp/Sheet sends, so the
# areas that assert on outbound sends run on a normal server.
set -uo pipefail
: "${PG_BIN:?}"; : "${TESTBASE:?}"
cd "$(dirname "$0")/../.."
PY=venv/Scripts/python
DB=postgresql+asyncpg://postgres@localhost:55432/pgtest
DEMO_ROLES_OPS="6000081041:Kiran:admin,6000081042:Lokesh:receptionist,6000081043:Lakshmi:owner,7845952289:Kiran:admin,7358341775:Lakshmi:owner,9444296681:Prabhakaran:owner,7680814628:Lokesh:receptionist"

stop() { local pid; pid=$(netstat -ano | grep LISTENING | grep ":$1 " | awk '{print $NF}' | head -1); [ -n "$pid" ] && taskkill //PID "$pid" //F >/dev/null; sleep 1; }
start() {  # port [demo]
  if [ "${2:-}" = demo ]; then
    DATABASE_URL=$DB DEMO_MODE=1 DEMO_ROLES="$DEMO_ROLES_OPS" $PY tests/sandbox/sandbox_server.py --port "$1" > "tests/sandbox/server_$1.log" 2>&1 &
  else
    DATABASE_URL=$DB $PY tests/sandbox/sandbox_server.py --port "$1" > "tests/sandbox/server_$1.log" 2>&1 &
  fi
  for _ in $(seq 1 60); do curl -s -m 2 "localhost:$1/healthz" >/dev/null && return 0; sleep 2; done
  echo "server $1 failed to start"; tail -20 "tests/sandbox/server_$1.log"; exit 1
}

stop 8100; stop 8104
P="-h localhost -p 55432 -U postgres"
"$PG_BIN/psql" $P -q -c "select pg_terminate_backend(pid) from pg_stat_activity where datname='pgtest' and pid<>pg_backend_pid();" >/dev/null
"$PG_BIN/psql" $P -q -c "drop database if exists pgtest" -c "create database pgtest"
"$PG_BIN/pg_restore" $P -d pgtest --no-owner "$TESTBASE"
: > tests/sandbox/outbound.jsonl
echo "== DB reset to test baseline"

$PY tests/sandbox/check_intents.py | tail -1

for label in cold repeat; do
  echo "== $label"
  start 8100
  for area in queries gate edits lifecycle; do
    $PY tests/sandbox/run_cases.py "tests/sandbox/cases/$area.json" --port 8100 --label "$label"
  done
  stop 8100
  start 8104 demo
  $PY tests/sandbox/run_cases.py tests/sandbox/cases/ops.json --port 8104 --label "$label"
  stop 8104
  DATABASE_URL=$DB $PY tests/sandbox/test_gate_webhook.py 2>&1 | tail -1
done
