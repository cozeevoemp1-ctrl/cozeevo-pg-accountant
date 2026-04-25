"""
scripts/migrate_media_to_supabase.py
=====================================
One-time migration: upload all existing VPS KYC/receipt/agreement files
to Supabase Storage and update DB paths to full Supabase public URLs.

Scope of DB fields updated:
  - documents.file_path          (KYC docs: selfie, id_proof, receipts...)
  - onboarding_sessions.agreement_pdf_path
  - payments.receipt_url

Run on VPS:
  python scripts/migrate_media_to_supabase.py           # dry run (default)
  python scripts/migrate_media_to_supabase.py --write   # commit changes
  python scripts/migrate_media_to_supabase.py --write --delete  # also remove local files

Env required:
  SUPABASE_URL          https://<project-ref>.supabase.co
  SUPABASE_SERVICE_KEY  service_role JWT  (or SUPABASE_KEY for anon key with RLS)
  DATABASE_URL          postgresql+asyncpg://...

VPS media root: /opt/pg-accountant/media/
VPS agreements dir: /opt/pg-accountant/static/agreements/
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

import httpx
from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# ── Config ──────────────────────────────────────────────────────────────────
SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "") or os.getenv("SUPABASE_KEY", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")

# VPS local roots — adjust if directory layout differs
VPS_MEDIA_ROOT = Path("/opt/pg-accountant/media")
VPS_STATIC_ROOT = Path("/opt/pg-accountant/static")

BUCKET_KYC = "kyc-documents"
BUCKET_AGREEMENTS = "agreements"

# ── Supabase helpers ─────────────────────────────────────────────────────────

def _headers(content_type: str | None = None) -> dict:
    h = {
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "apikey": SUPABASE_SERVICE_KEY,
    }
    if content_type:
        h["Content-Type"] = content_type
    return h


def public_url(bucket: str, path: str) -> str:
    return f"{SUPABASE_URL}/storage/v1/object/public/{bucket}/{path}"


def is_supabase_url(value: str) -> bool:
    return value.startswith("https://") and "supabase.co/storage" in value


_buckets_ensured: set[str] = set()


async def ensure_bucket(client: httpx.AsyncClient, bucket: str) -> None:
    if bucket in _buckets_ensured:
        return
    r = await client.post(
        f"{SUPABASE_URL}/storage/v1/bucket",
        headers=_headers("application/json"),
        json={"id": bucket, "name": bucket, "public": True},
    )
    if r.status_code in (200, 201, 409):
        _buckets_ensured.add(bucket)
    else:
        logger.warning("bucket create %s → %d %s", bucket, r.status_code, r.text[:100])


async def upload_file(client: httpx.AsyncClient, bucket: str, path: str,
                      data: bytes, content_type: str) -> str:
    await ensure_bucket(client, bucket)
    headers = _headers(content_type)
    headers["x-upsert"] = "true"
    r = await client.post(
        f"{SUPABASE_URL}/storage/v1/object/{bucket}/{path}",
        headers=headers,
        content=data,
    )
    if r.status_code not in (200, 201):
        raise RuntimeError(f"upload {bucket}/{path} failed {r.status_code}: {r.text[:200]}")
    return public_url(bucket, path)


# ── Path helpers ─────────────────────────────────────────────────────────────

def _content_type(filename: str) -> str:
    name = filename.lower()
    if name.endswith(".pdf"):
        return "application/pdf"
    if name.endswith(".png"):
        return "image/png"
    if name.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if name.endswith(".webp"):
        return "image/webp"
    return "application/octet-stream"


def resolve_local_path(db_value: str) -> Path | None:
    """
    Convert a DB-stored relative path to an absolute VPS path.
    Old patterns observed:
      onboarding/<token>/selfie.jpg
      onboarding/<token>/id_proof.jpg
      onboarding/<token>/staff_signature.png
      staff_signatures/<phone>.png
      agreements/2026-04/agreement_xxx.pdf       (legacy static/ prefix)
      media/onboarding/...                        (some old rows)
    """
    if not db_value or is_supabase_url(db_value):
        return None

    # Strip leading slashes / static/ / media/ prefixes
    stripped = db_value.lstrip("/")
    for prefix in ("static/", "media/"):
        if stripped.startswith(prefix):
            stripped = stripped[len(prefix):]

    # Try media root first, then static root
    candidates = [
        VPS_MEDIA_ROOT / stripped,
        VPS_STATIC_ROOT / stripped,
        VPS_STATIC_ROOT / "agreements" / Path(stripped).name,
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def supabase_path_for(db_value: str, bucket: str) -> str:
    """
    Derive the Supabase object path from the existing DB relative path.
    Keeps the same structure so existing organised paths are preserved.
    """
    stripped = db_value.lstrip("/")
    for prefix in ("static/", "media/", "onboarding/"):
        # keep onboarding/ prefix — it's part of the path
        pass
    # strip the common disk-root prefixes only
    for prefix in ("static/", "media/"):
        if stripped.startswith(prefix):
            stripped = stripped[len(prefix):]
    return stripped


# ── Migration logic ──────────────────────────────────────────────────────────

async def migrate_column(
    session: AsyncSession,
    client: httpx.AsyncClient,
    table: str,
    column: str,
    bucket: str,
    dry_run: bool,
    delete_local: bool,
) -> tuple[int, int, int]:
    """Process one (table, column) pair. Returns (found, migrated, skipped)."""
    result = await session.execute(
        text(f"SELECT id, {column} FROM {table} WHERE {column} IS NOT NULL AND {column} != ''")
    )
    rows = result.fetchall()

    found = len(rows)
    migrated = 0
    skipped = 0

    for row_id, value in rows:
        if is_supabase_url(value):
            logger.debug("[%s.%s id=%s] already Supabase URL — skip", table, column, row_id)
            skipped += 1
            continue

        local_path = resolve_local_path(value)
        if local_path is None:
            logger.warning("[%s.%s id=%s] file not found for path=%r — skip", table, column, row_id, value)
            skipped += 1
            continue

        sb_path = supabase_path_for(value, bucket)
        content_type = _content_type(local_path.name)
        new_url = public_url(bucket, sb_path)

        if dry_run:
            logger.info("[DRY] %s.%s id=%s: %s → %s", table, column, row_id, value, new_url)
            migrated += 1
            continue

        data = local_path.read_bytes()
        try:
            await upload_file(client, bucket, sb_path, data, content_type)
        except Exception as exc:
            logger.error("[%s.%s id=%s] upload failed: %s", table, column, row_id, exc)
            skipped += 1
            continue

        await session.execute(
            text(f"UPDATE {table} SET {column} = :url WHERE id = :id"),
            {"url": new_url, "id": row_id},
        )
        logger.info("  migrated %s.%s id=%s → %s", table, column, row_id, new_url)
        migrated += 1

        if delete_local:
            try:
                local_path.unlink()
                logger.debug("  deleted local %s", local_path)
            except Exception as exc:
                logger.warning("  could not delete %s: %s", local_path, exc)

    return found, migrated, skipped


async def migrate_staff_signatures(
    client: httpx.AsyncClient,
    dry_run: bool,
    delete_local: bool,
) -> tuple[int, int]:
    """Upload staff_signatures/<phone>.png files (not stored in DB — just upload them)."""
    sig_dir = VPS_MEDIA_ROOT / "staff_signatures"
    if not sig_dir.exists():
        return 0, 0

    uploaded = 0
    for f in sig_dir.glob("*.png"):
        phone = f.stem
        sb_path = f"staff-signatures/{phone}.png"
        new_url = public_url(BUCKET_KYC, sb_path)
        if dry_run:
            logger.info("[DRY] staff-sig %s → %s", f, new_url)
            uploaded += 1
            continue
        data = f.read_bytes()
        try:
            await upload_file(client, BUCKET_KYC, sb_path, data, "image/png")
            logger.info("  staff-sig %s → %s", phone, new_url)
            uploaded += 1
            if delete_local:
                f.unlink()
        except Exception as exc:
            logger.error("  staff-sig %s failed: %s", phone, exc)

    return len(list(sig_dir.glob("*.png"))) if not dry_run else uploaded, uploaded


async def main(dry_run: bool, delete_local: bool) -> None:
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        sys.exit("ERROR: SUPABASE_URL and (SUPABASE_SERVICE_KEY or SUPABASE_KEY) must be set in .env")
    if not DATABASE_URL:
        sys.exit("ERROR: DATABASE_URL must be set in .env")

    logger.info("=== migrate_media_to_supabase %s ===", "(DRY RUN)" if dry_run else "(WRITE)")

    engine = create_async_engine(DATABASE_URL, echo=False)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with httpx.AsyncClient(timeout=60.0) as client:
        async with AsyncSessionLocal() as session:
            totals: dict[str, tuple[int, int, int]] = {}

            # documents.file_path — KYC docs (selfie, id_proof, etc.)
            found, migrated, skipped = await migrate_column(
                session, client, "documents", "file_path", BUCKET_KYC, dry_run, delete_local
            )
            totals["documents.file_path"] = (found, migrated, skipped)

            # onboarding_sessions.agreement_pdf_path
            found, migrated, skipped = await migrate_column(
                session, client, "onboarding_sessions", "agreement_pdf_path",
                BUCKET_AGREEMENTS, dry_run, delete_local
            )
            totals["onboarding_sessions.agreement_pdf_path"] = (found, migrated, skipped)

            # payments.receipt_url
            found, migrated, skipped = await migrate_column(
                session, client, "payments", "receipt_url", BUCKET_KYC, dry_run, delete_local
            )
            totals["payments.receipt_url"] = (found, migrated, skipped)

            if not dry_run:
                await session.commit()
                logger.info("DB committed.")

        # Staff signatures (no DB update, just upload)
        sig_found, sig_uploaded = await migrate_staff_signatures(client, dry_run, delete_local)
        totals["staff_signatures (file-only)"] = (sig_found, sig_uploaded, sig_found - sig_uploaded)

    logger.info("\n=== Summary ===")
    for label, (found, migrated, skipped) in totals.items():
        logger.info("  %-45s found=%d  migrated=%d  skipped=%d", label, found, migrated, skipped)

    if dry_run:
        logger.info("\nDry run complete. Re-run with --write to apply changes.")
    else:
        logger.info("\nMigration complete.")
        if not delete_local:
            logger.info("Local files NOT deleted. Re-run with --delete to remove them after verification.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate VPS media files to Supabase Storage")
    parser.add_argument("--write", action="store_true", help="Apply changes (default: dry run)")
    parser.add_argument("--delete", action="store_true", help="Delete local files after successful upload")
    args = parser.parse_args()

    asyncio.run(main(dry_run=not args.write, delete_local=args.delete))
