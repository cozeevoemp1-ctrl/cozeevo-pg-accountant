"""
Download and save WhatsApp media files to local storage.
Uses WhatsApp Cloud API to retrieve media by ID.
"""
import os
import httpx
from pathlib import Path
from datetime import datetime
from loguru import logger

MEDIA_DIR = Path(os.getenv("DATA_DOCUMENTS_DIR", "./data/documents"))
WA_TOKEN = os.getenv("WHATSAPP_TOKEN", "")


async def download_whatsapp_media(
    media_id: str,
    mime_type: str,
    subfolder: str = "id_proofs",
    filename_prefix: str = "",
) -> str | None:
    """
    Download media from WhatsApp Cloud API, save to disk.
    Returns relative file path or None on failure.
    """
    try:
        headers = {"Authorization": f"Bearer {WA_TOKEN}"}
        async with httpx.AsyncClient(timeout=30) as client:
            # Step 1: Get media URL from WhatsApp
            resp = await client.get(
                f"https://graph.facebook.com/v21.0/{media_id}",
                headers=headers,
            )
            resp.raise_for_status()
            media_url = resp.json().get("url")

            if not media_url:
                logger.warning(f"No URL returned for media_id {media_id}")
                return None

            # Step 2: Download the actual file
            file_resp = await client.get(media_url, headers=headers)
            file_resp.raise_for_status()

        # Step 3: Save to disk
        ext = _mime_to_ext(mime_type)
        month_dir = datetime.now().strftime("%Y-%m")
        save_dir = MEDIA_DIR / subfolder / month_dir
        save_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{filename_prefix}_{timestamp}{ext}" if filename_prefix else f"{timestamp}{ext}"
        file_path = save_dir / filename

        file_path.write_bytes(file_resp.content)
        logger.info(f"Media saved: {file_path} ({len(file_resp.content)} bytes)")

        return str(file_path.relative_to(MEDIA_DIR))

    except Exception as e:
        logger.error(f"Media download failed: {e}")
        return None


async def download_whatsapp_media_bytes(media_id: str) -> tuple[bytes, str] | None:
    """
    Download media from WhatsApp Cloud API, return (raw_bytes, mime_type).
    Returns None on failure. Does NOT save to disk.
    """
    try:
        headers = {"Authorization": f"Bearer {WA_TOKEN}"}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"https://graph.facebook.com/v21.0/{media_id}",
                headers=headers,
            )
            resp.raise_for_status()
            meta = resp.json()
            media_url = meta.get("url")
            mime_type = meta.get("mime_type", "application/octet-stream")
            if not media_url:
                logger.warning("No URL returned for media_id %s", media_id)
                return None
            file_resp = await client.get(media_url, headers=headers)
            file_resp.raise_for_status()
        return file_resp.content, mime_type
    except Exception as e:
        logger.error("Media download failed for %s: %s", media_id, e)
        return None


async def upload_staff_kyc_to_supabase(
    media_id: str,
    staff_id: int,
    mime_type: str | None = None,
) -> str | None:
    """
    Download WhatsApp media and upload to Supabase Storage (kyc-documents bucket).
    Returns the public URL, or None on failure.
    """
    from src.services.storage import upload as _storage_upload, BUCKET_KYC
    result = await download_whatsapp_media_bytes(media_id)
    if result is None:
        return None
    raw_bytes, detected_mime = result
    effective_mime = mime_type or detected_mime
    ext = _mime_to_ext(effective_mime)
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = f"staff/{staff_id}_{ts}{ext}"
    try:
        url = await _storage_upload(BUCKET_KYC, path, raw_bytes, effective_mime)
        return url
    except Exception as e:
        logger.error("Supabase upload failed for staff %s KYC: %s", staff_id, e)
        return None


def _mime_to_ext(mime_type: str) -> str:
    return {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "application/pdf": ".pdf",
    }.get(mime_type, ".bin")
