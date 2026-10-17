"""DOCX reader for the IntelliStudy document ingestion pipeline.

Converts a ``.docx`` file into the unified :class:`Document` model. Because DOCX
files are structured documents without true pages, the whole file is represented
as a single logical page (``page_number = 1``).

Extracted content, in original body order:
    * paragraphs and headings (empty paragraphs are skipped)
    * bulleted / numbered list items with their nesting level and number
    * tables (as :class:`TableData`), emitted where they appear in the body
    * embedded images (as :class:`ImageData`), each one OCR'd via the existing
      :class:`OCRProcessor`, emitted at the paragraph that references them
    * heading hierarchy (``Document.metadata["headings"]`` and, per block,
      ``Block.heading_path``)
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from docx import Document as load_docx
from docx.document import Document as DocxDocument
from docx.oxml.ns import qn
from docx.table import Table as DocxTable
from docx.text.paragraph import Paragraph as DocxParagraph

from ai.ingestion.cleaners import cell_clean, clean_text
from ai.ingestion.image_ocr import (
    SKIP_READ_FAILED,
    classify_page,
    compute_confidence,
    join_ocr_text,
    mean_ocr_confidence,
    ocr_image_blob,
)
from ai.ingestion.models import (
    Block,
    BlockType,
    Document,
    ImageData,
    IngestionError,
    PageContent,
    TableData,
)
from ai.ingestion.ocr_processor import OCRProcessor
from ai.ingestion.structure import (
    DOCX_NUMFMT_TO_SCHEME,
    TEXT_BLOCK_TYPES,
    build_source_info,
    finalize_document,
    format_number,
    render_blocks,
)

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

DOCX_SUFFIXES: frozenset[str] = frozenset({".docx"})
LOGICAL_PAGE_NUMBER: int = 1

_NS_DRAWINGML = "http://schemas.openxmlformats.org/drawingml/2006/main"
_NS_RELATIONSHIPS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NS_VML = "urn:schemas-microsoft-com:vml"

_BLIP_TAG = f"{{{_NS_DRAWINGML}}}blip"
_VML_IMAGE_TAG = f"{{{_NS_VML}}}imagedata"
_EMBED_ATTR = f"{{{_NS_RELATIONSHIPS}}}embed"
_VML_ID_ATTR = f"{{{_NS_RELATIONSHIPS}}}id"

_HEADING_STYLE = re.compile(r"^heading\s*(\d+)$", re.IGNORECASE)
_MAX_HEADING_LEVEL = 6
_TITLE_LEVEL = 0  # "Title" sits above Heading 1 in the hierarchy

# Where an image was found. Only the document body is scanned today.
IMAGE_SOURCE_BODY = "body"

_W_P = qn("w:p")
_W_TBL = qn("w:tbl")
_W_SDT = qn("w:sdt")
_W_SDT_CONTENT = qn("w:sdtContent")
_LIST_STYLE = re.compile(r"^list\s+(bullet|number|paragraph)(?:\s+(\d+))?$", re.IGNORECASE)
_MAX_LIST_DEPTH = 8


class DocxParseError(IngestionError):
    """The DOCX file could not be found, opened or parsed."""


# --------------------------------------------------------------------------- #
# Internal value objects
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class _RawImage:
    """An embedded image blob found in the DOCX, before decoding / OCR."""

    index: int
    rel_id: str
    blob: bytes
    partname: str
    source: str = IMAGE_SOURCE_BODY


@dataclass(slots=True)
class _ImageBatch:
    """Result of processing every embedded image."""

    images: list[ImageData] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    sources: dict[int, str] = field(default_factory=dict)  # image index -> source label
    rel_index: dict[str, int] = field(default_factory=dict)  # relationship id -> image index


@dataclass(slots=True)
class _Body:
    """The document body walked in order."""

    blocks: list[Block] = field(default_factory=list)
    tables: list[TableData] = field(default_factory=list)
    headings: list[dict[str, Any]] = field(default_factory=list)
    paragraph_count: int = 0


class _NumberingResolver:
    """Looks up the number format (``decimal``, ``bullet``, ...) of a list level.

    Resolution is best-effort: a document without a numbering part, or with an
    unusual definition, simply yields ``None`` and the caller falls back to the
    paragraph's style name.
    """

    def __init__(self, docx_doc: DocxDocument) -> None:
        self._root: Any = None
        try:
            self._root = docx_doc.part.numbering_part.element
        except Exception as exc:  # no numbering part
            logger.debug("No numbering part: %s", exc)
        self._cache: dict[tuple[str, int], str | None] = {}

    def number_format(self, num_id: str, level: int) -> str | None:
        key = (num_id, level)
        if key not in self._cache:
            self._cache[key] = self._lookup(num_id, level)
        return self._cache[key]

    def _lookup(self, num_id: str, level: int) -> str | None:
        if self._root is None:
            return None
        try:
            abstract = self._root.xpath(f'w:num[@w:numId="{num_id}"]/w:abstractNumId/@w:val')
            if not abstract:
                return None
            formats = self._root.xpath(
                f'w:abstractNum[@w:abstractNumId="{abstract[0]}"]'
                f'/w:lvl[@w:ilvl="{level}"]/w:numFmt/@w:val'
            )
            return str(formats[0]) if formats else None
        except Exception as exc:  # malformed numbering definitions
            logger.debug("Could not resolve numbering %s/%d: %s", num_id, level, exc)
            return None


# --------------------------------------------------------------------------- #
# Reader
# --------------------------------------------------------------------------- #


class DocxReader:
    """Reads DOCX files into the IntelliStudy :class:`Document` model.

    Args:
        ocr_processor: OCR component used for embedded images. A default
            :class:`OCRProcessor` is created when omitted (useful for
            dependency injection in tests or custom configuration).
    """

    def __init__(self, ocr_processor: OCRProcessor | None = None) -> None:
        self._ocr: OCRProcessor = ocr_processor or OCRProcessor()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def read(self, path: str | Path, *, check_suffix: bool = True) -> Document:
        """Read a DOCX file and return the unified :class:`Document`.

        Args:
            path: file to read.
            check_suffix: require a ``.docx`` extension. Pass ``False`` when the
                format was established another way (e.g. an upload's MIME type)
                and the stored filename has no usable extension.

        Raises:
            DocxParseError: if the file is missing, not a DOCX, or unreadable.
        """
        file_path = self._validate_path(path, check_suffix)
        docx_doc = self._open_docx(file_path)
        logger.info("Reading DOCX: %s", file_path)

        image_batch = self._extract_and_ocr_images(docx_doc)
        body = self._extract_body(docx_doc, image_batch)

        page = self._build_page(body, image_batch)
        metadata = self._build_metadata(
            docx_doc,
            file_path,
            headings=body.headings,
            images=page.images,
            image_sources=image_batch.sources,
        )
        source = build_source_info(
            file_path,
            "docx",
            page_count=1,
            title=metadata.get("title"),
            author=metadata.get("author"),
            created=metadata.get("created"),
            modified=metadata.get("modified"),
            language=metadata.get("language"),
        )
        document = Document(
            source_path=str(file_path),
            pages=[page],
            metadata=metadata,
            statistics=self._build_statistics(body, page),
            source=source,
        )
        finalize_document(document)
        logger.info(
            "Finished DOCX %s: %d paragraphs, %d headings, %d tables, "
            "%d images (%d with OCR text), confidence=%.3f",
            file_path.name,
            body.paragraph_count,
            len(body.headings),
            document.statistics["table_count"],
            document.statistics["image_count"],
            document.statistics["image_ocr_count"],
            page.confidence,
        )
        return document

    # ------------------------------------------------------------------ #
    # Opening / validation
    # ------------------------------------------------------------------ #

    @staticmethod
    def _validate_path(path: str | Path, check_suffix: bool = True) -> Path:
        file_path = Path(path)
        if not file_path.is_file():
            raise DocxParseError(f"DOCX file not found: {file_path}")
        if check_suffix and file_path.suffix.lower() not in DOCX_SUFFIXES:
            raise DocxParseError(
                f"Unsupported file type '{file_path.suffix}' (expected .docx): {file_path}"
            )
        return file_path

    @staticmethod
    def _open_docx(file_path: Path) -> DocxDocument:
        try:
            return load_docx(str(file_path))
        except Exception as exc:  # python-docx raises several unrelated types
            logger.exception("Failed to open DOCX: %s", file_path)
            raise DocxParseError(f"Could not open DOCX file '{file_path}': {exc}") from exc

    # ------------------------------------------------------------------ #
    # Body walk (paragraphs, lists, tables, images - in document order)
    # ------------------------------------------------------------------ #

    @staticmethod
    def _iter_body_elements(parent: Any) -> Iterator[Any]:
        """Yield ``w:p`` / ``w:tbl`` elements in order, looking inside content controls."""
        for child in parent.iterchildren():
            if child.tag in (_W_P, _W_TBL):
                yield child
            elif child.tag == _W_SDT:
                for content in child.iterchildren(_W_SDT_CONTENT):
                    yield from DocxReader._iter_body_elements(content)

    def _extract_body(self, docx_doc: DocxDocument, batch: _ImageBatch) -> _Body:
        """Walk the body once, emitting blocks in the order the author wrote them."""
        body = _Body()
        numbering = _NumberingResolver(docx_doc)
        counters: dict[str, dict[int, int]] = {}  # list id -> level -> last number
        placed: set[int] = set()  # image indexes already emitted as blocks
        parent = docx_doc._body

        for element in self._iter_body_elements(docx_doc.element.body):
            if element.tag == _W_P:
                paragraph = DocxParagraph(element, parent)
                text = clean_text(paragraph.text)  # same normalisation as PDF text
                if text:
                    body.paragraph_count += 1
                    self._emit_paragraph(body, paragraph, text, numbering, counters)
            else:
                self._emit_table(body, DocxTable(element, parent))
            self._emit_images(body, element, batch, placed)

        # Images referenced from places the walk did not reach: keep them anyway.
        for image in batch.images:
            if image.index not in placed and image.ocr_text:
                body.blocks.append(self._image_block(image))
        return body

    def _emit_paragraph(
        self,
        body: _Body,
        paragraph: Any,
        text: str,
        numbering: "_NumberingResolver",
        counters: dict[str, dict[int, int]],
    ) -> None:
        style_name = self._style_name(paragraph)
        heading_level = self._heading_level(style_name)
        if heading_level is not None:
            counters.clear()  # a heading restarts every running list
            body.headings.append({"level": heading_level, "text": text})
            body.blocks.append(
                Block(BlockType.HEADING, text, LOGICAL_PAGE_NUMBER, level=heading_level)
            )
            return

        item = self._list_info(paragraph, style_name, numbering)
        if item is None:
            body.blocks.append(Block(BlockType.PARAGRAPH, text, LOGICAL_PAGE_NUMBER))
            return

        list_id, level, scheme = item
        levels = counters.setdefault(list_id, {})
        for deeper in [lvl for lvl in levels if lvl > level]:
            del levels[deeper]  # a shallower item restarts nested numbering
        if scheme is None:
            marker = "-"
            levels.pop(level, None)
        else:
            number = levels.get(level, 0) + 1
            levels[level] = number
            marker = format_number(number, scheme)
        body.blocks.append(
            Block(
                BlockType.LIST_ITEM,
                text,
                LOGICAL_PAGE_NUMBER,
                level=level,
                list_marker=marker,
            )
        )

    @staticmethod
    def _list_info(
        paragraph: Any, style_name: str, numbering: "_NumberingResolver"
    ) -> tuple[str, int, str | None] | None:
        """``(list_id, level, number_scheme)`` for list paragraphs, else ``None``.

        ``number_scheme`` is ``None`` for bullets. Explicit numbering
        properties (``w:numPr``) are honoured first, then ``List Bullet`` /
        ``List Number`` style names.
        """
        style_match = _LIST_STYLE.match(style_name.strip())
        num_pr = None
        properties = paragraph._p.pPr
        if properties is not None:
            num_pr = properties.find(qn("w:numPr"))

        if num_pr is not None:
            ilvl = num_pr.find(qn("w:ilvl"))
            num_id = num_pr.find(qn("w:numId"))
            level = int(ilvl.get(qn("w:val"), 0)) if ilvl is not None else 0
            list_id = num_id.get(qn("w:val")) if num_id is not None else None
            if list_id == "0":  # numId 0 means "no list"
                return None
            if list_id is not None:
                fmt = numbering.number_format(list_id, level)
                scheme = None if fmt in (None, "bullet", "none") else DOCX_NUMFMT_TO_SCHEME.get(
                    fmt, "arabicPeriod"
                )
                if fmt is None and style_match and "number" in style_match.group(1).lower():
                    scheme = "arabicPeriod"
                return f"num:{list_id}", min(level, _MAX_LIST_DEPTH), scheme

        if style_match and style_match.group(1).lower() in ("bullet", "number"):
            kind = style_match.group(1).lower()
            level = int(style_match.group(2) or 1) - 1
            return (
                f"style:{kind}",
                min(max(level, 0), _MAX_LIST_DEPTH),
                "arabicPeriod" if kind == "number" else None,
            )
        return None

    def _emit_table(self, body: _Body, docx_table: DocxTable) -> None:
        index = len(body.tables)
        try:
            rows = self._table_to_rows(docx_table)
        except Exception as exc:
            logger.warning("Skipping table %d: %s", index, exc)
            return
        if not rows:
            return
        table = TableData(page_number=LOGICAL_PAGE_NUMBER, index=index, rows=rows)
        body.tables.append(table)
        body.blocks.append(
            Block(
                BlockType.TABLE,
                table.to_key_value_text().strip(),
                LOGICAL_PAGE_NUMBER,
                ref_index=index,
            )
        )

    def _emit_images(
        self, body: _Body, element: Any, batch: _ImageBatch, placed: set[int]
    ) -> None:
        """Emit an image block for each not-yet-placed picture inside ``element``."""
        for node in element.iter(_BLIP_TAG, _VML_IMAGE_TAG):
            rel_id = node.get(_EMBED_ATTR) or node.get(_VML_ID_ATTR)
            index = batch.rel_index.get(rel_id) if rel_id else None
            if index is None or index in placed:
                continue
            placed.add(index)
            image = batch.images[index]
            if image.ocr_text:
                body.blocks.append(self._image_block(image))

    @staticmethod
    def _image_block(image: ImageData) -> Block:
        confidence = None if image.ocr_confidence is None else image.ocr_confidence / 100.0
        return Block(
            BlockType.IMAGE_OCR,
            image.ocr_text,
            LOGICAL_PAGE_NUMBER,
            ref_index=image.index,
            confidence=confidence,
        )

    @staticmethod
    def _style_name(paragraph: Any) -> str:
        style = getattr(paragraph, "style", None)
        return style.name if style is not None and style.name else ""

    @staticmethod
    def _heading_level(style_name: str) -> int | None:
        """Map a paragraph style name to a heading level, or ``None`` if not a heading.

        ``Title`` -> 0, ``Heading N`` -> N (clamped to 1..6).
        """
        name = (style_name or "").strip()
        if name.lower() == "title":
            return _TITLE_LEVEL
        match = _HEADING_STYLE.match(name)
        if match:
            return min(max(int(match.group(1)), 1), _MAX_HEADING_LEVEL)
        return None

    # ------------------------------------------------------------------ #
    # Tables
    # ------------------------------------------------------------------ #

    @staticmethod
    def _table_to_rows(docx_table: DocxTable) -> list[list[str]]:
        """Convert a python-docx table to a grid of cleaned cell strings.

        Horizontally merged cells are reported repeatedly by python-docx; the
        repeats are collapsed so each physical cell appears once per row.
        """
        rows: list[list[str]] = []
        for row in docx_table.rows:
            cells: list[str] = []
            previous_tc: Any = None
            for cell in row.cells:
                if cell._tc is previous_tc:
                    continue
                previous_tc = cell._tc
                cells.append(cell_clean(cell.text))
            if any(cells):
                rows.append(cells)
        return rows

    # ------------------------------------------------------------------ #
    # Images + OCR
    # ------------------------------------------------------------------ #

    def _extract_and_ocr_images(self, docx_doc: DocxDocument) -> _ImageBatch:
        batch = _ImageBatch()
        for raw in self._iter_raw_images(docx_doc, batch):
            image_data, warning = self._process_raw_image(raw)
            batch.images.append(image_data)
            batch.sources[image_data.index] = raw.source
            if warning:
                batch.warnings.append(warning)
        return batch

    def _iter_image_containers(self, docx_doc: DocxDocument) -> Iterator[tuple[str, Any, Any]]:
        """Yield ``(source_label, xml_root, owning_part)`` for every region to scan for images.

        This is the single extension point for image discovery. The owning
        part matters because relationship ids (``rId1`` ...) are resolved
        *per part*: an image referenced from a header must be resolved through
        the header part, not the main document part.

        Currently only the document body is scanned. Because the body is
        scanned recursively, images inside text boxes and grouped drawing
        objects that live in the body are already reached incidentally, but
        without dedicated handling or labelling.

        TODO(header/footer images): for each ``section`` in ``docx_doc.sections``
            yield ``("header", section.header._element, section.header.part)``
            and the equivalent for ``section.footer`` (also first-page and
            even-page variants). Skip headers where ``is_linked_to_previous``
            is true to avoid scanning the same part repeatedly.
        TODO(textbox images): handle ``w:txbxContent`` / ``mc:AlternateContent``
            explicitly. Word often stores both an ``mc:Choice`` and an
            ``mc:Fallback`` (VML) copy of the same drawing, so skip the
            fallback branch to avoid duplicate images.
        TODO(grouped drawing objects): handle ``wpg:wgp`` / ``v:group`` by
            walking the group's children and preserving their order and, if
            useful, their group label as the ``source`` value.
        TODO(footnotes/endnotes/comments): same pattern as headers, using the
            corresponding related parts.
        """
        yield IMAGE_SOURCE_BODY, docx_doc.element.body, docx_doc.part

    def _iter_raw_images(
        self, docx_doc: DocxDocument, batch: _ImageBatch
    ) -> Iterator[_RawImage]:
        """Yield each distinct embedded image in document order.

        Images are located through their ``<a:blip>`` (DrawingML) and
        ``<v:imagedata>`` (legacy VML) references. An image part referenced
        several times is yielded once (deduplicated by part name, which is
        stable across parts) to avoid duplicated OCR text.

        Images whose data cannot be read are recorded in ``batch`` as failed
        :class:`ImageData` so they count against extraction confidence.
        """
        seen_partnames: dict[str, int] = {}  # part name -> image index
        index = 0
        for source, root, owner_part in self._iter_image_containers(docx_doc):
            for element in root.iter(_BLIP_TAG, _VML_IMAGE_TAG):
                rel_id = element.get(_EMBED_ATTR) or element.get(_VML_ID_ATTR)
                if not rel_id:
                    continue
                try:
                    part = owner_part.related_parts[rel_id]
                    partname = str(part.partname)
                    if partname in seen_partnames:
                        batch.rel_index[rel_id] = seen_partnames[partname]
                        continue
                    blob = part.blob
                except Exception as exc:
                    message = f"Image {index + 1}: could not read image data ({exc})"
                    logger.warning(message)
                    batch.warnings.append(message)
                    batch.images.append(
                        ImageData(
                            page_number=LOGICAL_PAGE_NUMBER,
                            index=index,
                            xref=0,
                            width=0,
                            height=0,
                            ocr_skipped_reason=SKIP_READ_FAILED,
                        )
                    )
                    batch.sources[index] = source
                    batch.rel_index[rel_id] = index
                    index += 1
                    continue
                seen_partnames[partname] = index
                batch.rel_index[rel_id] = index
                yield _RawImage(
                    index=index, rel_id=rel_id, blob=blob, partname=partname, source=source
                )
                index += 1

    def _process_raw_image(self, raw: _RawImage) -> tuple[ImageData, str | None]:
        """Decode one image, run OCR, and build its :class:`ImageData`.

        Never raises: failures are reported via the returned warning string.
        The decode / OCR / outcome handling is shared with the PPTX reader
        (:func:`ai.ingestion.image_ocr.ocr_image_blob`).
        """
        image_data = ImageData(
            page_number=LOGICAL_PAGE_NUMBER,
            index=raw.index,
            xref=0,  # PDF-specific concept; not applicable to DOCX
            width=0,
            height=0,
        )
        label = f"Image {raw.index + 1} ({raw.partname})"
        detail = ocr_image_blob(self._ocr, raw.blob, image_data, label)
        return image_data, (f"{label}: {detail}" if detail else None)

    # ------------------------------------------------------------------ #
    # Page assembly
    # ------------------------------------------------------------------ #

    def _build_page(self, body: _Body, image_batch: _ImageBatch) -> PageContent:
        images = image_batch.images
        tables = body.tables
        text = render_blocks(body.blocks, TEXT_BLOCK_TYPES)
        ocr_text = join_ocr_text(images)
        final_text = render_blocks(body.blocks)  # original order, tables and images inline

        return PageContent(
            page_number=LOGICAL_PAGE_NUMBER,
            text=text,
            ocr_text=ocr_text,
            tables=tables,
            images=images,
            page_type=classify_page(text, tables, images),
            text_length=len(text),
            image_count=len(images),
            has_text=bool(text),
            needs_ocr=False,
            ocr_applied=any(img.ocr_applied for img in images),
            ocr_confidence=mean_ocr_confidence(images),
            confidence=compute_confidence(images),
            final_text=final_text,
            warnings=list(image_batch.warnings),
            blocks=body.blocks,
        )

    # ------------------------------------------------------------------ #
    # Metadata / statistics
    # ------------------------------------------------------------------ #

    def _build_metadata(
        self,
        docx_doc: DocxDocument,
        file_path: Path,
        headings: list[dict[str, Any]] | None = None,
        images: list[ImageData] | None = None,
        image_sources: dict[int, str] | None = None,
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "file_name": file_path.name,
            "file_type": "docx",
            "file_size_bytes": file_path.stat().st_size,
            "page_model": "single_logical_page",
            "headings": list(headings or []),
            "images": self._build_image_metadata(images or [], image_sources or {}),
        }
        try:
            props = docx_doc.core_properties
            for key in ("title", "author", "subject", "keywords", "language"):
                value = getattr(props, key, None)
                if value:
                    metadata[key] = str(value)
            for key in ("created", "modified"):
                value = getattr(props, key, None)
                if value:
                    metadata[key] = value.isoformat()
        except Exception as exc:  # metadata is best-effort
            logger.debug("Could not read DOCX core properties: %s", exc)
        return metadata

    @staticmethod
    def _build_image_metadata(
        images: list[ImageData], sources: dict[int, str]
    ) -> list[dict[str, Any]]:
        """Per-image diagnostics for analytics and debugging."""
        return [
            {
                "index": img.index,
                "width": img.width,
                "height": img.height,
                "ocr_applied": img.ocr_applied,
                "ocr_confidence": (
                    round(img.ocr_confidence, 1) if img.ocr_confidence is not None else None
                ),
                "ocr_skipped_reason": img.ocr_skipped_reason,
                "source": sources.get(img.index, IMAGE_SOURCE_BODY),
            }
            for img in images
        ]

    @staticmethod
    def _build_statistics(body: _Body, page: PageContent) -> dict[str, Any]:
        """Legacy DOCX keys; canonical keys are merged in by ``finalize_document``."""
        return {
            "paragraph_count": body.paragraph_count,
            "table_count": len(page.tables),
            "image_count": len(page.images),
            "image_ocr_count": len(page.images_with_text),
            "total_characters": len(page.final_text),
        }


# --------------------------------------------------------------------------- #
# Convenience function
# --------------------------------------------------------------------------- #


def read_docx(path: str | Path, ocr_processor: OCRProcessor | None = None) -> Document:
    """Read a DOCX file into a :class:`Document` using a one-off :class:`DocxReader`."""
    return DocxReader(ocr_processor=ocr_processor).read(path)
