---
name: feedback_schema_sync
description: When backend adds a field, update TypeScript schema in the SAME commit
metadata:
  type: feedback
---

## Rule
**When backend returns a new field, ALWAYS update the TypeScript schema in the same commit.**

## Why
Session C audit fix added `notices_incoming` calculation to the KPI endpoint backend, but forgot to add it to the `KpiResponse` TypeScript interface. This caused:
- PWA build failure on VPS (not caught locally)
- Notices, Bookings, Pre-Register pages crashed with "client-side exception"
- User-facing outage until manually fixed

The build should have failed locally too, but didn't — likely skipped type-checking locally or didn't rebuild after backend changes.

## How to apply
- **Before committing backend changes:** Check if any new response fields are being added
- **Update both in same commit:**
  1. Backend response model / return statement
  2. TypeScript interface in `web/lib/api.ts`
- **Test locally:** `npm run build` to catch TypeScript errors before pushing
- **Code review:** Check backend commits for new fields before merging

## Related lesson
[[feedback_occupancy_service]] — similar issue with duplicated calculations diverging
