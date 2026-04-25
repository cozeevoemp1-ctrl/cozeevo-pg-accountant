"""
src/services/storage.py
========================
Supabase Storage wrapper for KYC documents and agreement PDFs.

Buckets (both public, pre-created via SQL migration):
  kyc-documents  — selfie, id_proof, signature, staff_signature per onboarding token
  agreements     — signed rental agreement PDFs

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
    """Return the public URL for a Supabase Storage object."""
    return f"{SUPABASE_URL}/storage/v1/object/public/{bucket}/{path}"


def is_supabase_url(value: str) -> bool:
    """True if value is already a full Supabase Storage URL (not a local relative path)."""
    return value.startswith("https://") and "supabase.co/storage" in value


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
            json={"id": bucket, "name": bucket, "public": True},
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
