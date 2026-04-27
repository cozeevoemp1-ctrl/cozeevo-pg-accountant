"""Pydantic schemas for /api/v2/app/reporting/*."""
from pydantic import BaseModel


class CollectionSummaryResponse(BaseModel):
    period_month: str
    expected: int
    collected: int
    pending: int
    collection_pct: int
    rent_collected: int
    maintenance_collected: int
    deposits_received: int
    booking_advances: int
    overdue_count: int
    method_breakdown: dict[str, int] = {}
