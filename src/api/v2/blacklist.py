"""
Blacklist management API — admin/power_user only.

GET  /api/v2/app/blacklist          — list all active entries
POST /api/v2/app/blacklist          — add an entry  {name?, phone?, reason}
DELETE /api/v2/app/blacklist/{id}   — soft-delete (is_active=False)
"""
from fastapi import APIRouter, Depends, HTTPException
from src.api.v2.auth import AppUser, get_current_user
from src.database.db_manager import get_session
from src.services.blacklist import (
    add_to_blacklist,
    list_blacklist,
    remove_from_blacklist,
)

router = APIRouter(prefix="/blacklist", tags=["blacklist"])

_ALLOWED = ("admin", "power_user")


@router.get("")
async def get_blacklist(user: AppUser = Depends(get_current_user)):
    if user.role not in _ALLOWED:
        raise HTTPException(403, "Admins only")
    async with get_session() as session:
        entries = await list_blacklist(session)
    return {"blacklist": entries, "count": len(entries)}


@router.post("")
async def post_blacklist(body: dict, user: AppUser = Depends(get_current_user)):
    if user.role not in _ALLOWED:
        raise HTTPException(403, "Admins only")
    name = (body.get("name") or "").strip() or None
    phone = (body.get("phone") or "").strip() or None
    reason = (body.get("reason") or "").strip()
    if not name and not phone:
        raise HTTPException(400, "Provide name or phone (or both)")
    if not reason:
        raise HTTPException(400, "reason is required")
    async with get_session() as session:
        new_id = await add_to_blacklist(
            session, name=name, phone=phone, reason=reason, added_by=user.user_id
        )
    return {"id": new_id, "name": name, "phone": phone, "status": "blacklisted"}


@router.delete("/{blacklist_id}")
async def delete_blacklist(blacklist_id: int, user: AppUser = Depends(get_current_user)):
    if user.role not in _ALLOWED:
        raise HTTPException(403, "Admins only")
    async with get_session() as session:
        ok = await remove_from_blacklist(session, blacklist_id)
    if not ok:
        raise HTTPException(404, "Entry not found or already removed")
    return {"id": blacklist_id, "status": "removed"}
