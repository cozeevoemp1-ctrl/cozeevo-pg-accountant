# WhatsApp bot sandbox — end-to-end tests without touching production

Runs the real FastAPI app (real regex, real handlers, real Groq/Claude calls) against a
**local Postgres with synthetic data**. Every call that could reach a real person or
system — Meta WhatsApp, Google Sheets/Drive/Gmail, Supabase Storage — is blocked at the
HTTP layer, answered with a fake success, and recorded in `outbound.jsonl` so tests can
assert on what *would* have been sent.

Why not the local `.env`? Its `DATABASE_URL` is the production Supabase DB, and write
intents mirror to the live Sheet and can message tenants.

## One-time setup (Windows, no Docker/installer needed)

```bash
# 1. Portable Postgres 17 binaries (EDB zip), anywhere outside the repo
curl -L -o pg.zip https://get.enterprisedb.com/postgresql/postgresql-17.6-1-windows-x64-binaries.zip
unzip -q pg.zip -d pg -x 'pgsql/pgAdmin 4/*' 'pgsql/doc/*' 'pgsql/StackBuilder/*'
export PG_BIN=$PWD/pg/pgsql/bin

# 2. Cluster on port 55432 + Supabase stub roles/functions the migrations expect
$PG_BIN/initdb -D pgdata -U postgres -A trust -E UTF8
$PG_BIN/pg_ctl -D pgdata -o "-p 55432" -l pg.log start
$PG_BIN/psql -h localhost -p 55432 -U postgres -c "create database pgtest" \
  -c "create role anon nologin; create role authenticated nologin; create role service_role nologin;"
$PG_BIN/psql -h localhost -p 55432 -U postgres -d pgtest -c "create schema auth;
  create function auth.uid() returns uuid language sql as 'select null::uuid';
  create function auth.role() returns text language sql as 'select null::text';
  create function auth.jwt() returns jsonb language sql as 'select null::jsonb';"

# 3. Schema + synthetic data (from the repo root)
export DATABASE_URL=postgresql+asyncpg://postgres@localhost:55432/pgtest PYTHONPATH=$PWD
venv/Scripts/python -c "import asyncio;from sqlalchemy.ext.asyncio import create_async_engine as c;from src.database.models import Base
async def m():
  async with c('$DATABASE_URL').begin() as x: await x.run_sync(Base.metadata.create_all)
asyncio.run(m())"
DEMO_MODE=1 venv/Scripts/python scripts/seed_demo_data.py --confirm   # fictional tenants/payments
$PG_BIN/psql -h localhost -p 55432 -U postgres -d pgtest -c \
  "update properties set name='Cozeevo THOR' where id=1; update properties set name='Cozeevo HULK' where id=2;
   alter table property_config alter column id set default gen_random_uuid();"
venv/Scripts/python -m src.database.migrate_all   # a few steps that assume prod history fail; harmless here

# 4. Baseline snapshot, then the test baseline = baseline + tests/sandbox/fixtures/*.sql
$PG_BIN/pg_dump -h localhost -p 55432 -U postgres -Fc -f pgtest_baseline.dump pgtest
for f in tests/sandbox/fixtures/*.sql; do $PG_BIN/psql -h localhost -p 55432 -U postgres -d pgtest -v ON_ERROR_STOP=1 -f $f; done
$PG_BIN/pg_dump -h localhost -p 55432 -U postgres -Fc -f pgtest_testbase.dump pgtest
```

Fixtures: `10_lifecycle.sql` (no-show + checkout tenants with unique `90000090xx` phones),
`20_ops.sql` (test wifi map, chit rows 900/901). Cases find fixture tenants by phone.

## Full regression (what to run before merging to master)

```bash
PG_BIN=.../pgsql/bin TESTBASE=.../pgtest_testbase.dump bash tests/sandbox/run_all.sh
```
Resets the DB to the test baseline, then runs every area **cold**, then again as a
**repeat** on the mutated state; `ops.json` runs on a `DEMO_MODE` server (extra ops-only
phones), the rest on a normal one. Paid LLM APIs are blocked unless `SANDBOX_ALLOW_LLM=1`.

## Running

```bash
# server (refuses to start unless DATABASE_URL is localhost)
DATABASE_URL=postgresql+asyncpg://postgres@localhost:55432/pgtest \
  venv/Scripts/python tests/sandbox/sandbox_server.py --port 8100

# offline regex check (no server) — run after any intent_detector.py edit
venv/Scripts/python tests/sandbox/check_intents.py

# cold run: reset DB to baseline, start server, replay every case
PG_BIN=... BASELINE=.../pgtest_baseline.dump bash tests/sandbox/reset_db.sh
venv/Scripts/python tests/sandbox/run_cases.py tests/sandbox/cases/*.json --port 8100 --label cold
# repeat run: same cases again on the mutated state (catches stale pending state, non-idempotent writes)
venv/Scripts/python tests/sandbox/run_cases.py tests/sandbox/cases/*.json --port 8100 --label repeat
```

Results land in `tests/sandbox/results/` (gitignored); the summary of each full run is
recorded in `docs/TESTING.md`.

## Case files — `tests/sandbox/cases/*.json`

| File | Covers |
|---|---|
| `lifecycle.json` | add tenant, onboarding, arrival, check-in edits, checkout, notices |
| `edits.json` | room transfer/assign, rent/phone/gender/sharing edits, notes, blacklist, audit |
| `queries.json` | vacant/occupancy/layout/notices/check-ins/master data/activity, LLM fallback |
| `ops.json` | staff, complaints, contacts, wifi, vacation, help/menus, chit register |
| `gate.json` | role gate (blocked numbers silent), finance block, pre-gate leaks, media |

Format is documented in the `run_cases.py` docstring. Phones: Kiran 917845952289 (admin),
917358341775 / 919444296681 (owner), Lokesh 917680814628 (receptionist); anything else is blocked.
