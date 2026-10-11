#!/usr/bin/env bash
# Restore the sandbox DB to the baseline snapshot (a "cold" start).
# Usage: PG_BIN=/path/to/pgsql/bin BASELINE=/path/pgtest_baseline.dump bash tests/sandbox/reset_db.sh
# Stop every sandbox server first — open connections block DROP DATABASE.
set -euo pipefail
: "${PG_BIN:?set PG_BIN to the portable Postgres bin dir}"
: "${BASELINE:?set BASELINE to the pg_dump -Fc baseline file}"
P="-h localhost -p 55432 -U postgres"
"$PG_BIN/psql" $P -q -c "select pg_terminate_backend(pid) from pg_stat_activity where datname='pgtest' and pid<>pg_backend_pid();" >/dev/null
"$PG_BIN/psql" $P -q -c "drop database if exists pgtest" -c "create database pgtest"
"$PG_BIN/pg_restore" $P -d pgtest --no-owner "$BASELINE"
: > "$(dirname "$0")/outbound.jsonl"
echo "sandbox reset to baseline"
