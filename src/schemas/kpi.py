"""Pydantic schemas for /api/v2/app/reporting/kpi and /api/v2/app/activity/recent."""
from typing import List
from pydantic import BaseModel


class KpiResponse(BaseModel):
    occupied_beds: int
    total_beds: int
    vacant_beds: int
    occupancy_pct: float
    active_tenants: int
    no_show_count: int
    checkins_today: int
    checkouts_today: int
    overdue_tenants: int
    overdue_amount: float


class ActivityItem(BaseModel):
    tenant_name: str
    room_number: str
    amount: int
    method: str
    for_type: str
    payment_date: str  # ISO date string


class ActivityResponse(BaseModel):
    items: List[ActivityItem]
