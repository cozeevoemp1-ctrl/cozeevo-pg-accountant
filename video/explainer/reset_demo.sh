#!/usr/bin/env bash
# Restore the sandbox DB to the demo snapshot (made by seed_demo.py + pg_dump) before a take.
# Usage (repo root): PG_BIN=... DEMO_DUMP=... bash video/explainer/reset_demo.sh
set -euo pipefail
: "${PG_BIN:?}" "${DEMO_DUMP:?}"
P="-h localhost -p 55432 -U postgres"
"$PG_BIN/psql" $P -q -c "select pg_terminate_backend(pid) from pg_stat_activity where datname='pgtest' and pid<>pg_backend_pid();" >/dev/null
"$PG_BIN/psql" $P -q -c "drop database if exists pgtest" -c "create database pgtest"
"$PG_BIN/pg_restore" $P -d pgtest --no-owner "$DEMO_DUMP"
echo "sandbox reset to demo snapshot"
