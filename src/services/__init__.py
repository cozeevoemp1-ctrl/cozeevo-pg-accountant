"""
src/services/__init__.py
=========================
Public exports for the services layer.

Services are pure business logic — no WhatsApp, no HTTP, no message
formatting. Both the bot handlers and the owner PWA import from here.
"""
from src.services.payments import log_payment, PaymentResult
from src.services.audit import write_audit_entry

__all__ = [
    "log_payment",
    "PaymentResult",
    "write_audit_entry",
]
