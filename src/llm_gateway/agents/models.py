"""Pydantic response models for all PydanticAI agents."""
from __future__ import annotations

from pydantic import BaseModel


class ConversationResult(BaseModel):
    """Response from ConversationAgent — covers classify, converse, options, corrections."""
    action: str                       # "classify", "ask_options", "clarify", "converse", "correct"
    intent: str | None = None
    confidence: float = 0.0
    entities: dict = {}
    options: list[str] | None = None  # intent options when 0.6-0.9
    correction: dict | None = None    # {field, old, new}
    reply: str | None = None          # natural language to user
    reasoning: str = ""               # why this classification — used by LearningAgent


class MerchantClassification(BaseModel):
    """Response from merchant/expense classification."""
    category: str
    confidence: float
    reason: str


class BankStatementRow(BaseModel):
    """Parsed bank statement row with classification."""
    date: str
    description: str
    amount: float
    txn_type: str                     # credit/debit
    category: str | None = None
    tenant_match: str | None = None
    confidence: float = 0.0
