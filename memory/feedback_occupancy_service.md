---
name: feedback_occupancy_service
description: Use src/services/occupancy.py for all occupancy calculations — don't duplicate
metadata:
  type: feedback
---

## Rule
**All occupancy calculations go through `src/services/occupancy.py`. Never duplicate the calculation in multiple endpoints.**

## Why
Session D found that KPI and Analytics endpoints were calculating occupied beds differently:
- KPI: active + no_shows (checkin_date <= target)
- Analytics: active only (missing no_shows)
- Result: KPI tile and Finance chart showed different occupancy % for the same date

Root cause: duplicate code in two places → divergence over time. Temporary fixes made them match, but fragile.

**Permanent fix:** Extracted canonical service with three functions:
- `get_total_revenue_beds(session)` → total beds
- `get_occupied_beds(session, target_date)` → active + no_shows
- `get_occupancy_pct(session, target_date)` → percentage

Both `src/api/v2/kpi.py` and `src/api/v2/analytics.py` now call these functions.

## How to apply
- **Adding occupancy calculation to a new endpoint?** Import from `src/services/occupancy.py`
- **Changing occupancy logic?** Update `src/services/occupancy.py` — both endpoints auto-update
- **Never:** Duplicate occupancy SQL queries across files
- **Never:** Calculate occupied beds inline in endpoint code

## Location
`src/services/occupancy.py` — three functions, fully documented, includes both active and no_show counts.

## Related lesson
[[feedback_schema_sync]] — similar issue with schema divergence
