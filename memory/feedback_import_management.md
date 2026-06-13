---
name: feedback_import_management
description: Always import required SQLAlchemy functions at file top — missing imports cause endpoint crashes
metadata:
  type: feedback
---

## Rule
**Import all SQLAlchemy functions used in the file at the TOP. Missing imports cause silent endpoint crashes at runtime.**

## Why
Session D found that `cancel_session()` in `onboarding_router.py` used `text()` function (line 761) but never imported it. Result:
- Endpoint crashed when called: `NameError: name 'text' is not defined`
- Users saw "Failed to fetch" with no clear error
- Root cause was invisible until checking VPS logs

This pattern repeated across multiple files. Need systematic import checking.

## How to apply
**Before closing any PR with SQLAlchemy code:**
1. Search file for all `sqlalchemy` usage: `text()`, `func.*`, `case()`, `literal_column()`, `exists()`, etc.
2. Check line 1-30 imports include every function used
3. If adding a new query type, add import at top immediately
4. Test the endpoint locally before pushing (crashes on line 761 would fail in test)

## What was imported wrong
- Missing: `from sqlalchemy import text`
- Used in: `src/api/onboarding_router.py:761`
- Impact: Cancel booking endpoint crashed

## Fix
Added to imports (line 18):
```python
from sqlalchemy import select, update, text
```

## Related lesson
[[feedback_dependency_sync]] — similar issue with dependencies diverging across files

## Prevention checklist
- [ ] Grep file for `sqlalchemy.` usage
- [ ] Verify import at line 1-30
- [ ] Run endpoint locally
- [ ] Check VPS logs for NameError after deploy
