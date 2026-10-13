"""
Local OCR — RapidOCR (PaddleOCR PP-OCR models on ONNX Runtime), CPU only (spec 06).

One lazily-loaded engine per process. `ocr_lines_async` runs the CPU-bound work in
a thread behind a semaphore so a 1-vCPU box never runs two OCR passes at once
and the event loop stays free.
"""
from __future__ import annotations

import asyncio
import logging
import threading

import cv2
import numpy as np

logger = logging.getLogger(__name__)

MAX_SIDE = 1600  # downscale huge phone photos; screenshots stay sharp at this size

_engine = None
_engine_lock = threading.Lock()
_sem: asyncio.Semaphore | None = None


def _get_engine():
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                from rapidocr_onnxruntime import RapidOCR
                _engine = RapidOCR()
                logger.info("[LocalOCR] RapidOCR loaded")
    return _engine


def decode_image(image_bytes: bytes) -> np.ndarray | None:
    img = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return None
    h, w = img.shape[:2]
    scale = MAX_SIDE / max(h, w)
    if scale < 1:
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    return img


def ocr_boxes(image_bytes: bytes) -> list[tuple[list, str, float]]:
    """[(box, text, score)] in reading order (top-to-bottom, left-to-right)."""
    img = decode_image(image_bytes)
    if img is None:
        return []
    result, _ = _get_engine()(img)
    if not result:
        return []
    result.sort(key=lambda r: (round(r[0][0][1] / 12), r[0][0][0]))
    return [(r[0], r[1], float(r[2])) for r in result]


def ocr_lines(image_bytes: bytes) -> list[str]:
    return [t for _, t, _ in ocr_boxes(image_bytes)]


async def ocr_lines_async(image_bytes: bytes) -> list[str]:
    global _sem
    if _sem is None:
        _sem = asyncio.Semaphore(1)
    async with _sem:
        return await asyncio.to_thread(ocr_lines, image_bytes)
