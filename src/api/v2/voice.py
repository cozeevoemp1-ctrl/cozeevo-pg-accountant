"""Voice endpoints: transcribe (Whisper) + intent extraction (Llama 3.3)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, UploadFile

from src.api.v2.auth import AppUser, get_current_user
from src.schemas.voice import IntentRequest, PaymentIntentResponse, TranscribeResponse
from src.services.intent_voice import extract_intent
from src.services.voice import transcribe

router = APIRouter(prefix="/voice")

MAX_AUDIO_BYTES = 25 * 1024 * 1024  # 25 MB — Groq limit


@router.post("/transcribe", response_model=TranscribeResponse)
async def transcribe_endpoint(
    audio: UploadFile,
    user: AppUser = Depends(get_current_user),
):
    if user.role not in ("admin", "staff"):
        raise HTTPException(status_code=403, detail="admin/staff only")

    data = await audio.read(MAX_AUDIO_BYTES + 1)
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Audio too large (max 25 MB)")

    mime = audio.content_type or "audio/webm"
    result = transcribe(audio_bytes=data, mime=mime)
    return TranscribeResponse(
        text=result.text,
        language=result.language,
        duration_seconds=result.duration_seconds,
    )


@router.post("/intent", response_model=PaymentIntentResponse)
async def intent_endpoint(
    body: IntentRequest,
    user: AppUser = Depends(get_current_user),
):
    if user.role not in ("admin", "staff"):
        raise HTTPException(status_code=403, detail="admin/staff only")

    intent = extract_intent(transcript=body.transcript)
    return PaymentIntentResponse(**intent.model_dump())
