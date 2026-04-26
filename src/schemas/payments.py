"""Pydantic schemas for /api/v2/app/payments."""
from typing import Literal, Optional

from pydantic import BaseModel, Field


class PaymentCreate(BaseModel):
    tenant_id: int = Field(gt=0, description="Tenant PK — endpoint resolves active tenancy")
    amount: int = Field(gt=0, description="Amount in rupees (no paise)")
    method: Literal["UPI", "CASH", "BANK", "CARD", "OTHER"] = "CASH"
    for_type: Literal["rent", "deposit", "maintenance", "booking", "adjustment"] = "rent"
    period_month: str = Field(
        pattern=r"^\d{4}-\d{2}$",
        description="Month as YYYY-MM",
        examples=["2026-04"],
    )
    notes: str = ""


class PaymentResponse(BaseModel):
    payment_id: int
    new_balance: float
    receipt_sent: bool = False
