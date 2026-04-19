"""Supabase JWT auth dependency for /api/v2/app/* routes.

Validates the JWT using SUPABASE_JWT_SECRET (HS256, audience="authenticated").
Returns an AppUser dataclass with user_id, phone, role, org_id.

Roles expected: admin | staff | tenant. Defaults to tenant if unset.
Org ID defaults to 1 (Cozeevo) if unset.
"""
import logging
import os
from dataclasses import dataclass

import jwt
from fastapi import Header, HTTPException

logger = logging.getLogger(__name__)

SUPABASE_JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET", "")


@dataclass
class AppUser:
    user_id: str
    phone: str
    role: str
    org_id: int


def get_current_user(authorization: str = Header(default=None)) -> AppUser:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    secret = os.environ.get("SUPABASE_JWT_SECRET", SUPABASE_JWT_SECRET)
    if not secret:
        raise HTTPException(status_code=500, detail="SUPABASE_JWT_SECRET not configured")
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience="authenticated",
        )
    except jwt.PyJWTError as e:
        logger.warning("JWT validation failed: %s", e)
        raise HTTPException(status_code=401, detail="invalid token")
    meta = payload.get("user_metadata") or {}
    try:
        org_id_val = int(meta.get("org_id", 1))
    except (TypeError, ValueError):
        org_id_val = 1
    return AppUser(
        user_id=payload.get("sub", ""),
        phone=payload.get("phone", ""),
        role=meta.get("role", "tenant"),
        org_id=org_id_val,
    )
