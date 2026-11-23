"""Ingestion pipeline - the single entry point for the rest of IntelliStudy.

``IngestionPipeline.ingest`` routes by file type (extension, or MIME type when
given): ``.pdf`` runs the hybrid PDF flow below, ``.docx`` goes to
:class:`DocxReader` and ``.pptx`` to :class:`PptxReader`. All three return the
same :class:`Document` model.

PDF flow per page::

    PDFReader (L1) -> page has no text layer?  -> OCRProcessor.process        (whole page)
                   -> else, page has images?   -> OCRProcessor.process_image  (each image)
                   -> else/also                -> TableExtractor (L3) -> re-read text without tables
                   -> DocumentBuilder.finalize_page (L4)

Usage::

    from ai.ingestion.ingestion_pipeline import IngestionPipeline

    document = IngestionPipeline().ingest("lecture.pdf")
    document = IngestionPipeline().ingest("slides.pptx")
"""

from __future__ import annotations

import logging
import math
import re
import threading
from pathlib import Path

from ai.ingestion.docs_reader import DOCX_SUFFIXES, DocxReader
from ai.ingestion.document_builder import DocumentBuilder
from ai.ingestion.figure_selection import SelectionConfig, apply_stats, figure_features, select_figures
from ai.ingestion.figures import area, detect_pdf_figures, intersection
from ai.ingestion.models import (
    Document,
    ImageExtractionError,
    IngestionError,
    OCRError,
    PageContent,
    TableData,
    TableExtractionError,
)
from ai.ingestion.ocr_processor import OCRProcessor
from ai.ingestion.pdf_reader import LayoutProfile, PDFReader, RunningLines
from ai.ingestion.pptx_reader import PPTX_SUFFIXES, PptxReader
from ai.ingestion.structure import build_source_info, pdf_date_to_iso
from ai.ingestion.table_extractor import TableExtractor

logger = logging.getLogger(__name__)

PDF_SUFFIXES: frozenset[str] = frozenset({".pdf"})

_MIN_TABLE_FILL = 0.4  # below this share of non-empty cells a detected table is treated as a chart frame


def _filled_fraction(table: TableData) -> float:
    cells = [cell for row in table.rows for cell in row]
    return sum(1 for cell in cells if str(cell).strip()) / len(cells) if cells else 0.0

# MIME type -> canonical suffix, for uploads whose filename is not trustworthy.
MIME_TYPES: dict[str, str] = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
}
SUPPORTED_SUFFIXES: frozenset[str] = PDF_SUFFIXES | DOCX_SUFFIXES | PPTX_SUFFIXES


class IngestionPipeline:
    """Orchestrates the four layers. All collaborators are injectable.

    Args:
        reader: Layer 1 PyMuPDF reader.
        ocr: Layer 2 OCR processor (created lazily, only if a page needs OCR).
        table_extractor: Layer 3 pdfplumber extractor.
        builder: Layer 4 document builder.
        docx_reader: DOCX reader (created lazily, sharing this pipeline's OCR).
        pptx_reader: PPTX reader (created lazily, sharing this pipeline's OCR).
        enable_ocr: Disable to skip full-page OCR of scanned pages.
        enable_image_ocr: Disable to skip OCR of embedded images on pages that
            already have a text layer.
        enable_tables: Disable to skip table extraction entirely.
    """

    def __init__(
        self,
        reader: PDFReader | None = None,
        ocr: OCRProcessor | None = None,
        table_extractor: TableExtractor | None = None,
        builder: DocumentBuilder | None = None,
        enable_ocr: bool = True,
        enable_image_ocr: bool = True,
        enable_tables: bool = True,
        docx_reader: DocxReader | None = None,
        pptx_reader: PptxReader | None = None,
        enable_figures: bool = True,
        figure_config: SelectionConfig | None = None,
    ) -> None:
        self.reader = reader or PDFReader()
        self.enable_figures = enable_figures
        self.figure_config = figure_config or SelectionConfig()
        self._ocr = ocr
        self.table_extractor = table_extractor or TableExtractor()
        self.builder = builder or DocumentBuilder(min_text_chars=self.reader.min_text_chars)
        self.enable_ocr = enable_ocr
        self.enable_image_ocr = enable_image_ocr
        self.enable_tables = enable_tables
        self._docx_reader = docx_reader
        self._pptx_reader = pptx_reader
        # The PDF flow keeps per-document state on the shared layers (table extractor, OCR
        # cache), so one pipeline instance processes one PDF at a time. Run one pipeline per
        # worker for real parallelism; concurrent calls are safe but serialised.
        self._pdf_lock = threading.Lock()

    @property
    def ocr(self) -> OCRProcessor:
        """Lazily create the OCR processor so text-only PDFs never touch Tesseract."""
        if self._ocr is None:
            self._ocr = OCRProcessor()
        return self._ocr

    @property
    def docx_reader(self) -> DocxReader:
        if self._docx_reader is None:
            self._docx_reader = DocxReader(ocr_processor=self.ocr)
        return self._docx_reader

    @property
    def pptx_reader(self) -> PptxReader:
        if self._pptx_reader is None:
            self._pptx_reader = PptxReader(ocr_processor=self.ocr)
        return self._pptx_reader

    # ---------------------------------------------------------------- public
    def ingest(self, path: str | Path, mime_type: str | None = None) -> Document:
        """Ingest a PDF, DOCX or PPTX file and return a :class:`Document`.

        Args:
            path: file to ingest.
            mime_type: optional MIME type; when it is a known one it decides
                the format instead of the file extension, and the extension
                is then not required to match (uploads are often stored under
                temporary names).

        Raises:
            IngestionError: if the file type is not supported.
            PDFParseError / DocxParseError / PptxParseError: if the file
                cannot be opened.
        """
        suffix = self.resolve_format(path, mime_type)
        by_mime = self._mime_suffix(mime_type) is not None
        if suffix in DOCX_SUFFIXES:
            logger.info("Starting DOCX ingestion: %s", path)
            return self.docx_reader.read(path, check_suffix=not by_mime)
        if suffix in PPTX_SUFFIXES:
            logger.info("Starting PPTX ingestion: %s", path)
            return self.pptx_reader.read(path, check_suffix=not by_mime)
        return self._ingest_pdf(path)

    @staticmethod
    def resolve_format(path: str | Path, mime_type: str | None = None) -> str:
        """Return the canonical suffix (``.pdf`` / ``.docx`` / ``.pptx``) for a file."""
        known = IngestionPipeline._mime_suffix(mime_type)
        if known:
            return known
        suffix = Path(path).suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            raise IngestionError(
                f"Unsupported file type '{suffix or mime_type or 'unknown'}': {path} "
                f"(supported: {', '.join(sorted(SUPPORTED_SUFFIXES))})"
            )
        return suffix

    @staticmethod
    def _mime_suffix(mime_type: str | None) -> str | None:
        """Canonical suffix for a known MIME type (parameters ignored), else ``None``."""
        if not mime_type:
            return None
        return MIME_TYPES.get(mime_type.split(";")[0].strip().lower())

    def _ingest_pdf(self, path: str | Path) -> Document:
        """Run the hybrid PDF pipeline (serialised: see ``_pdf_lock``).

        Raises:
            PDFParseError: if the file cannot be opened.
        """
        with self._pdf_lock:
            return self._ingest_pdf_unlocked(path)

    def _ingest_pdf_unlocked(self, path: str | Path) -> Document:
        logger.info("Starting ingestion: %s", path)
        fitz_doc = self.reader.open(path)
        metadata = self.reader.extract_metadata(fitz_doc)
        pages: list[PageContent] = []
        failed: set[int] = set()
        if self._ocr is not None:
            self._ocr.clear_cache()  # image results are cached per document only
        try:
            # Document-level pass: lines repeated in the header / footer band.
            running = self.reader.detect_running_lines(fitz_doc)
            # ... and document-wide typography, so heading levels agree across pages.
            profile = self.reader.profile_document(fitz_doc, running)
            tables_ready = self._open_tables(path)
            for fitz_page in fitz_doc.pages():
                pages.append(
                    self._extract_page(
                        fitz_doc, fitz_page, tables_ready, running, profile, failed
                    )
                )
            if self.enable_figures:
                figure_summary = self._figure_pass(fitz_doc, pages, running, profile)
                if figure_summary:
                    metadata["figures"] = figure_summary
        finally:
            fitz_doc.close()
            self.table_extractor.close()

        # Needs every page's OCR results, so it runs before finalisation.
        repeated_images = self._drop_repeated_images(pages)
        if running or repeated_images:
            metadata["running_content"] = {
                "lines": running.summary(),
                "repeated_image_texts": repeated_images,
            }
        pages = [
            page if page.page_number in failed else self._finalize(page, failed)
            for page in pages
        ]
        source = build_source_info(
            path,
            "pdf",
            page_count=len(pages),
            title=str(metadata.get("title") or "") or None,
            author=str(metadata.get("author") or "") or None,
            created=pdf_date_to_iso(metadata.get("creationDate")),
            modified=pdf_date_to_iso(metadata.get("modDate")),
        )
        return self.builder.build(str(path), pages, metadata, source=source)

    # --------------------------------------------------------------- private
    def _open_tables(self, path: str | Path) -> bool:
        if not self.enable_tables:
            return False
        try:
            self.table_extractor.open(path)
            return True
        except TableExtractionError as exc:
            logger.warning("Table layer disabled for this file: %s", exc)
            return False

    def _extract_page(
        self,
        fitz_doc,
        fitz_page,
        tables_ready: bool,
        running: RunningLines,
        profile: LayoutProfile,
        failed: set[int],
    ) -> PageContent:
        """Layers 1-3 for one page; Layer 4 (finalisation) happens afterwards."""
        number = fitz_page.number + 1
        try:
            page = self.reader.analyze_page(fitz_page, running=running, profile=profile)  # Layer 1

            if page.needs_ocr and self.enable_ocr:  # Layer 2a - whole page, only when no text layer
                self._run_ocr(fitz_page, page)

            # Layer 2b - embedded images, only when the page was NOT OCR'd as a whole
            # (otherwise the image text is already in the page OCR => no duplicates).
            if self.enable_image_ocr and page.images and not page.ocr_applied:
                self._run_image_ocr(fitz_doc, page)

            if tables_ready and not page.ocr_applied:  # Layer 3 - needs a real text layer
                self._run_tables(fitz_page, page, running, profile)
            page.size = (float(fitz_page.rect.width), float(fitz_page.rect.height))
            if self.enable_figures and not page.ocr_applied:  # figures: candidates only, chosen per document
                self._detect_figures(fitz_doc, fitz_page, page)
            return page
        except Exception as exc:  # one bad page must never kill the document
            logger.exception("Page %d failed: %s", number, exc)
            failed.add(number)
            broken = PageContent(page_number=number, confidence=0.0)
            broken.warnings.append(f"Page processing failed: {exc}")
            return broken

    def _detect_figures(self, fitz_doc, fitz_page, page: PageContent) -> None:
        try:
            # a nearly empty "table" is usually the gridlines and legend of a chart: not a reason to ignore the graphic
            tables = [t.bbox for t in page.tables if t.bbox and _filled_fraction(t) >= _MIN_TABLE_FILL]
            page.figures = detect_pdf_figures(fitz_page, page.images, tables=tables)
            for figure in page.figures:  # fingerprints feed repetition / flat-colour rules
                if figure.image_index is None:
                    continue
                image = page.images[figure.image_index]
                try:
                    apply_stats(image, self.reader.load_image(fitz_doc, image))
                except ImageExtractionError as exc:
                    logger.debug("No fingerprint for image on page %d: %s", page.page_number, exc)
        except Exception as exc:  # figure detection must never cost a page its text
            logger.warning("Figure detection failed on page %d: %s", page.page_number, exc)
            page.figures = []
            page.warnings.append(f"Figure detection failed: {exc}")

    def _figure_pass(self, fitz_doc, pages: list[PageContent], running: RunningLines, profile: LayoutProfile) -> dict:
        """Keep the figures worth keeping and take their words out of the running text."""
        candidates = sum(len(p.figures) for p in pages)
        if not candidates:
            return {}
        decisions = select_figures(pages, self.figure_config)
        kept_ids = {id(f) for f, d in decisions if d.keep}
        skipped = [
            {"page": f.page_number, "kind": f.kind, "reasons": list(d.reasons)} for f, d in decisions if not d.keep
        ]
        detail = [
            {
                "page": f.page_number, "image_index": f.image_index, "kind": f.kind, "label": f.label,
                "bbox": [round(v, 1) for v in f.bbox] if f.bbox else None,
                "keep": d.keep, "score": d.score, "reasons": list(d.reasons),
                "features": figure_features(f, pages[f.page_number - 1]),
            }
            for f, d in decisions
        ]
        kept = 0
        for page in pages:
            page.figures = [f for f in page.figures if id(f) in kept_ids]
            for number, figure in enumerate(page.figures):
                figure.index = number
            kept += len(page.figures)
            if not page.figures:
                continue
            self._drop_chart_tables(page)
            boxes = [t.bbox for t in page.tables if t.bbox]
            for figure in page.figures:
                if figure.caption_bbox:
                    boxes.append(figure.caption_bbox)
                if figure.kind == "vector_region" and figure.bbox:
                    boxes.append(figure.bbox)
            try:
                page.text = self.reader.extract_text(
                    fitz_doc[page.page_number - 1], exclude_bboxes=boxes, running=running, profile=profile
                )
            except Exception as exc:  # keep the original text rather than lose the page
                logger.warning("Re-reading page %d without figures failed: %s", page.page_number, exc)
        return {"candidates": candidates, "kept": kept, "skipped": skipped[:200], "decisions": detail[:1000]}

    @staticmethod
    def _drop_chart_tables(page: PageContent) -> None:
        """Remove "tables" that are really the frame of a kept figure (mostly empty cells inside its box)."""
        graphics = [f.bbox for f in page.figures if f.bbox and f.kind in ("vector_region", "raster")]
        if not graphics:
            return
        keep = []
        for table in page.tables:
            inside = table.bbox is not None and any(
                intersection(table.bbox, g) > 0.6 * area(table.bbox) for g in graphics
            )
            if not (inside and _filled_fraction(table) < _MIN_TABLE_FILL):
                keep.append(table)
        if len(keep) != len(page.tables):
            for number, table in enumerate(keep):
                table.index = number
            page.tables = keep

    def _finalize(self, page: PageContent, failed: set[int]) -> PageContent:
        """Layer 4 for one page, with the same isolation as extraction."""
        try:
            return self.builder.finalize_page(page)
        except Exception as exc:
            logger.exception("Page %d failed: %s", page.page_number, exc)
            failed.add(page.page_number)
            broken = PageContent(page_number=page.page_number, confidence=0.0)
            broken.warnings.append(f"Page processing failed: {exc}")
            return broken

    @staticmethod
    def _drop_repeated_images(
        pages: list[PageContent], min_pages: int = 3, min_ratio: float = 0.5
    ) -> int:
        """Blank out image OCR text that repeats on most pages (logos, banners).

        Returns the number of image results removed. Like repeated header
        lines, such text carries no page-specific information and would only
        pollute every chunk.
        """
        total = len(pages)
        if total < min_pages:
            return 0

        def key(text: str) -> str:
            return re.sub(r"\s+", " ", text.casefold()).strip()

        pages_by_text: dict[str, set[int]] = {}
        for page in pages:
            for image in page.images_with_text:
                pages_by_text.setdefault(key(image.ocr_text), set()).add(page.page_number)

        needed = max(min_pages, math.ceil(min_ratio * total))
        repeated = {text for text, seen in pages_by_text.items() if len(seen) >= needed}
        removed = 0
        for page in pages:
            for image in page.images_with_text:
                if key(image.ocr_text) in repeated:
                    image.ocr_text = ""
                    image.ocr_skipped_reason = "repeated"
                    removed += 1
        return removed

    def _run_ocr(self, fitz_page, page: PageContent) -> None:
        try:
            result = self.ocr.process(fitz_page)
            page.ocr_text = result.text
            page.ocr_confidence = result.confidence
            page.ocr_applied = True
        except OCRError as exc:
            logger.error("%s", exc)
            page.warnings.append(str(exc))

    def _run_image_ocr(self, fitz_doc, page: PageContent) -> None:
        """OCR each embedded image separately and store the result on the image."""
        for image in page.images:
            try:
                pil_image = self.reader.load_image(fitz_doc, image)
                result = self.ocr.process_image(pil_image, cache_key=image.xref)
            except (ImageExtractionError, OCRError) as exc:
                logger.warning("Image OCR skipped on page %d: %s", page.page_number, exc)
                page.warnings.append(str(exc))
                if isinstance(exc, OCRError) and not self.ocr.available:
                    return  # no engine => no point trying the remaining images
                continue
            image.ocr_applied = result.applied
            image.ocr_text = result.text
            image.ocr_confidence = result.confidence if result.applied else None
            image.ocr_skipped_reason = result.skipped_reason

    def _run_tables(
        self,
        fitz_page,
        page: PageContent,
        running: RunningLines | None = None,
        profile: LayoutProfile | None = None,
    ) -> None:
        try:
            page.tables = self.table_extractor.extract(page.page_number)
        except TableExtractionError as exc:
            logger.warning("%s", exc)
            page.warnings.append(str(exc))
            return
        if page.tables:
            # Re-read the text with table regions removed so tables aren't duplicated.
            boxes = [t.bbox for t in page.tables if t.bbox]
            page.text = self.reader.extract_text(
                fitz_page, exclude_bboxes=boxes, running=running, profile=profile
            )
