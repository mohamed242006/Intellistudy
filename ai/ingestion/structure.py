"""Format-independent document structure helpers.

Everything that makes PDF, DOCX and PPTX output look the same lives here:

* :func:`parse_markdown_blocks` / :func:`render_blocks` - text <-> :class:`Block`
* :func:`assign_heading_paths` - ``heading_path`` for hierarchical chunking
* :func:`build_source_info` - the canonical :class:`SourceInfo`
* :func:`canonical_statistics` / :func:`finalize_document` - one statistics
  schema (plus each reader's legacy keys) and global block ordering
* :func:`format_number` - list numbering shared by DOCX and PPTX
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from importlib import metadata as importlib_metadata
from pathlib import Path

from ai.ingestion.models import (
    SCHEMA_VERSION,
    Block,
    BlockType,
    Document,
    SourceInfo,
)

logger = logging.getLogger(__name__)

LOW_CONFIDENCE_THRESHOLD = 0.6
MAX_HEADING_LEVEL = 6
LIST_INDENT = "  "

_HEADING_LINE = re.compile(r"^(#{1,6})\s+(\S.*)$")
_BULLET_LINE = re.compile(r"^( *)[-*•]\s+(\S.*)$")

# Unit of ``page_number`` per file type.
UNIT_BY_FILE_TYPE = {"pdf": "page", "pptx": "slide", "docx": "document"}


# --------------------------------------------------------------------------- #
# Markdown-ish text -> blocks
# --------------------------------------------------------------------------- #


def parse_markdown_blocks(
    text: str,
    page_number: int,
    bbox: tuple[float, float, float, float] | None = None,
) -> list[Block]:
    """Split text that uses ``#`` headings and ``- `` bullets into blocks.

    Used for PDF native text and OCR text, which are produced as marked-up
    strings. ``order`` and ``heading_path`` are filled in later by
    :func:`finalize_document`.
    """
    blocks: list[Block] = []
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            blocks.append(
                Block(BlockType.PARAGRAPH, "\n".join(paragraph), page_number, bbox=bbox)
            )
            paragraph.clear()

    for raw in text.split("\n"):
        line = raw.rstrip()
        if not line.strip():
            flush()
            continue
        heading = _HEADING_LINE.match(line)
        if heading:
            flush()
            blocks.append(
                Block(
                    BlockType.HEADING,
                    heading.group(2).strip(),
                    page_number,
                    level=len(heading.group(1)),
                    bbox=bbox,
                )
            )
            continue
        bullet = _BULLET_LINE.match(line)
        if bullet:
            flush()
            blocks.append(
                Block(
                    BlockType.LIST_ITEM,
                    bullet.group(2).strip(),
                    page_number,
                    level=len(bullet.group(1)) // 2,
                    list_marker="-",
                    bbox=bbox,
                )
            )
            continue
        paragraph.append(line.strip())
    flush()
    return blocks


# --------------------------------------------------------------------------- #
# Blocks -> text
# --------------------------------------------------------------------------- #

_LABELLED = {
    BlockType.CHART: "[Chart]",
    BlockType.NOTES: "[Speaker Notes]",
}


def render_block(block: Block) -> str:
    """Text form of one block, with its marker label where it has one."""
    if block.type is BlockType.HEADING:
        return f"{'#' * max(block.level or 1, 1)} {block.text}"
    if block.type is BlockType.LIST_ITEM:
        marker = block.list_marker or "-"
        return f"{LIST_INDENT * (block.level or 0)}{marker} {block.text}"
    if block.type is BlockType.TABLE:
        label = f"[Table {block.ref_index + 1}]" if block.ref_index is not None else "[Table]"
        return f"{label}\n{block.text}"
    if block.type is BlockType.IMAGE_OCR:
        index = f" {block.ref_index + 1}" if block.ref_index is not None else ""
        return f"[Embedded Image{index} OCR]\n{block.text}"
    fixed_label = _LABELLED.get(block.type)
    if fixed_label:
        return f"{fixed_label}\n{block.text}"
    return block.text


def render_blocks(blocks: Iterable[Block], types: Iterable[BlockType] | None = None) -> str:
    """Join blocks into reading-order text (consecutive list items stay tight).

    Args:
        blocks: blocks in reading order.
        types: when given, only blocks of these types are rendered.
    """
    wanted = set(types) if types is not None else None
    parts: list[str] = []
    previous_was_list = False
    for block in blocks:
        if wanted is not None and block.type not in wanted:
            continue
        text = render_block(block)
        if not text.strip():
            continue
        is_list = block.type is BlockType.LIST_ITEM
        if parts and is_list and previous_was_list:
            parts[-1] = f"{parts[-1]}\n{text}"
        else:
            parts.append(text)
        previous_was_list = is_list
    return "\n\n".join(parts)


#: Block types that make up a page's running text (``PageContent.text``).
TEXT_BLOCK_TYPES = (
    BlockType.HEADING,
    BlockType.PARAGRAPH,
    BlockType.LIST_ITEM,
    BlockType.CHART,
)


# --------------------------------------------------------------------------- #
# Heading paths
# --------------------------------------------------------------------------- #


def assign_heading_paths(blocks: Iterable[Block], *, carry_across_pages: bool = True) -> None:
    """Fill ``heading_path`` on every block (in place).

    A stack of open headings is kept: a heading closes every open heading of
    the same or deeper level, then opens itself. With
    ``carry_across_pages=False`` (slides) the stack resets whenever the page
    changes, so each slide is its own root.
    """
    stack: list[tuple[int, str]] = []
    current_page: int | None = None
    for block in blocks:
        if not carry_across_pages and block.page_number != current_page:
            stack.clear()
        current_page = block.page_number

        if block.type is BlockType.HEADING:
            level = block.level if block.level is not None else 1
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, block.text))
        block.heading_path = tuple(text for _, text in stack)


def _normalise_title(text: str) -> str:
    return re.sub(r"[\W_]+", " ", text.casefold()).strip()


def apply_outline_levels(document: Document, outline: list[tuple[int, str, int]]) -> int:
    """Use a PDF's bookmark outline as the authority for heading levels.

    Args:
        document: the document whose heading blocks are adjusted.
        outline: ``(level, title, page_number)`` entries (1-based levels).

    Returns:
        How many heading blocks were re-levelled.
    """
    if not outline:
        return 0
    by_page: dict[int, dict[str, int]] = {}
    for level, title, page in outline:
        by_page.setdefault(page, {}).setdefault(_normalise_title(title), level)

    changed = 0
    for doc_page in document.pages:
        titles = by_page.get(doc_page.page_number)
        if not titles:
            continue
        for block in doc_page.blocks:
            if block.type is not BlockType.HEADING:
                continue
            new_level = titles.get(_normalise_title(block.text))
            if new_level is not None:
                block.level = min(max(new_level, 1), MAX_HEADING_LEVEL)
                changed += 1
    return changed


# --------------------------------------------------------------------------- #
# Source info
# --------------------------------------------------------------------------- #


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _package_version(name: str) -> str:
    try:
        return f"{name} {importlib_metadata.version(name)}"
    except importlib_metadata.PackageNotFoundError:
        return name


PARSER_PACKAGE = {"pdf": "pymupdf", "docx": "python-docx", "pptx": "python-pptx"}


def build_source_info(
    path: str | Path,
    file_type: str,
    *,
    page_count: int,
    title: str | None = None,
    author: str | None = None,
    created: str | None = None,
    modified: str | None = None,
    language: str | None = None,
) -> SourceInfo:
    """Create the canonical :class:`SourceInfo` for a file on disk."""
    file_path = Path(path)
    digest = _sha256(file_path)
    return SourceInfo(
        doc_id=digest[:16],
        sha256=digest,
        file_name=file_path.name,
        file_type=file_type,
        file_size_bytes=file_path.stat().st_size,
        unit=UNIT_BY_FILE_TYPE[file_type],
        page_count=page_count,
        parser=_package_version(PARSER_PACKAGE[file_type]),
        ingested_at=datetime.now(UTC).isoformat(timespec="seconds"),
        title=title or None,
        author=author or None,
        created=created or None,
        modified=modified or None,
        language=language,
    )


def pdf_date_to_iso(value: object) -> str | None:
    """Best-effort conversion of a PDF date (``D:20240131120000+02'00'``) to ISO."""
    if not isinstance(value, str):
        return None
    match = re.match(r"D:(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?", value)
    if not match:
        return None
    defaults = (0, 1, 1, 0, 0, 0)
    year, month, day, hour, minute, second = (
        int(group) if group else default for group, default in zip(match.groups(), defaults, strict=True)
    )
    try:
        return datetime(year, month, day, hour, minute, second).isoformat()
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# Statistics + finalisation
# --------------------------------------------------------------------------- #


def canonical_statistics(document: Document) -> dict[str, object]:
    """Statistics with the same keys for every document type."""
    pages = document.pages
    blocks = document.blocks
    confidences = [page.confidence for page in pages]

    def count(kind: BlockType) -> int:
        return sum(1 for block in blocks if block.type is kind)

    return {
        "page_count": len(pages),
        "unit": document.unit,
        "block_count": len(blocks),
        "heading_count": count(BlockType.HEADING),
        "list_item_count": count(BlockType.LIST_ITEM),
        "table_count": sum(len(page.tables) for page in pages),
        "image_count": sum(len(page.images) for page in pages),
        "image_ocr_count": sum(len(page.images_with_text) for page in pages),
        "chart_count": count(BlockType.CHART),
        "total_characters": sum(len(page.final_text) for page in pages),
        "average_confidence": (
            round(sum(confidences) / len(confidences), 3) if confidences else 0.0
        ),
        "low_confidence_pages": [
            page.page_number for page in pages if page.confidence < LOW_CONFIDENCE_THRESHOLD
        ],
        "warning_count": sum(len(page.warnings) for page in pages) + len(document.warnings),
    }


def finalize_document(document: Document, *, carry_across_pages: bool = True) -> Document:
    """Complete a freshly built document so every format ends up identical in shape.

    * numbers blocks globally (``order``) and fills ``heading_path``;
    * merges :func:`canonical_statistics` over the reader's legacy statistics;
    * flattens :class:`SourceInfo` into ``metadata`` (existing keys win).
    """
    order = 0
    for page in document.pages:
        for block in page.blocks:
            block.order = order
            order += 1
    assign_heading_paths(document.blocks, carry_across_pages=carry_across_pages)

    merged = dict(document.statistics)
    merged.update(canonical_statistics(document))
    document.statistics = merged

    if document.source is not None:
        for key, value in document.source.to_metadata().items():
            document.metadata.setdefault(key, value)
    document.metadata["schema_version"] = SCHEMA_VERSION
    document.schema_version = SCHEMA_VERSION
    return document


# --------------------------------------------------------------------------- #
# Citations
# --------------------------------------------------------------------------- #


def citation_label(block: Block, unit: str) -> str:
    """Human-readable location, e.g. ``"slide 4"`` or ``"p. 12 > Caching > LRU"``."""
    where = {"page": f"p. {block.page_number}", "slide": f"slide {block.page_number}"}.get(unit, "")
    trail = " > ".join(block.heading_path)
    return " > ".join(part for part in (where, trail) if part) or "document"


# --------------------------------------------------------------------------- #
# List numbering (OOXML auto-number schemes)
# --------------------------------------------------------------------------- #

# DOCX ``w:numFmt`` values mapped to the PPTX ``a:buAutoNum`` scheme names.
DOCX_NUMFMT_TO_SCHEME = {
    "decimal": "arabicPeriod",
    "lowerLetter": "alphaLcPeriod",
    "upperLetter": "alphaUcPeriod",
    "lowerRoman": "romanLcPeriod",
    "upperRoman": "romanUcPeriod",
}


def format_number(number: int, scheme: str) -> str:
    """Render an auto-number such as ``1.``, ``a)``, ``(iv)`` from its OOXML scheme."""
    if scheme.startswith(("alphaLc", "alphaUc")):
        body, n = "", number
        while n > 0:
            n, rem = divmod(n - 1, 26)
            body = chr(ord("a") + rem) + body
        if scheme.startswith("alphaUc"):
            body = body.upper()
    elif scheme.startswith(("romanLc", "romanUc")):
        body, n = "", number
        for value, symbol in (
            (1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"),
            (50, "l"), (40, "xl"), (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i"),
        ):
            count, n = divmod(n, value)
            body += symbol * count
        if scheme.startswith("romanUc"):
            body = body.upper()
    else:
        body = str(number)

    if scheme.endswith("ParenBoth"):
        return f"({body})"
    if scheme.endswith("ParenR"):
        return f"{body})"
    if scheme.endswith("Plain"):
        return body
    return f"{body}."
