"""Pydantic schemas for /api/v2/app/reporting/*."""
from pydantic import BaseModel


class CollectionSummaryResponse(BaseModel):
    period_month: str
    expected: int                          # pure_rent_expected + maintenance_expected
    collected: int                         # = expected - pending (obligation settled)
    pending: int
    collection_pct: int                    # collected / expected * 100
    pure_rent_expected: int                # SUM(agreed_rent + adjustment) for active tenants
    maintenance_expected: int
    rent_collected: int                    # period-scoped rent payments
    maintenance_collected: int
    prior_dues_collected: int              # cash received this month for prior periods
    cash_received_for_current_period: int  # cash received this month for this period
    future_advances_collected: int         # cash received this month for future periods
    deposits_received: int
    booking_advances: int
    overdue_count: int
    method_breakdown: dict[str, int] = {}
