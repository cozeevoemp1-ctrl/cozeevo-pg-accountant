"""
src/utils/demo.py
==================
DEMO_MODE — lets a second deployment of this same codebase run as a public demo
against a fresh, empty database with zero of the real business's hardcoded
figures or outbound messaging.

Read once via `is_demo_mode()`. Off by default — production behaviour is
unchanged unless the env var is explicitly set.
"""
from __future__ import annotations

import os


def is_demo_mode() -> bool:
    """True when DEMO_MODE=1 / true (case-insensitive) in the environment."""
    return os.getenv("DEMO_MODE", "0").strip().lower() in ("1", "true")
