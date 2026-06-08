# Artha Bot — Testing Standard Operating Procedures

> **This document is the single source of truth for how we test the bot.**
> Every developer, every session, every deploy must follow this SOP.

---

## The Four Root Causes of Bot Failures

Based on architecture review and live conversation logs, failures fall into 4 categories:

### Failure 1: Action vs Query Confusion
Bot sees a keyword and fires the write handler, even when the user is **asking** about something.

| ❌ Wrong | ✅ Correct |
|---------|----------|
| "What are all plumbing issues?" → triggers `LOG_COMPLAINT` | → triggers `QUERY_COMPLAINTS` |
| "Any leaking taps?" → starts complaint form | → lists open complaints |
| "Did Raj pay?" → triggers `PAYMENT_LOG` | → triggers `QUERY_TENANT` |

**Fix:** Intent rules require explicit **action verbs** for write intents (`report`, `register`, `log`, `issue with`). Query words (`what`, `show`, `list`, `any open`, `status of`, `did`) route to read-only handlers.

---

### Failure 2: Entity Extraction Before Missing-Field Check
Bot asks for fields that the user already provided in the same message.

| ❌ Wrong | ✅ Correct |
|---------|----------|
| "paid plumber 2500 cash" → Bot: "Which category?" | → Extract {category: Plumbing, amount: 2500, mode: cash} → confirm |
| "2 water 2500" (step reply) → Bot: confused | → Extract all fields from full string |
| "Kiran checked in 15 Feb room 203" → Bot: "What room?" | → Extract room from message |

**Fix:** `detect_intent()` entity extraction runs on the **full message** before any step-by-step field collection. Handler checks for missing fields only AFTER extraction is complete.

---

### Failure 3: No Correction State in Confirmation Flow
User is in `Confirming_X` state and tries to correct a value. Bot rejects with "I didn't understand."

| ❌ Wrong | ✅ Correct |
|---------|----------|
| In CONFIRM_PAYMENT: "No it's UPI" → "I didn't understand" | → Update mode=UPI, re-show confirm |
| In CONFIRM_EXPENSE: "Actually 3000 not 2500" → "Reply Yes or No" | → Update amount=3000, re-show confirm |

**Fix:** `resolve_pending_action()` checks for **correction pattern** BEFORE checking yes/no. If correction detected → update `action_data`, stay in same state, re-display confirm summary.

---

### Failure 4: Technical Leak
Bot exposes internal errors, VPS details, Python tracebacks, or DB seed errors to end users.

| ❌ Wrong | ✅ Correct |
|---------|----------|
| "Run seed on VPS" shown in chat | → "Something went wrong. Please try again." |
| Python traceback in WhatsApp | → Generic error message |

**Fix:** All handler exceptions caught by gatekeeper. User always gets sanitized response. `reply_must_not_contain` check in every golden test case.

---

## Test Hierarchy — When to Run What

| Level | Command | When | Pass Target | Blocks Deploy? |
|-------|---------|------|-------------|---------------|
| **Smoke** | `python tests/run_500.py --quick` | After every code change | ≥ 80% | No |
| **Regression** | `python tests/run_500.py` | Before every `git push` | ≥ 90% | Yes |
| **Golden** | `python tests/eval_golden.py` | Before every VPS deploy | **100%** | Yes |
| **CI** | `pytest tests/eval_suite.py -v` | On PR merge | All pass | Yes |
| **Single intent** | `python tests/run_500.py --intent ADD_EXPENSE` | While fixing a specific intent | ≥ 85% | Warn only |

---

## Pass Thresholds

| Scope | Threshold | Blocks Deploy? |
|-------|-----------|---------------|
| Overall (run_500) | ≥ 90% | Yes |
| Core intents (PAYMENT_LOG, QUERY_DUES, MY_BALANCE, REPORT, ROOM_PRICE) | ≥ 95% | Yes |
| **Golden dataset (eval_golden)** | **100%** | **Yes** |
| Any single intent (run_500 --intent) | ≥ 85% | Warn only |
| Hinglish / typo tag | ≥ 70% | No |

---

## Golden Dataset Format

File: `tests/golden_test_cases.json`

```json
{
  "id": "G001",
  "name": "Clear description of what this proves",
  "category": "entity_extraction",
  "turns": [
    {
      "role": "admin",
      "input": "paid plumber 2500 cash",
      "expected_intent": "ADD_EXPENSE",
      "expected_entities": {"amount": 2500, "category": "Plumbing", "mode": "cash"},
      "expected_state": "confirming",
      "reply_must_contain": ["2,500", "Plumbing", "Confirm"],
      "reply_must_not_contain": ["error", "traceback", "vps", "seed", "database", "exception"]
    },
    {
      "role": "admin",
      "input": "yes",
      "expected_intent": "CONFIRMATION",
      "expected_state": "idle",
      "reply_must_contain": ["logged"],
      "reply_must_not_contain": ["error", "traceback", "vps", "seed", "database", "exception"]
    }
  ]
}
```

### The 8 Golden Categories

| Category | Count | What It Proves |
|----------|-------|----------------|
| `entity_extraction` | 15 | All info in one message — bot must NOT ask for fields already given |
| `correction_mid_flow` | 15 | User corrects mid-confirmation — bot updates and stays in state |
| `action_vs_query` | 20 | Same keyword, different intent — "log issue" vs "show issues" |
| `ambiguous_name` | 10 | 2+ tenants match — disambiguation flow resolves correctly |
| `incomplete_input` | 10 | Partial info — bot asks for the ONE missing piece only |
| `hinglish_typo` | 10 | Mixed language and typo tolerance |
| `role_boundary` | 10 | Wrong-role access is blocked with a clear message |
| `state_guard` | 10 | Expired pending, double-submit, out-of-order replies handled safely |

### Mandatory Fields

Every golden case turn MUST have:
- `reply_must_not_contain`: `["error", "traceback", "vps", "seed", "database", "exception"]`

---

## Running Tests

```bash
# 1. Start API (local, with Ollama for free LLM)
START_API.bat

# 2. Smoke test (after any code change)
python tests/run_500.py --quick

# 3. Regression (before git push)
python tests/run_500.py

# 4. Golden suite (before VPS deploy — must be 100%)
python tests/eval_golden.py

# 5. Single intent (while fixing a specific bug)
python tests/run_500.py --intent ADD_EXPENSE
python tests/run_500.py --intent GET_WIFI_PASSWORD

# 6. Single golden category
python tests/eval_golden.py --category correction_mid_flow

# 7. Single golden case
python tests/eval_golden.py --id G001

# 8. Technical leak check only
python tests/eval_golden.py --check-leaks
```

---

## SOP for Adding New Test Cases

### When a bug is found in production:
1. **Add the failing conversation to `golden_test_cases.json` FIRST** (before fixing code)
2. Run `python tests/eval_golden.py --id G0xx` → confirm it **fails** (proves the gap is real)
3. Fix the code in the source
4. Run golden → must be **100%** before committing
5. Commit both the fix and the new golden case in the same commit

### When a new intent is added:
Add minimum 5 golden cases:
1. Basic happy path
2. Correction mid-flow
3. Action vs query variant
4. Hinglish/typo variant
5. Partial info (one field missing)

### When a role boundary is added:
Add 1 golden case per blocked role to `role_boundary` category.

---

## What NOT to Test

- ❌ Don't run 10,000 random variations — 5 representative + 2 edge cases per intent is enough
- ❌ Don't test what regex already reliably covers (basic keyword matches) — test the LLM fallback edge cases
- ❌ Don't run bulk tests BEFORE fixing known broken intents — fix first, then verify
- ❌ Don't test only happy paths — every intent needs ≥1 correction + ≥1 action_vs_query case
- ✅ Do test the exact conversation that broke in production — and add it to golden

---

## Local vs VPS Testing

| Aspect | Local | VPS |
|--------|-------|-----|
| LLM | Ollama (free, unlimited) | Groq (rate-limited, costs money) |
| DB | Supabase (same cloud DB) | Supabase (same cloud DB) |
| `.env` LLM_PROVIDER | `ollama` | `groq` |
| Test cases | All | Not run directly — use golden pre-deploy |

Switch local `.env`:
```
LLM_PROVIDER=ollama    # for local testing
LLM_PROVIDER=groq      # for VPS (auto-set by systemd service)
```

---

## Deploy Checklist

Before running `git pull && systemctl restart pg-accountant` on VPS:

- [ ] `python tests/run_500.py` → ≥ 90% overall
- [ ] `python tests/eval_golden.py` → 100%
- [ ] No `reply_must_not_contain` violations (no technical leaks)
- [ ] DB migration runs clean: `python -m src.database.migrate_all`
- [ ] New seed data applied (if any): `python -m src.database.seed_wifi`
- [ ] `git push` succeeds with no conflicts
