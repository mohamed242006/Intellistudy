"""Layer 2 - OCR (PyMuPDF rendering + Pillow + pytesseract).

Two entry points, both owned by :class:`OCRProcessor`:

* :meth:`OCRProcessor.process` - OCR a whole rendered page (scanned pages only).
* :meth:`OCRProcessor.process_image` - OCR a single embedded image (any page).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pymupdf as fitz
import pytesseract
from PIL import Image, ImageOps

from ai.ingestion.cleaners import clean_text
from ai.ingestion.models import OCRError

logger = logging.getLogger(__name__)

#: Seconds Tesseract may spend on one image before it is killed (0 = no limit). Off by default so existing callers
#: behave as before; the backend's sandboxed parser sets it (backend security contract UPL-08).
DEFAULT_TIMEOUT_SECONDS: float = 0.0


@dataclass(slots=True)
class OCRResult:
    """OCR output for one page or one image.

    ``skipped_reason`` is set (and ``text`` empty) when an image was filtered out
    before or after OCR, e.g. ``"too_small"``, ``"no_text"``, ``"low_confidence"``.
    """

    text: str
    confidence: float  # mean word confidence, 0-100
    applied: bool = True  # False when the image was filtered before running Tesseract
    skipped_reason: str | None = None


class OCRProcessor:
    """Runs Tesseract on rendered pages and on embedded images.

    Args:
        dpi: Render resolution for full-page OCR. 300 is the usual sweet spot.
        lang: Tesseract language(s), e.g. ``"eng"`` or ``"eng+ara"``.
        min_word_confidence: Words below this confidence (0-100) are dropped.
        min_image_side: Images with a shorter side (px) than this are skipped
            (icons, bullets, rules).
        min_image_area: Images with fewer pixels than this are skipped.
        max_image_aspect: Images thinner than this width:height ratio are skipped
            (separator lines, banners).
        min_image_chars: Image OCR results shorter than this are treated as "no text".
        min_image_confidence: Image OCR results with mean confidence below this
            (0-100) are discarded - photos and diagrams produce low-confidence noise.
        min_ocr_side: Images whose longest side is below this are upscaled for
            better recognition.
        max_ocr_side: Images whose longest side exceeds this are downscaled for speed.
    """

    def __init__(
        self,
        dpi: int = 300,
        lang: str = "eng",
        min_word_confidence: float = 30.0,
        min_image_side: int = 40,
        min_image_area: int = 10_000,
        max_image_aspect: float = 25.0,
        min_image_chars: int = 8,
        min_image_confidence: float = 55.0,
        min_ocr_side: int = 1000,
        max_ocr_side: int = 3500,
        timeout: float | None = None,
    ) -> None:
        self.timeout = DEFAULT_TIMEOUT_SECONDS if timeout is None else timeout
        self.dpi = dpi
        self.lang = lang
        self.min_word_confidence = min_word_confidence
        self.min_image_side = min_image_side
        self.min_image_area = min_image_area
        self.max_image_aspect = max_image_aspect
        self.min_image_chars = min_image_chars
        self.min_image_confidence = min_image_confidence
        self.min_ocr_side = min_ocr_side
        self.max_ocr_side = max_ocr_side
        self.available = self._check_available()
        self._image_cache: dict[object, OCRResult] = {}

    @staticmethod
    def _check_available() -> bool:
        try:
            version = pytesseract.get_tesseract_version()
            logger.info("Tesseract %s detected", version)
            return True
        except Exception as exc:
            logger.warning("Tesseract not available, OCR disabled: %s", exc)
            return False

    # ------------------------------------------------------------ whole page
    def render_page(self, page: fitz.Page) -> Image.Image:
        """Render a PDF page to a PIL image."""
        pix = page.get_pixmap(dpi=self.dpi, colorspace=fitz.csRGB, alpha=False)
        return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

    def process(self, page: fitz.Page) -> OCRResult:
        """OCR a whole page (used for scanned pages).

        Raises:
            OCRError: if Tesseract is missing or fails.
        """
        number = page.number + 1
        self._require_engine()
        try:
            image = self.render_page(page)
        except Exception as exc:
            raise OCRError(f"Cannot render page {number} for OCR: {exc}") from exc
        result = self._run_tesseract(image, f"page {number}")
        logger.info("OCR page %d: %d chars, mean confidence %.1f", number, len(result.text), result.confidence)
        return result

    # ---------------------------------------------------------- single image
    def process_image(self, image: Image.Image, cache_key: object | None = None) -> OCRResult:
        """OCR one embedded image.

        Tiny, extremely thin, empty and low-confidence images are filtered out and
        returned with ``text=""`` and a ``skipped_reason`` instead of raising.

        Args:
            image: The decoded image.
            cache_key: Optional identity (e.g. the PDF image xref). Images that
                repeat across pages (logos, headers) are OCR'd only once per
                document; call :meth:`clear_cache` between documents.

        Raises:
            OCRError: if Tesseract is missing or fails.
        """
        if cache_key is not None and cache_key in self._image_cache:
            logger.debug("Image OCR cache hit: %s", cache_key)
            return self._image_cache[cache_key]

        result = self._ocr_image_uncached(image)
        if cache_key is not None:
            self._image_cache[cache_key] = result
        return result

    def clear_cache(self) -> None:
        """Forget cached image results (call at the start of each document)."""
        self._image_cache.clear()

    def _ocr_image_uncached(self, image: Image.Image) -> OCRResult:
        width, height = image.size
        short, long_ = min(width, height), max(width, height)
        if short < self.min_image_side or width * height < self.min_image_area:
            return OCRResult("", 0.0, applied=False, skipped_reason="too_small")
        if long_ / max(short, 1) > self.max_image_aspect:
            return OCRResult("", 0.0, applied=False, skipped_reason="too_thin")

        self._require_engine()
        result = self._run_tesseract(self._prepare_image(image), f"image {width}x{height}")
        if len(result.text) < self.min_image_chars:
            return OCRResult("", result.confidence, skipped_reason="no_text")
        if result.confidence < self.min_image_confidence:
            logger.debug("Image OCR discarded (confidence %.1f)", result.confidence)
            return OCRResult("", result.confidence, skipped_reason="low_confidence")
        logger.info("OCR image %dx%d: %d chars, mean confidence %.1f",
                    width, height, len(result.text), result.confidence)
        return result

    def _prepare_image(self, image: Image.Image) -> Image.Image:
        """Grayscale, then upscale small images / downscale huge ones."""
        img = ImageOps.grayscale(image)
        long_ = max(img.size)
        if long_ < self.min_ocr_side:
            scale = min(self.min_ocr_side / long_, 3.0)
        elif long_ > self.max_ocr_side:
            scale = self.max_ocr_side / long_
        else:
            return img
        new_size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
        return img.resize(new_size, Image.Resampling.LANCZOS)

    # ----------------------------------------------------------------- core
    def _require_engine(self) -> None:
        if not self.available:
            raise OCRError("Tesseract is not installed or not on PATH")

    def _run_tesseract(self, image: Image.Image, label: str) -> OCRResult:
        """Run Tesseract and rebuild text (line/paragraph aware) with a mean confidence."""
        try:
            data = pytesseract.image_to_data(
                image, lang=self.lang, output_type=pytesseract.Output.DICT, timeout=self.timeout
            )
        except Exception as exc:
            raise OCRError(f"OCR failed on {label}: {exc}") from exc

        lines: dict[tuple[int, int, int], list[str]] = {}
        confs: list[float] = []
        for i, raw_word in enumerate(data["text"]):
            word = raw_word.strip()
            try:
                conf = float(data["conf"][i])
            except (TypeError, ValueError):
                continue
            if not word or conf < 0:
                continue
            confs.append(conf)
            if conf < self.min_word_confidence:
                continue
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            lines.setdefault(key, []).append(word)

        # Blank line between paragraphs, newline between lines.
        out: list[str] = []
        last_par: tuple[int, int] | None = None
        for (blk, par, _ln), words in lines.items():
            if last_par is not None and (blk, par) != last_par:
                out.append("")
            out.append(" ".join(words))
            last_par = (blk, par)

        text = clean_text("\n".join(out))
        mean_conf = sum(confs) / len(confs) if confs else 0.0
        return OCRResult(text=text, confidence=mean_conf)
