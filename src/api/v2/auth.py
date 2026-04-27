"""Supabase JWT auth for /api/v2/app/* routes.

Verifies JWTs using Supabase's JWKS endpoint — supports both
the new ECC (ES256) keys and legacy HS256 shared-secret keys.
"""
import logging
import os
from dataclasses import dataclass
from functools import lru_cache

import jwt
from jwt import PyJWKClient
from fastapi import Header, HTTPException

logger = logging.getLogger(__name__)


@dataclass
class AppUser:
    user_id: str
    phone: str
    role: str
    org_id: int


@lru_cache(maxsize=1)
def _jwks_client() -> PyJWKClient:
    supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    if not supabase_url:
        raise RuntimeError("SUPABASE_URL not configured")
    return PyJWKClient(f"{supabase_url}/auth/v1/.well-known/jwks.json", cache_keys=True)


def _decode_token(token: str) -> dict:
    # Try JWKS (ES256 / RS256 — Supabase current keys)
    try:
        client = _jwks_client()
        signing_key = client.get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256", "RS256"],
            audience="authenticated",
        )
    except Exception:
        pass

    # Fall back to legacy HS256 shared secret
    secret = os.environ.get("SUPABASE_JWT_SECRET", "")
    if secret:
        try:
            return jwt.decode(token, secret, algorithms=["HS256"], audience="authenticated")
        except jwt.PyJWTError:
            pass

    raise jwt.InvalidTokenError("token verification failed")


def get_current_user(authorization: str = Header(default=None)) -> AppUser:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        payload = _decode_token(token)
    except Exception as e:
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
