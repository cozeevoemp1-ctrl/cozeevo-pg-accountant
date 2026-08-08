"""GET /api/v2/app/reporting/collection — collection summary for the Owner PWA."""
import re
from datetime import date as _date
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.v2.auth import AppUser, get_current_user
from src.database.db_manager import get_session
from src.schemas.reporting import CollectionSummaryResponse
from src.services.reporting import collection_summary

router = APIRouter(prefix="/reporting")

_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


@router.get("/collection", response_model=CollectionSummaryResponse)
async def get_collection_summary(
    period_month: str,
    user: AppUser = Depends(get_current_user),
):
    """Return collection summary for a given month (YYYY-MM)."""
    if not _MONTH_RE.match(period_month):
        raise HTTPException(status_code=422, detail="period_month must be YYYY-MM")

    async with get_session() as session:
        summary = await collection_summary(period_month=period_month, session=session)

    return CollectionSummaryResponse(**summary.__dict__)


@router.get("/collection-history", response_model=List[CollectionSummaryResponse])
async def get_collection_history(
    months: int = Query(default=6, ge=1, le=12),
    user: AppUser = Depends(get_current_user),
):
    """Return collection summary for the last N months (newest first)."""
    today = _date.today()
    results = []
    async with get_session() as session:
        for i in range(months):
            m = today.month - i
            y = today.year
            while m <= 0:
                m += 12
                y -= 1
            period = f"{y}-{m:02d}"
            s = await collection_summary(period_month=period, session=session)
            results.append(CollectionSummaryResponse(**s.__dict__))
    return results
