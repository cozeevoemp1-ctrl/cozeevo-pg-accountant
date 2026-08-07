"""Legacy PIN-based checkout API — RETIRED 2026-08-07 (Phase 3).

All checkouts go through the authenticated v2 flow
(POST /api/v2/app/checkout/create), which recalculates and validates the
refund against deposit − maintenance − dues − deductions and enforces the
notice/forfeiture rules. This legacy stack persisted whatever refund the
client sent (audit 2026-08-06 finding D-1) and duplicated the v2 flow with
weaker validation, so every route now returns 410 like direct-checkin.

static/checkout_admin.html and static/checkout_confirm.html were deleted
with it; /admin/checkout and /checkout/{token} serve routes removed from
main.py.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/checkout", tags=["checkout"])


@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def checkout_removed(path: str):
    raise HTTPException(
        status_code=410,
        detail="Legacy checkout API removed. Use the app (POST /api/v2/app/checkout/create).",
    )
