"""Top-level router for /api/v2/app/* — new JSON API for the Owner PWA.

Mounted alongside existing /webhook (WhatsApp bot untouched).
All endpoints under this router require Supabase JWT via get_current_user.
"""
from fastapi import APIRouter, Depends

from src.api.v2.auth import AppUser, get_current_user
from src.api.v2.payments import router as payments_router
from src.api.v2.reporting import router as reporting_router
from src.database.field_registry import fields_for_pwa

router = APIRouter(prefix="/api/v2/app", tags=["app"])

router.include_router(payments_router)
router.include_router(reporting_router)


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
