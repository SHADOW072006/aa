"""
OCR extractor — reads text from images in flagged messages.

Uses EasyOCR (pure-Python, no Tesseract binary needed) with multi-variant
preprocessing:
1. Bilingual pass (en + hi) on the original image to preserve Devanagari text.
2. English-focused pass (en) on a 2x upscaled, sharpened, contrast-enhanced
   variant to recover small punctuation in handles, UPI IDs, URLs, and wallets.

Devanagari digits (०-९) in OCR output are normalised to ASCII (0-9).
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import List, Optional

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

logger = logging.getLogger(__name__)

_reader_hi = None
_reader_en = None
_reader_lock = asyncio.Lock()

_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")

# EasyOCR sometimes drops the dot in "UPI prefix sub@psp" -> "UPI prefix sub@psp"
_DROPPED_UPI_DOT_RE = re.compile(
    r"\b(?:upi\s+)([a-z0-9_-]{3,})\s+([a-z0-9_-]{2,}@(?:oksbi|okicici|okaxis|okhdfcbank|okhdfc|okbizaxis|ybl|axl|ibl|paytm|upi|airtel|jio|kotak|sbi|icici|axis|hdfc))\b",
    re.IGNORECASE,
)

# EasyOCR sometimes drops "-" in bare domains ("pvcprint hub.in" -> "pvcprint-hub.in")
_DROPPED_SITE_HYPHEN_RE = re.compile(
    r"\b([a-z0-9]{3,})\s+([a-z0-9]{2,}\.(?:in|com|org|net|co|io|xyz|online|site|shop|store))\b",
    re.IGNORECASE,
)


async def _get_readers():
    """Lazy-load EasyOCR readers (thread-safe)."""
    global _reader_hi, _reader_en
    if _reader_hi is not None and _reader_en is not None:
        return _reader_hi, _reader_en
    async with _reader_lock:
        if _reader_hi is not None and _reader_en is not None:
            return _reader_hi, _reader_en
        try:
            import easyocr  # type: ignore

            loop = asyncio.get_event_loop()
            if _reader_hi is None:
                _reader_hi = await loop.run_in_executor(
                    None,
                    lambda: easyocr.Reader(["en", "hi"], gpu=False, verbose=False),
                )
            if _reader_en is None:
                _reader_en = await loop.run_in_executor(
                    None,
                    lambda: easyocr.Reader(["en"], gpu=False, verbose=False),
                )
            logger.info("EasyOCR readers initialised (en+hi, en)")
        except ImportError:
            logger.warning("easyocr not installed — image OCR disabled")
        except Exception as exc:
            logger.error("EasyOCR init failed: %s", exc)
    return _reader_hi, _reader_en


def _normalise_ocr_text(text: str) -> str:
    text = text.translate(_DEVANAGARI_DIGITS)
    text = _DROPPED_UPI_DOT_RE.sub(lambda m: f"UPI {m.group(1)}.{m.group(2)}", text)
    text = _DROPPED_SITE_HYPHEN_RE.sub(lambda m: f"{m.group(1)}-{m.group(2)}", text)
    # In Base58 TRC20 addresses (34 chars starting with 'T'), uppercase 'I' is never valid Base58 (it is '1').
    text = re.sub(r"\bT[A-Za-z0-9]{33}\b", lambda m: m.group().replace("I", "1"), text)
    return re.sub(r"\s+", " ", text).strip()


def _run_multivariant_ocr(image_path: str, reader_hi, reader_en) -> Optional[str]:
    with Image.open(image_path) as im:
        rgb = im.convert("RGB")
        orig_arr = np.array(rgb)
        scale = 1.5 if max(rgb.width, rgb.height) < 1100 else 1.0
        if scale > 1.0:
            up = rgb.resize((int(rgb.width * scale), int(rgb.height * scale)), Image.Resampling.LANCZOS)
        else:
            up = rgb
        sharp = ImageEnhance.Contrast(up.filter(ImageFilter.SHARPEN)).enhance(1.5)
        sharp_arr = np.array(sharp)

    parts: List[str] = []
    if reader_hi is not None:
        hi_tokens = reader_hi.readtext(orig_arr, detail=0, paragraph=False)
        hi_text = " ".join(str(t) for t in hi_tokens).strip()
        if hi_text:
            parts.append(hi_text)

    if reader_en is not None:
        en_tokens = reader_en.readtext(sharp_arr, detail=0, paragraph=False)
        en_text = " ".join(str(t) for t in en_tokens).strip()
        if en_text and en_text not in parts:
            parts.append(en_text)

    if not parts:
        return None
    merged = _normalise_ocr_text(" ".join(parts))
    return merged if merged else None


async def extract_text_from_image(image_path: str) -> Optional[str]:
    """
    Run multi-variant OCR on a local image file.
    Returns extracted, digit-normalised text joined into a single string, or None on failure.
    """
    p = Path(image_path)
    if not p.exists():
        return None

    suffix = p.suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif"}:
        return None

    reader_hi, reader_en = await _get_readers()
    if reader_hi is None and reader_en is None:
        return None

    try:
        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(
            None,
            lambda: _run_multivariant_ocr(str(p), reader_hi, reader_en),
        )
        if text:
            logger.debug("OCR extracted %d chars from %s", len(text), p.name)
        return text
    except Exception as exc:
        logger.warning("OCR failed for %s: %s", image_path, exc)
        return None
