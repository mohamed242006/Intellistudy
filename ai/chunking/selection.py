"""Decides which blocks of a document are eligible for indexing."""

from __future__ import annotations

import unicodedata

from ai.chunking.config import ChunkConfig
from ai.chunking.models import ChunkReport
from ai.ingestion.models import Block, BlockType, Document


def is_blank(text: str) -> bool:
    """True if ``text`` has no visible character (whitespace, zero-width, control, format)."""
    return not any(
        not ch.isspace() and unicodedata.category(ch) not in {"Cf", "Cc", "Zs", "Zl", "Zp", "Cn"}
        for ch in text
    )


class BlockSelector:
    """Applies the exclusion rules, in reading order (final decisions):

    * hidden slides are excluded;
    * whole-page OCR pages with confidence below ``drop_below_page_confidence`` are not indexed;
    * image OCR with confidence below ``ocr_min_confidence`` is not indexed;
    * empty blocks are dropped. Headings are kept (they feed ``heading_path``).
    """

    def __init__(self, config: ChunkConfig) -> None:
        self._config = config

    def select(self, document: Document, report: ChunkReport) -> list[Block]:
        cfg = self._config
        pages = {p.page_number: p for p in document.pages}
        hidden = {
            int(s["slide_number"]) for s in document.metadata.get("slides", []) if s.get("hidden")
        }
        unit = document.unit
        dropped_pages: set[int] = set()
        selected: list[Block] = []

        for block in document.blocks:
            page = pages.get(block.page_number)
            if unit == "slide" and block.page_number in hidden:
                if block.page_number not in report.hidden_slides_excluded:
                    report.hidden_slides_excluded.append(block.page_number)
                report.dropped_blocks += 1
                continue
            # Only whole-page OCR pages are dropped for low confidence: for text pages
            # (and for DOCX/PPTX) page confidence reflects images, not the text itself.
            if (
                unit == "page"
                and page is not None
                and page.ocr_applied
                and page.confidence < cfg.drop_below_page_confidence
            ):
                if block.page_number not in dropped_pages:
                    dropped_pages.add(block.page_number)
                    report.skipped_pages.append(block.page_number)
                report.dropped_blocks += 1
                continue
            if is_blank(block.text):
                report.dropped_blocks += 1
                continue
            if (
                block.type is BlockType.IMAGE_OCR
                and block.confidence is not None
                and block.confidence < cfg.ocr_min_confidence
            ):
                report.dropped_blocks += 1
                continue
            selected.append(block)
        return selected
