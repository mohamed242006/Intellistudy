"""Shared image-OCR helpers for the document readers (DOCX, PPTX).

Both office readers embed pictures, OCR them through :class:`OCRProcessor`,
and turn the outcomes into a page-level confidence score. That logic lives
here so the readers cannot drift apart.

Reader-specific parts stay in the readers: how pictures are *found* (XML
relationships vs. shapes), how they are *labelled* in warnings, and any
reader-only skip reasons (e.g. PPTX's EMF/WMF detection is injected through
``is_unsupported``).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from io import BytesIO

from PIL import Image

from ai.ingestion.models import ImageData, PageType, TableData
from ai.ingestion.ocr_processor import OCRProcessor

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# OCR skip / failure reasons
# --------------------------------------------------------------------------- #
# Produced by the readers (not by OCRProcessor):
SKIP_READ_FAILED = "read_failed"
SKIP_DECODE_FAILED = "decode_failed"
SKIP_OCR_ERROR = "ocr_error"
# Not a failure: a vector format (EMF/WMF) this environment cannot rasterise.
SKIP_UNSUPPORTED_FORMAT = "unsupported_format"

FAILURE_REASONS: frozenset[str] = frozenset(
    {SKIP_READ_FAILED, SKIP_DECODE_FAILED, SKIP_OCR_ERROR}
)

UNSUPPORTED_FORMAT_WARNING = (
    "EMF/WMF image skipped because format is not supported in the current environment."
)

# --------------------------------------------------------------------------- #
# Confidence scoring
# --------------------------------------------------------------------------- #
# Each image gets a quality score in [0, 1]; the page confidence is their mean.
SCORE_FAILURE = 0.0  # real failures: unreadable / undecodable / OCR crashed
SCORE_OCR_BASE = 0.85  # OCR succeeded; scales up to 1.0 with OCR confidence
SCORE_OCR_RANGE = 1.0 - SCORE_OCR_BASE
SCORE_SKIPPED_DEFAULT = 0.75  # unknown / unspecified skip reason

# Intentional skips: much milder than failures.
SKIP_SCORES: dict[str, float] = {
    "too_small": 0.85,  # typically icons / bullets, no study content lost
    "too_thin": 0.85,  # typically separators / lines
    "no_text": 0.80,  # image simply contains no text (e.g. a photo)
    "low_confidence": 0.60,  # text may exist but was judged unreliable
    # Environment limitation rather than a corrupt file: milder than a failure.
    SKIP_UNSUPPORTED_FORMAT: 0.70,
}


def score_image(image: ImageData) -> float:
    """Quality score in [0, 1] for a single image's processing outcome."""
    reason = image.ocr_skipped_reason
    if reason in FAILURE_REASONS:
        return SCORE_FAILURE
    if image.ocr_applied and image.ocr_text:
        confidence = image.ocr_confidence
        fraction = 1.0 if confidence is None else min(max(confidence / 100.0, 0.0), 1.0)
        return SCORE_OCR_BASE + SCORE_OCR_RANGE * fraction
    if reason:
        return SKIP_SCORES.get(reason, SCORE_SKIPPED_DEFAULT)
    if image.ocr_applied:  # OCR ran cleanly but found no text
        return SKIP_SCORES["no_text"]
    return SCORE_SKIPPED_DEFAULT


def compute_confidence(
    images: list[ImageData], extra_scores: Iterable[float] = ()
) -> float:
    """Overall 0-1 extraction confidence: the mean of every item's score.

    ``extra_scores`` lets a reader add non-image items (PPTX charts). With no
    images and no extra items nothing could have failed, so the result is 1.0.
    Unrelated warnings never affect the score.
    """
    scores = [score_image(img) for img in images]
    scores.extend(extra_scores)
    if not scores:
        return 1.0
    return round(min(max(sum(scores) / len(scores), 0.0), 1.0), 3)


# --------------------------------------------------------------------------- #
# Decoding + OCR
# --------------------------------------------------------------------------- #


def decode_image(blob: bytes) -> Image.Image:
    """Decode image bytes into a fully-loaded RGB/grayscale PIL image."""
    with Image.open(BytesIO(blob)) as opened:
        opened.load()
        if opened.mode in ("RGBA", "LA") or (
            opened.mode == "P" and "transparency" in opened.info
        ):
            rgba = opened.convert("RGBA")
            background = Image.new("RGB", rgba.size, (255, 255, 255))
            background.paste(rgba, mask=rgba.getchannel("A"))
            return background
        if opened.mode not in ("RGB", "L"):
            return opened.convert("RGB")
        return opened.copy()


def ocr_image_blob(
    ocr: OCRProcessor,
    blob: bytes,
    image_data: ImageData,
    label: str,
    is_unsupported: Callable[[], bool] | None = None,
) -> str | None:
    """Decode ``blob``, run OCR, and write the outcome onto ``image_data``.

    Never raises. Returns a short warning detail (without the location
    ``label``; callers prefix their own) or ``None`` on a clean run.

    Args:
        ocr: OCR component.
        blob: raw image bytes.
        image_data: the :class:`ImageData` to fill in (mutated in place).
        label: human-readable image location, used for log messages only.
        is_unsupported: optional predicate consulted when decoding fails; when
            true the image is reported as ``unsupported_format`` (a mild skip)
            instead of ``decode_failed``.
    """
    try:
        pil_image = decode_image(blob)
    except Exception as exc:
        if is_unsupported is not None and is_unsupported():
            logger.warning("%s: %s", label, UNSUPPORTED_FORMAT_WARNING)
            image_data.ocr_skipped_reason = SKIP_UNSUPPORTED_FORMAT
            return UNSUPPORTED_FORMAT_WARNING
        logger.warning("%s could not be decoded: %s", label, exc)
        image_data.ocr_skipped_reason = SKIP_DECODE_FAILED
        return f"decode failed ({exc})"

    image_data.width, image_data.height = pil_image.size

    try:
        result = ocr.process_image(pil_image)
    except Exception as exc:
        logger.warning("OCR failed for %s: %s", label, exc)
        image_data.ocr_skipped_reason = SKIP_OCR_ERROR
        return f"OCR failed ({exc})"
    finally:
        pil_image.close()

    image_data.ocr_text = (result.text or "").strip()
    image_data.ocr_confidence = result.confidence
    image_data.ocr_applied = bool(result.applied)
    image_data.ocr_skipped_reason = result.skipped_reason
    return None


# --------------------------------------------------------------------------- #
# Page assembly helpers
# --------------------------------------------------------------------------- #


def join_ocr_text(images: list[ImageData]) -> str:
    return "\n\n".join(img.ocr_text for img in images if img.ocr_text)


def mean_ocr_confidence(images: list[ImageData]) -> float | None:
    """Mean engine confidence (0-100) over images where OCR produced one."""
    values = [
        img.ocr_confidence
        for img in images
        if img.ocr_applied and img.ocr_confidence is not None
    ]
    return sum(values) / len(values) if values else None


def classify_page(
    text: str, tables: list[TableData], images: list[ImageData]
) -> PageType:
    has_ocr_images = any(img.ocr_text for img in images)
    if text and (tables or has_ocr_images):
        return PageType.MIXED_PAGE
    if tables and not text:
        return PageType.TABLE_PAGE
    if has_ocr_images and not text:
        return PageType.SCANNED_PAGE
    return PageType.TEXT_PAGE
