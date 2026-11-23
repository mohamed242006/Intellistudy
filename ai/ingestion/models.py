"""Data models for the IntelliStudy document ingestion pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

#: Version of the canonical output schema (Document / PageContent / Block).
SCHEMA_VERSION = "2.1"


class IngestionError(Exception):
    """Base class for ingestion failures."""


class PDFParseError(IngestionError):
    """The PDF could not be opened or parsed."""


class OCRError(IngestionError):
    """OCR failed for a page."""


class TableExtractionError(IngestionError):
    """Table extraction failed."""


class ImageExtractionError(IngestionError):
    """An embedded image could not be decoded."""


class PageType(str, Enum):
    """Automatic page classification."""

    TEXT_PAGE = "TEXT_PAGE"
    SCANNED_PAGE = "SCANNED_PAGE"
    TABLE_PAGE = "TABLE_PAGE"
    MIXED_PAGE = "MIXED_PAGE"


class BlockType(str, Enum):
    """Kind of a reading-order element extracted from a document."""

    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"
    TABLE = "table"
    IMAGE_OCR = "image_ocr"
    CHART = "chart"
    NOTES = "notes"
    FIGURE = "figure"  # a selected figure: caption + text inside it (+ later a generated description)


@dataclass(slots=True)
class Block:
    """One element of a document, in reading order - the unit chunkers work on.

    Attributes:
        type: element kind.
        text: the element's text. For tables this is the rendered table, for
            images the OCR text; marker labels such as ``[Table 1]`` are added
            only when blocks are rendered into ``final_text``.
        page_number: 1-indexed page / slide the block belongs to (always 1 for
            DOCX, which has no real pages).
        order: 0-based position in the whole document's reading order.
        level: heading level (0 = document title, 1-6) for headings; nesting
            depth (0-based) for list items; ``None`` otherwise.
        heading_path: titles of the headings enclosing this block, outermost
            first. A heading's own path ends with its own text.
        list_marker: ``"-"`` or the rendered number (``"1."``, ``"a)"``) for
            list items.
        ref_index: index of the matching :class:`TableData` / :class:`ImageData`
            on the page, for table and image blocks.
        bbox: position on the page, when the source provides one (PDF).
        confidence: 0-1 quality of this element when known (image OCR).
    """

    type: BlockType
    text: str
    page_number: int
    order: int = 0
    level: int | None = None
    heading_path: tuple[str, ...] = ()
    list_marker: str | None = None
    ref_index: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    confidence: float | None = None

    @property
    def is_heading(self) -> bool:
        return self.type is BlockType.HEADING

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly form, e.g. for storing chunk provenance."""
        return {
            "type": self.type.value,
            "text": self.text,
            "page_number": self.page_number,
            "order": self.order,
            "level": self.level,
            "heading_path": list(self.heading_path),
            "list_marker": self.list_marker,
            "ref_index": self.ref_index,
            "bbox": list(self.bbox) if self.bbox else None,
            "confidence": self.confidence,
        }


@dataclass(slots=True)
class SourceInfo:
    """Format-independent description of the ingested file.

    ``unit`` says what ``page_number`` means: ``"page"`` (PDF), ``"slide"``
    (PPTX) or ``"document"`` (DOCX: one logical page, cite by heading path).
    """

    doc_id: str
    sha256: str
    file_name: str
    file_type: str  # "pdf" | "docx" | "pptx"
    file_size_bytes: int
    unit: str  # "page" | "slide" | "document"
    page_count: int = 0
    parser: str = ""
    ingested_at: str = ""
    title: str | None = None
    author: str | None = None
    created: str | None = None
    modified: str | None = None
    language: str | None = None

    def to_metadata(self) -> dict[str, Any]:
        """Flat dict of the non-empty fields (merged into ``Document.metadata``)."""
        values = {name: getattr(self, name) for name in self.__slots__}
        return {k: v for k, v in values.items() if v not in (None, "")}


@dataclass(slots=True)
class ImageData:
    """An image embedded in a PDF page, plus its OCR result (if OCR was run)."""

    page_number: int
    index: int
    xref: int
    width: int
    height: int
    bbox: tuple[float, float, float, float] | None = None
    smask: int = 0  # xref of the soft mask (transparency), 0 if none
    ocr_text: str = ""
    ocr_confidence: float | None = None  # mean word confidence, 0-100
    ocr_applied: bool = False  # OCR was attempted on this image
    ocr_skipped_reason: str | None = None  # e.g. "too_small", "no_text", "low_confidence"
    thumb_hash: str = ""  # 8x8 average hash: the same picture on several pages is a logo / template element
    distinct_colors: int = 0  # colours in a 32x32 thumbnail after quantising (0 = not measured)
    alt_text: str = ""  # author-supplied description (PPTX / DOCX), when present
    dominant_fraction: float = -1.0  # share of the most common colour (flat backgrounds: diagrams, charts)
    white_fraction: float = -1.0  # share of near-white pixels
    edge_density: float = -1.0  # share of pixels on a strong edge (line art) in a 64x64 thumbnail


@dataclass(slots=True)
class FigureData:
    """A figure the selection layer decided is worth understanding (chart, diagram, scientific figure ...).

    Source text is kept apart from anything generated: ``caption`` and ``inner_text`` / ``ocr_text`` are the
    author's words, ``description`` is reserved for a later model-generated summary and stays empty in Phase 0.
    """

    page_number: int
    index: int  # position in PageContent.figures
    kind: str  # raster | vector_region | caption_only | pptx_picture | docx_inline
    bbox: tuple[float, float, float, float] | None = None
    label: str = ""  # "Figure 3"
    number: str = ""  # "3", "2b"
    caption: str = ""
    caption_bbox: tuple[float, float, float, float] | None = None
    inner_text: str = ""  # text objects inside a vector figure (axis labels, legend), native and exact
    ocr_text: str = ""  # OCR of a raster figure
    ocr_confidence: float | None = None  # 0-1
    image_index: int | None = None  # index into PageContent.images for raster figures
    alt_text: str = ""
    figure_type: str = "unknown"  # chart | diagram | photo | screenshot | unknown (caption keywords only)
    selection_score: float = 0.0
    selection_reasons: list[str] = field(default_factory=list)
    mentions: list[str] = field(default_factory=list)  # sentences elsewhere in the text that cite this figure
    referenced_by: list[int] = field(default_factory=list)  # block orders of those sentences
    description: str = ""  # generated summary (Phase 1); empty means none
    description_status: str = "none"  # none | pending | done | failed | skipped
    image_sha256: str = ""

    @property
    def has_text(self) -> bool:
        return bool(self.caption or self.inner_text or self.ocr_text or self.alt_text)

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_number": self.page_number,
            "index": self.index,
            "kind": self.kind,
            "label": self.label,
            "caption": self.caption,
            "figure_type": self.figure_type,
            "selection_score": self.selection_score,
            "selection_reasons": list(self.selection_reasons),
            "bbox": list(self.bbox) if self.bbox else None,
            "referenced_by": list(self.referenced_by),
            "description_status": self.description_status,
        }


@dataclass(slots=True)
class TableData:
    """A table extracted from a page.

    ``rows`` holds the raw cell grid; the first row is treated as header.
    """

    page_number: int
    index: int
    rows: list[list[str]]
    bbox: tuple[float, float, float, float] | None = None

    @property
    def header(self) -> list[str]:
        return self.rows[0] if self.rows else []

    @property
    def n_rows(self) -> int:
        return len(self.rows)

    @property
    def n_cols(self) -> int:
        return max((len(r) for r in self.rows), default=0)

    def to_pipe_text(self) -> str:
        """Render as ``col | col`` lines."""
        return "\n".join(" | ".join(row) for row in self.rows)

    def to_key_value_text(self) -> str:            #3ashan llm ye3raf yefham el tables#
        """Render each data row as ``Header: value`` lines (RAG-friendly)."""
        if len(self.rows) < 2:
            return self.to_pipe_text()
        header = self.rows[0]
        blocks: list[str] = []
        for row in self.rows[1:]:
            lines = [
                f"{header[i] if i < len(header) and header[i] else f'Column {i + 1}'}: {cell}"
                for i, cell in enumerate(row)
                if cell
            ]
            if lines:
                blocks.append("\n".join(lines))
        return "\n\n".join(blocks)


@dataclass(slots=True)
class PageContent:
    """All extracted content for a single page (1-indexed)."""

    page_number: int
    text: str = ""
    ocr_text: str = ""
    tables: list[TableData] = field(default_factory=list)
    images: list[ImageData] = field(default_factory=list)
    figures: list[FigureData] = field(default_factory=list)
    size: tuple[float, float] | None = None  # (width, height) in points, when the format has pages
    page_type: PageType = PageType.TEXT_PAGE         #el default is text_page
    text_length: int = 0
    image_count: int = 0
    has_text: bool = False
    needs_ocr: bool = False
    ocr_applied: bool = False
    ocr_confidence: float | None = None  # 0-100 from Tesseract
    confidence: float = 1.0  # overall 0-1 extraction confidence
    final_text: str = ""
    warnings: list[str] = field(default_factory=list)
    blocks: list[Block] = field(default_factory=list)  # reading-order elements

    @property
    def images_with_text(self) -> list[ImageData]:
        """Embedded images that yielded OCR text."""
        return [img for img in self.images if img.ocr_text]


@dataclass(slots=True)
class Document:
    """A fully ingested document."""

    source_path: str
    pages: list[PageContent] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    statistics: dict[str, Any] = field(default_factory=dict)
    source: SourceInfo | None = None
    schema_version: str = SCHEMA_VERSION
    warnings: list[str] = field(default_factory=list)  # document-level warnings

    @property
    def unit(self) -> str:
        """What a page number means: ``page``, ``slide`` or ``document``."""
        return self.source.unit if self.source else "page"

    @property
    def blocks(self) -> list[Block]:
        """Every block of the document in reading order."""
        return [block for page in self.pages for block in page.blocks]

    @property
    def full_text(self) -> str:
        """Whole document with location markers, ready for chunking.

        The marker follows :attr:`unit`: ``[Page N]`` for PDF, ``[Slide N]``
        for PPTX and ``[Document]`` for DOCX (no real pages).
        """
        unit = self.unit
        return "\n\n".join(
            f"{page_marker(unit, p.page_number)}\n{p.final_text}"
            for p in self.pages
            if p.final_text
        )

    def get_page(self, page_number: int) -> PageContent | None:
        return next((p for p in self.pages if p.page_number == page_number), None)


def page_marker(unit: str, page_number: int) -> str:
    """Location marker line used in ``Document.full_text``."""
    if unit == "slide":
        return f"[Slide {page_number}]"
    if unit == "document":
        return "[Document]"
    return f"[Page {page_number}]"
