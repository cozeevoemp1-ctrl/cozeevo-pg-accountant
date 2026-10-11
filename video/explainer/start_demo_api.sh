#!/usr/bin/env bash
# Sandbox API for demo recordings: local fake data, finance intents on, accepts the
# PWA's dev-login token (secret shared via web/.env.development.local). Run from repo root.
set -euo pipefail
export SUPABASE_JWT_SECRET=$(grep '^DEV_DEMO_JWT_SECRET=' web/.env.development.local | cut -d= -f2)
export SUPABASE_URL=   # never contact real Supabase (JWKS) from the sandbox
export DATABASE_URL=postgresql+asyncpg://postgres@localhost:55432/pgtest
exec venv/Scripts/python tests/sandbox/sandbox_server.py --port 8100 --allow-finance --fake-sheets
