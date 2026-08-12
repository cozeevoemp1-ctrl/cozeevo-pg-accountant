"""
src/services/storage.py
========================
Supabase Storage wrapper for KYC documents and agreement PDFs.

Buckets (PRIVATE — tenant PII; read only via create_signed_url/sign_stored_url):
  kyc-documents  — selfie, id_proof, signature, staff_signature per onboarding token
  agreements     — signed rental agreement PDFs
  receipts        — payment receipt screenshots

Env vars (one of these pairs must be set):
  SUPABASE_URL + SUPABASE_SERVICE_KEY  (preferred — service_role JWT, full access)
  SUPABASE_URL + SUPABASE_KEY          (anon JWT — works with RLS policies on storage.objects)
"""
from __future__ import annotations

import os
from typing import Optional

import httpx
from loguru import logger

SUPABASE_URL: str = os.getenv("SUPABASE_URL", "").rstrip("/")
# Prefer service_role key; fall back to anon key (works with RLS policies set on storage.objects)
SUPABASE_SERVICE_KEY: str = (
    os.getenv("SUPABASE_SERVICE_KEY", "")
    or os.getenv("SUPABASE_KEY", "")
)

BUCKET_KYC = "kyc-documents"
BUCKET_AGREEMENTS = "agreements"
BUCKET_RECEIPTS = "receipts"

_BUCKETS_CREATED: set[str] = set()


def _headers(content_type: Optional[str] = None) -> dict:
    h = {
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "apikey": SUPABASE_SERVICE_KEY,
    }
    if content_type:
        h["Content-Type"] = content_type
    return h


def public_url(bucket: str, path: str) -> str:
    """
    Return the (legacy) public URL for a Supabase Storage object.
    Buckets are now PRIVATE — this URL will 403. Kept only so historic values
    stored in the DB remain parseable by sign_stored_url(). New callers must
    use create_signed_url()/sign_stored_url() instead.
    """
    return f"{SUPABASE_URL}/storage/v1/object/public/{bucket}/{path}"


def is_supabase_url(value: str) -> bool:
    """True if value is already a full Supabase Storage URL (not a local relative path)."""
    return value.startswith("https://") and "supabase.co/storage" in value


def _split_bucket_path(stored: str) -> Optional[tuple[str, str]]:
    """Extract (bucket, path) from a stored Supabase object URL (public or signed)."""
    if not stored or not is_supabase_url(stored):
        return None
    for marker in ("/object/public/", "/object/sign/"):
        if marker in stored:
            tail = stored.split(marker, 1)[1].split("?", 1)[0]  # drop any ?token=
            bucket, _, path = tail.partition("/")
            if bucket and path:
                return bucket, path
    return None


async def create_signed_url(bucket: str, path: str, expires_in: int = 3600) -> str:
    """Return a short-lived signed URL for a private-bucket object (default 1h)."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        raise RuntimeError("SUPABASE_URL and (SUPABASE_SERVICE_KEY or SUPABASE_KEY) must be set in .env")
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(
            f"{SUPABASE_URL}/storage/v1/object/sign/{bucket}/{path}",
            headers=_headers("application/json"),
            json={"expiresIn": expires_in},
        )
        if r.status_code != 200:
            raise RuntimeError(f"[Storage] sign {bucket}/{path} failed {r.status_code}: {r.text[:200]}")
    return f"{SUPABASE_URL}/storage/v1" + r.json()["signedURL"]


async def sign_stored_url(stored: Optional[str], expires_in: int = 3600) -> Optional[str]:
    """
    Turn a value previously produced by upload()/public_url() (a full Supabase
    public URL) into a fresh short-lived signed URL.

    Passthrough-safe: non-Supabase values (local /static paths, base64 data URLs,
    empty/None) are returned unchanged, so this can wrap ANY stored file
    reference. Fails OPEN (returns the original value) if signing errors, so a
    Storage hiccup degrades one image rather than 500-ing the whole response.
    """
    bp = _split_bucket_path(stored or "")
    if not bp:
        return stored
    try:
        return await create_signed_url(bp[0], bp[1], expires_in)
    except Exception as e:
        logger.warning("[Storage] sign_stored_url failed for %s: %s", (stored or "")[:80], e)
        return stored


async def ensure_bucket(bucket: str) -> None:
    """Mark bucket as ready (buckets are pre-created via SQL). Skips REST call when using anon key."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        return
    if bucket in _BUCKETS_CREATED:
        return
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(
            f"{SUPABASE_URL}/storage/v1/bucket",
            headers=_headers("application/json"),
            # PRIVATE — objects are tenant PII (govt IDs, selfies, signatures,
            # signed agreements). Access only via create_signed_url()/sign_stored_url().
            json={"id": bucket, "name": bucket, "public": False},
        )
        if r.status_code in (200, 201, 409):  # 409 = already exists
            _BUCKETS_CREATED.add(bucket)
        else:
            logger.warning("[Storage] bucket create %s → %d %s", bucket, r.status_code, r.text[:120])


async def upload(bucket: str, path: str, data: bytes, content_type: str) -> str:
    """
    Upload bytes to Supabase Storage. Returns the public URL.
    Uses x-upsert=true so re-uploads overwrite (idempotent).
    """
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        raise RuntimeError("SUPABASE_URL and (SUPABASE_SERVICE_KEY or SUPABASE_KEY) must be set in .env")

    await ensure_bucket(bucket)

    headers = _headers(content_type)
    headers["x-upsert"] = "true"

    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(
            f"{SUPABASE_URL}/storage/v1/object/{bucket}/{path}",
            headers=headers,
            content=data,
        )
        if r.status_code not in (200, 201):
            raise RuntimeError(f"[Storage] upload {bucket}/{path} failed {r.status_code}: {r.text[:200]}")

    url = public_url(bucket, path)
    logger.info("[Storage] uploaded %s/%s → %s", bucket, path, url)
    return url


async def download(bucket: str, path: str) -> bytes:
    """Download a file from Supabase Storage. Returns raw bytes."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        raise RuntimeError("SUPABASE_URL and (SUPABASE_SERVICE_KEY or SUPABASE_KEY) must be set in .env")
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(
            f"{SUPABASE_URL}/storage/v1/object/{bucket}/{path}",
            headers=_headers(),
        )
        if r.status_code != 200:
            raise FileNotFoundError(f"[Storage] {bucket}/{path} not found ({r.status_code})")
        return r.content


async def delete(bucket: str, paths: list[str]) -> None:
    """Delete a list of file paths from a bucket (bulk delete)."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY or not paths:
        return
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.delete(
            f"{SUPABASE_URL}/storage/v1/object/{bucket}",
            headers=_headers("application/json"),
            json={"prefixes": paths},
        )
        if r.status_code not in (200, 204):
            logger.warning("[Storage] delete from %s failed %d: %s", bucket, r.status_code, r.text[:120])
        else:
            logger.info("[Storage] deleted %d file(s) from %s", len(paths), bucket)
