from pydantic import BaseModel


class TranscribeResponse(BaseModel):
    text: str
    language: str
    duration_seconds: float


class IntentRequest(BaseModel):
    transcript: str


class PaymentIntentResponse(BaseModel):
    intent: str  # "log_payment" | "check_balance" | "unknown"
    amount: int | None = None
    tenant_name: str | None = None
    tenant_room: str | None = None
    method: str | None = None
    for_type: str = "rent"
