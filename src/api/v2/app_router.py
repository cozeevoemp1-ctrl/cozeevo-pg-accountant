"""Top-level router for /api/v2/app/* — new JSON API for the Owner PWA.

Mounted alongside existing /webhook (WhatsApp bot untouched).
All endpoints under this router require Supabase JWT via get_current_user.
"""
from fastapi import APIRouter, Depends

from src.api.v2.auth import AppUser, get_current_user
from src.api.v2.auth_hooks import router as auth_hooks_router
from src.api.v2.checkin import router as checkin_router
from src.api.v2.checkout import router as checkout_router
from src.api.v2.kpi import activity_router, router as kpi_router
from src.api.v2.payments import router as payments_router
from src.api.v2.notices import router as notices_router
from src.api.v2.reminders import router as reminders_router
from src.api.v2.checkouts import router as checkouts_router
from src.api.v2.rooms import router as rooms_router
from src.api.v2.reporting import router as reporting_router
from src.api.v2.tenants import router as tenants_router
from src.api.v2.finance import router as finance_router
from src.api.v2.blacklist import router as blacklist_router
from src.api.v2.analytics import router as analytics_router
from src.api.v2.bookings import router as bookings_router
from src.api.v2.operations import router as operations_router
from src.database.field_registry import fields_for_pwa

router = APIRouter(prefix="/api/v2/app", tags=["app"])

router.include_router(auth_hooks_router)
router.include_router(kpi_router)
router.include_router(activity_router)
router.include_router(checkin_router)
router.include_router(checkout_router)
router.include_router(payments_router)
router.include_router(reporting_router)
router.include_router(tenants_router)
router.include_router(notices_router)
router.include_router(reminders_router)
router.include_router(checkouts_router)
router.include_router(rooms_router)
router.include_router(finance_router)
router.include_router(blacklist_router)
router.include_router(analytics_router)
router.include_router(bookings_router)
router.include_router(operations_router)


@router.get("/health")
def health(user: AppUser = Depends(get_current_user)):
    return {
        "status": "ok",
        "user_id": user.user_id,
        "role": user.role,
        "org_id": user.org_id,
    }


@router.get("/field-registry")
def field_registry(_user: AppUser = Depends(get_current_user)):
    return {"fields": fields_for_pwa()}


@router.get("/config")
async def app_config(_user: AppUser = Depends(get_current_user)):
    """Business-rule constants for the frontend — never hardcode these in UI
    (spec rule 6). notice_by_day from services/property_logic (single source);
    total_beds derived live from the rooms table (SaaS-ready, no constant).
    """
    from services.property_logic import NOTICE_BY_DAY
    from src.database.db_manager import get_session
    from src.services.occupancy import get_total_revenue_beds

    async with get_session() as session:
        total_beds = await get_total_revenue_beds(session)
    return {"notice_by_day": NOTICE_BY_DAY, "total_beds": total_beds}
