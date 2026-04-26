"""GET /api/v2/app/reporting/collection — collection summary for the Owner PWA."""
import re

from fastapi import APIRouter, Depends, HTTPException

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
