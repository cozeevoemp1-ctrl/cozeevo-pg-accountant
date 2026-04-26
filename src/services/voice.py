"""Groq Whisper transcription service."""
from __future__ import annotations

import os
from dataclasses import dataclass

from groq import Groq

_client: Groq | None = None


def _groq() -> Groq:
    global _client
    if _client is None:
        _client = Groq(api_key=os.environ["GROQ_API_KEY"])
    return _client


@dataclass
class TranscribeResult:
    text: str
    language: str
    duration_seconds: float


def transcribe(*, audio_bytes: bytes, mime: str) -> TranscribeResult:
    """Transcribe audio bytes via Groq Whisper Large v3 Turbo."""
    filename = "audio.webm" if "webm" in mime else "audio.mp4"
    res = _groq().audio.transcriptions.create(
        file=(filename, audio_bytes, mime),
        model="whisper-large-v3-turbo",
        response_format="verbose_json",
    )
    return TranscribeResult(
        text=res.text,
        language=getattr(res, "language", "auto") or "auto",
        duration_seconds=float(getattr(res, "duration", 0) or 0),
    )
