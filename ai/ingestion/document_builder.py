"""Layer 4 - document reconstruction.

Pure logic, no file or engine access: takes the outputs of the earlier layers
(PyMuPDF text, OCR text, tables) and produces finished pages and a Document.
"""

from __future__ import annotations

import logging
from typing import Literal

from ai.ingestion.cleaners import mark_headings
from ai.ingestion.models import (
    Block,
    BlockType,
    Document,
    PageContent,
    PageType,
    SourceInfo,
    TableData,
)
from ai.ingestion.structure import (
    apply_outline_levels,
    finalize_document,
    parse_markdown_blocks,
    render_blocks,
)

logger = logging.getLogger(__name__)

TableFormat = Literal["pipe", "key_value"]


class PageClassifier:
    """Assigns a :class:`PageType` to a processed page."""

    def __init__(self, min_text_chars: int = 50) -> None:
        self.min_text_chars = min_text_chars

    def classify(self, page: PageContent) -> PageType:
        body_chars = len(page.text)
        has_tables = bool(page.tables)
        if page.ocr_applied:
            # Text came from OCR => scanned; native text or tables on top => mixed
            if has_tables or body_chars >= self.min_text_chars:
                return PageType.MIXED_PAGE
            return PageType.SCANNED_PAGE
        if page.images_with_text:
            # Text recovered from embedded images: mixed unless there's nothing else
            if body_chars < self.min_text_chars and not has_tables:
                return PageType.SCANNED_PAGE
            return PageType.MIXED_PAGE
        if has_tables:
            # Little prose beyond the tables => table page; lots => mixed
            return PageType.TABLE_PAGE if body_chars < 4 * self.min_text_chars else PageType.MIXED_PAGE
        return PageType.TEXT_PAGE


class ConfidenceScorer:
    """Heuristic 0-1 extraction-quality score per page."""

    @staticmethod
    def score(page: PageContent) -> float:
        if page.ocr_applied:
            if page.ocr_confidence is None or not page.ocr_text:
                return 0.0
            return round(min(page.ocr_confidence / 100.0, 1.0), 3)

        native = ConfidenceScorer._native_score(page)
        images = page.images_with_text
        if not images:
            return native

        # Blend native-text and image-OCR confidence, weighted by characters.
        image_chars = sum(len(i.ocr_text) for i in images)
        image_conf = sum((i.ocr_confidence or 0.0) * len(i.ocr_text) for i in images) / image_chars / 100.0
        native_chars = len(page.text) + sum(len(t.to_pipe_text()) for t in page.tables)
        if native_chars == 0:
            return round(min(image_conf, 1.0), 3)
        total = native_chars + image_chars
        return round((native * native_chars + min(image_conf, 1.0) * image_chars) / total, 3)

    @staticmethod
    def _native_score(page: PageContent) -> float:
        """Confidence of the PyMuPDF text layer / tables alone."""
        text = page.text
        if not text and not page.tables:
            return 0.0
        if not text:
            return 0.9  # table-only page
        bad = text.count("\ufffd") + sum(1 for c in text if ord(c) < 32 and c not in "\n\t")
        alnum = sum(c.isalnum() for c in text) / max(len(text), 1)
        penalty = min(bad / max(len(text), 1) * 10, 0.5)
        base = 0.6 + 0.4 * min(alnum / 0.7, 1.0)
        return round(max(base - penalty, 0.0), 3)


class DocumentBuilder:
    """Combines per-page layer outputs into a clean :class:`Document`.

    Args:
        classifier: Page classifier (injectable for testing).
        scorer: Confidence scorer (injectable for testing).
        table_format: ``"pipe"`` (``Course | Grade``) or ``"key_value"`` (``Course: AI``).
        min_text_chars: Used by the default classifier.
    """

    def __init__(
        self,
        classifier: PageClassifier | None = None,
        scorer: ConfidenceScorer | None = None,
        table_format: TableFormat = "pipe",
        min_text_chars: int = 50,
    ) -> None:
        self.classifier = classifier or PageClassifier(min_text_chars)
        self.scorer = scorer or ConfidenceScorer()
        self.table_format = table_format

    # ------------------------------------------------------------------ page
    def finalize_page(self, page: PageContent) -> PageContent:
        """Classify, score, build blocks and assemble ``final_text`` for a page (in place)."""
        page.page_type = self.classifier.classify(page)
        page.confidence = self.scorer.score(page)
        page.blocks = self._build_blocks(page)
        page.final_text = render_blocks(page.blocks)
        return page

    def _build_blocks(self, page: PageContent) -> list[Block]:
        """Reading-order blocks: page text first, then tables / image text by position."""
        blocks: list[Block] = []
        if page.ocr_applied and page.ocr_text:
            blocks.extend(parse_markdown_blocks(mark_headings(page.ocr_text), page.page_number))
        if page.text:
            blocks.extend(parse_markdown_blocks(page.text, page.page_number))

        # Tables and image text follow the body, ordered top-to-bottom on the page.
        # Items without a position keep their relative order at the end.
        extras: list[tuple[float, int, Block]] = []
        for table in page.tables:
            table_block = Block(
                BlockType.TABLE,
                self._render_table(table),
                page.page_number,
                ref_index=table.index,
                bbox=table.bbox,
            )
            extras.append((self._top(table.bbox), len(extras), table_block))
        for image in page.images_with_text:
            confidence = None if image.ocr_confidence is None else image.ocr_confidence / 100.0
            image_block = Block(
                BlockType.IMAGE_OCR,
                image.ocr_text,
                page.page_number,
                ref_index=image.index,
                bbox=image.bbox,
                confidence=confidence,
            )
            extras.append((self._top(image.bbox), len(extras), image_block))
        blocks.extend(block for _, _, block in sorted(extras, key=lambda e: (e[0], e[1])))
        return blocks

    @staticmethod
    def _top(bbox: tuple[float, float, float, float] | None) -> float:
        return bbox[1] if bbox else float("inf")

    def _render_table(self, table: TableData) -> str:
        return table.to_key_value_text() if self.table_format == "key_value" else table.to_pipe_text()

    # -------------------------------------------------------------- document
    def build(
        self,
        source_path: str,
        pages: list[PageContent],
        metadata: dict[str, object],
        source: SourceInfo | None = None,
    ) -> Document:
        """Create the final :class:`Document`: heading levels, paths and statistics."""
        document = Document(source_path=source_path, pages=pages, metadata=metadata, source=source)
        document.statistics = self.compute_statistics(document)  # legacy PDF keys

        # Bookmarks, when present, are the authority for heading levels.
        raw_outline = metadata.get("outline") or []
        outline = [
            (int(level), str(title), int(page))
            for level, title, page in raw_outline  # type: ignore[attr-defined]
        ]
        if apply_outline_levels(document, outline):
            for page in pages:
                page.final_text = render_blocks(page.blocks)

        finalize_document(document, carry_across_pages=True)
        logger.info("Document built: %s", document.statistics)
        return document

    @staticmethod
    def compute_statistics(document: Document) -> dict[str, object]:
        pages = document.pages
        count = lambda t: sum(p.page_type == t for p in pages)  # noqa: E731
        confs = [p.confidence for p in pages]
        return {
            "total_pages": len(pages),
            "text_pages": count(PageType.TEXT_PAGE),
            "scanned_pages": count(PageType.SCANNED_PAGE),
            "table_pages": count(PageType.TABLE_PAGE),
            "mixed_pages": count(PageType.MIXED_PAGE),
            "ocr_pages": sum(p.ocr_applied for p in pages),
            "total_images": sum(p.image_count for p in pages),
            "ocr_images": sum(len(p.images_with_text) for p in pages),
            "image_ocr_pages": sum(bool(p.images_with_text) for p in pages),
            "total_tables": sum(len(p.tables) for p in pages),
            "average_confidence": round(sum(confs) / len(confs), 3) if confs else 0.0,
            "low_confidence_pages": [p.page_number for p in pages if p.confidence < 0.6],
        }
