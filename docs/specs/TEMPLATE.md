# Spec NN — <feature name>

> Copy this file to `docs/specs/NN-<kebab-name>.md` before building any non-trivial
> feature. Invocation prompt stays trivial: "Read docs/specs/NN-x.md, mark it
> in-progress in memory/project_pending_tasks.md, implement exactly as specified."

## Goal
One or two sentences: what exists when this unit is done.

## Design decisions
The choices already made (and why) — libraries, patterns, data model. Reference
existing code to reuse (file paths). Never invent a new pattern when one exists.

## Implementation
Concrete steps. Name the files to touch. One layer/concern per spec — if it
spans backend + frontend, split into two specs.

## Out of scope
Explicit list of what NOT to build or touch. This is the section that prevents
scope drift — always fill it.

## Verification checklist
- [ ] Compile/typecheck/lint pass
- [ ] Golden suite (if bot behavior changed): `python tests/eval_golden.py`
- [ ] Manual test of the actual flow (browser/WhatsApp) — not just the build
- [ ] Storage-layer check: DB row + Sheet mirror actually written
- [ ] Do it twice: the same action repeated behaves correctly (idempotency)
- [ ] Dependency sync rule run (CLAUDE.md checklist)
