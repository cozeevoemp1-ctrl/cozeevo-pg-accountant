# Testing Strategy & Go-Live Checklist
> Cozeevo PG Accountant v1.4.0 · Last updated: 2026-03-14

---

## How to Run the Tests

### Step 1 — Generate the scenario file (one-time)
```bash
python tests/generate_scenarios.py
```
Creates `tests/scenarios_500.json` with 500 test scenarios.

### Step 2 — Start FastAPI with TEST_MODE
Add to `.env`:
```
TEST_MODE=1
```
Then:
```bash
START_API.bat          # Windows
```
Verify: `http://localhost:8000/healthz` → `{"status":"ok"}`

### Step 3 — Run the full suite
```bash
python tests/run_500.py
```

### Useful filters
```bash
# Just the financial worker (fast, 135 scenarios)
python tests/run_500.py --worker AccountWorker

# Just basic sanity check (no edge cases)
python tests/run_500.py --quick

# One intent at a time (debugging)
python tests/run_500.py --intent PAYMENT_LOG

# First 50 only (smoke test)
python tests/run_500.py --limit 50

# Preview without hitting API
python tests/run_500.py --dry

# Tenant phone configuration
TENANT_PHONE=+91XXXXXXXXXX python tests/run_500.py --worker TenantWorker
```

---

## Scenario Coverage

| Worker | Count | What's tested |
|--------|-------|---------------|
| AccountWorker | 135 | All 11 financial intents × admin + power_user + key_user roles |
| OwnerWorker | 160 | All 20 operational intents + Hinglish variants + edge cases |
| TenantWorker | 80 | 10 tenant intents + permission boundaries + Hinglish |
| LeadWorker | 50 | 5 lead intents + general conversation |
| Edge & System | 75 | Typos, empty messages, role violations, multi-step starters |
| **Total** | **500** | |

### Category breakdown
| Tag | What it tests |
|-----|---------------|
| `basic` | Canonical phrasings — should always pass |
| `hinglish` | Hindi-English mixed — optional but good to have |
| `edge` | Unusual inputs — partial pass acceptable |
| `boundary` | Wrong role sending admin commands — must reject gracefully |
| `flow` | Multi-step flow starters — checks intent only |
| `typo` | Common spelling mistakes — partial pass acceptable |
| `ambiguous` | Unclear messages — lower confidence expected |

---

## How to Read the Results

### Outcome definitions

| Outcome | Meaning |
|---------|---------|
| **PASS** | Correct intent detected + confidence ≥ threshold + reply keywords present |
| **PARTIAL** | Correct intent but confidence low OR reply missing a keyword |
| **FAIL** | Wrong intent detected |
| **ERROR** | API didn't respond (server down, timeout, crash) |

### Score interpretation

| Overall score | Verdict | Action |
|--------------|---------|--------|
| ≥ 90% | ✅ Go-live ready | Deploy with confidence |
| 80–90% | ⚠️ Soft launch | Deploy carefully, fix weak intents in v1.5 |
| 70–80% | 🔧 Needs work | Fix failing intents before live traffic |
| < 70% | ❌ Not ready | Significant regex gaps — review intent_detector.py |

### Core intents threshold (most critical)

These 7 intents are the heart of the system. They must pass at **≥ 95%**:
- `PAYMENT_LOG` — most frequent admin action
- `QUERY_DUES` — most frequent query
- `QUERY_TENANT` — second most frequent query
- `REPORT` — daily/monthly management
- `MY_BALANCE` — tenant self-service
- `ROOM_PRICE` — lead conversion
- `AVAILABILITY` — lead conversion

---

## Tenant Phone Configuration

TenantWorker tests need a real phone number that exists in the `tenants` table in Supabase.

**How to find a test tenant phone:**
```sql
-- Run in Supabase SQL editor
SELECT name, phone FROM tenants WHERE phone IS NOT NULL LIMIT 5;
```

Then set it:
```bash
set TENANT_PHONE=+91XXXXXXXXXX   # Windows
python tests/run_500.py --worker TenantWorker
```

Or edit the top of `run_500.py`:
```python
"tenant": "+91XXXXXXXXXX",   # replace with real tenant phone
```

**Note:** If tenant phone is not configured, TenantWorker tests will route to LeadWorker (unknown phone) and fail. That's expected — just configure the phone.

---

## Fixing Failing Intents

All intent patterns live in:
```
src/whatsapp/intent_detector.py
```

### Pattern for adding a new phrase
Find the intent section and add to the regex list:
```python
# PAYMENT_LOG patterns
PAYMENT_LOG_PATTERNS = [
    r"(\w+)\s+paid\s+(\d+)",          # existing
    r"received\s+(\d+)\s+from\s+(\w+)",  # add new patterns here
    r"(\w+)\s+ne\s+diya\s+(\d+)",     # Hinglish
]
```

### Common fixes by intent

**VOID_PAYMENT failing:**
Add: `"cancel payment"`, `"payment wrong"`, `"reverse payment"`, `"galat payment"`

**ADD_REFUND failing:**
Add: `"return deposit"`, `"give back deposit"`, `"wapas karo deposit"`

**RENT_DISCOUNT failing:**
Add: `"waive rent"`, `"reduce rent"`, `"rent kam karo"`

**CHECKOUT_NOTICE failing (tenant):**
Add: `"I am leaving"`, `"planning to vacate"`, `"moving out"`, `"giving notice"`

**VACATION_NOTICE failing:**
Add: `"going home"`, `"out of station"`, `"chutti pe"`, `"on leave"`

After fixing patterns, restart FastAPI and re-run:
```bash
python tests/run_500.py --intent VOID_PAYMENT
```

---

## Go-Live Checklist

### Pre-deployment (complete before going live)

**Testing:**
- [ ] Full 500-scenario suite at ≥ 80% overall
- [ ] Core 7 intents at ≥ 95%
- [ ] AccountWorker ≥ 85%
- [ ] OwnerWorker ≥ 80%
- [ ] TenantWorker ≥ 85%
- [ ] LeadWorker ≥ 85%
- [ ] Role boundary tests all returning graceful responses

**Infrastructure (local):**
- [ ] FastAPI running stable (no crashes in 30-min run)
- [ ] Supabase DB connected and responding
- [ ] Ollama running (llama3.2) — fallback for unknown intents

**Infrastructure (cloud — Hostinger VPS):**
- [ ] VPS provisioned (Hostinger KVM 1, Ubuntu 22.04)
- [ ] FastAPI running as systemd service
- [ ] Ollama installed + llama3.2 pulled
- [ ] n8n running in Docker
- [ ] nginx reverse proxy configured
- [ ] SSL certificate from certbot
- [ ] Domain A record pointing to VPS IP

**WhatsApp:**
- [ ] n8n workflow `WA-01-whatsapp-router.json` imported + active
- [ ] Meta Cloud API webhook URL configured
- [ ] Verify token matched in `.env`
- [ ] End-to-end test: send real WhatsApp message → get reply
- [ ] Admin phone +917845952289 recognized as admin

**Security:**
- [ ] `.env` file NOT in git (check `git status`)
- [ ] Supabase RLS policies active (`rls_policies.sql` applied)
- [ ] `VERIFY_TOKEN` is non-default (not `pg-accountant-verify` — change it)
- [ ] `SECRET_KEY` is random and set

**Go-live:**
- [ ] Send test messages from each role: admin, tenant, lead
- [ ] Check `journalctl -u pg-accountant -f` for any errors
- [ ] Confirm rate limiting is working (block after 10 msg/10min)
- [ ] Monitor first 24h of live traffic in whatsapp_log table

---

## Post-Launch Monitoring

Check these regularly after go-live:

```sql
-- Supabase SQL — unrecognized intents (Ollama fallback)
SELECT message, intent, confidence, created_at
FROM whatsapp_log
WHERE confidence < 0.70
ORDER BY created_at DESC
LIMIT 20;

-- Most common intents (what users actually use)
SELECT intent, count(*) as n
FROM whatsapp_log
GROUP BY intent
ORDER BY n DESC;

-- Error rate
SELECT
  COUNT(CASE WHEN reply IS NULL THEN 1 END) as errors,
  COUNT(*) as total
FROM whatsapp_log
WHERE created_at > now() - interval '24 hours';
```

Any intents appearing frequently in the low-confidence log → add those phrases to `intent_detector.py`.

---

## After Testing: Deployment Steps

Once testing passes, see `DEPLOYMENT.md` for full cloud deployment guide.

**Quick path:**
```
1. Provision Hostinger VPS KVM 1 (~$5/month)
2. Follow DEPLOYMENT.md Steps 1–9
3. Point Meta webhook to https://yourdomain.com/api/whatsapp/webhook
4. Run full test suite against production URL
5. Go live
```
