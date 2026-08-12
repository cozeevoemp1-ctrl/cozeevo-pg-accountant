"""
UI-consistency gate — enforces docs/UI_SYSTEM.md mechanically (pre-push hook).

Fails (exit 1) if any file in web/app or web/components:
  1. uses a bracket-class hex that has a token  (bg-[#F6F5F0] -> bg-bg, etc.)
  2. defines a local INR formatter              (use @/lib/format)
  3. formats currency inline                   (toLocaleString("en-IN"))
  4. hand-rolls an overlay                     (fixed inset-0 outside ui/modal.tsx)
  5. re-derives the API base URL               (NEXT_PUBLIC_API_URL outside lib/api.ts)

Run: py -3 scripts/check_ui_consistency.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"

# Orphaned finance components pending restore-vs-delete decision (see UI_SYSTEM.md debt)
ORPHANS = {"cash-tab.tsx", "upi-reconcile-tab.tsx", "reconcile-card.tsx",
           "unit-economics-card.tsx", "pnl-cards.tsx"}

# Files allowed to contain `fixed inset-0` (they ARE the overlay layer / documented debt)
OVERLAY_ALLOW = {"modal.tsx", "confirmation-card.tsx", "voice-sheet.tsx",
                 "onboarding-voice-sheet.tsx", "date-picker-input.tsx",
                 "datetime-picker-input.tsx"}

TOKENED_HEX = "F6F5F0|F0EDE9|E0DDD8|E2DEDD|EF1F9C|00AEED|0F0E0D|6F655D|C25000|FCE2EE"

CHECKS: list[tuple[str, re.Pattern, str]] = [
    ("tokened hex in className",
     re.compile(r"\[#(?:%s)\]" % TOKENED_HEX, re.I),
     "use the Tailwind token (see docs/UI_SYSTEM.md color table)"),
    ("local INR formatter",
     re.compile(r"function\s+(?:_?inr|fmtINR|rupee\w*)\s*\(|const\s+(?:_?inr|fmtINR)\s*="),
     "import rupee/rupeeExact/rupeeShort from @/lib/format"),
    ("inline en-IN currency",
     re.compile(r'toLocaleString\(\s*["\']en-IN'),
     "import a formatter from @/lib/format"),
    ("hand-rolled overlay",
     # real modal backdrops carry bg-black/NN; transparent click-catchers are fine
     re.compile(r'className="[^"]*fixed inset-0[^"]*bg-black'),
     "use <Modal>/<Sheet> from @/components/ui/modal"),
    ("re-derived API base URL",
     re.compile(r"NEXT_PUBLIC_API_URL"),
     "import BASE_URL from @/lib/api"),
]


def main() -> int:
    violations = []
    for path in list((WEB / "app").rglob("*.tsx")) + list((WEB / "components").rglob("*.tsx")):
        if path.name in ORPHANS:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for name, pattern, fix in CHECKS:
            if name == "hand-rolled overlay" and path.name in OVERLAY_ALLOW:
                continue
            if name == "re-derived API base URL" and path.name == "api.ts":
                continue
            for m in pattern.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                rel = path.relative_to(WEB.parent)
                violations.append(f"  {rel}:{line}  [{name}]  -> {fix}")
    if violations:
        print("[ui-check] docs/UI_SYSTEM.md violations — rebuilt instead of reused:")
        print("\n".join(sorted(set(violations))))
        print(f"[ui-check] {len(violations)} violation(s). Fix or (rarely) allowlist in scripts/check_ui_consistency.py.")
        return 1
    print("[ui-check] UI consistency OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
