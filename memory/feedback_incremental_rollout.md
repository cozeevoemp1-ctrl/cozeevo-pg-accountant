---
name: Incremental Rollout Required
description: Big changes must use feature flags and not touch handler flows — learned from 2-day confirm bug
type: feedback
---

Never change classification AND handler flows in the same release. The contact/confirm bug (v1.20.0) took 2 days to fix because multiple things changed at once, failures were silent (return None), and there was no way to roll back.

**Why:** Silent failures in chained flows (regex → classification → pending state → confirm) are nearly impossible to debug when multiple layers changed simultaneously.

**How to apply:**
- Feature flag for any new integration (USE_PYDANTIC_AGENTS=false, flip when tested)
- New code sits BESIDE old code, doesn't replace it until verified
- Run golden test suite against new path before wiring into handlers
- Classification changes and handler changes = separate commits, separate deploys
- Log every decision point so "why did it do that?" is always answerable
