"""PPTX reader for the IntelliStudy document ingestion pipeline.

Converts a ``.pptx`` file into the unified :class:`Document` model. PowerPoint
is slide-based, so every slide becomes one :class:`PageContent`
(``page_number`` == slide number, 1-indexed).

Extracted content, per slide:
    * title (also when it lives inside a group), text boxes, placeholders and
      bullet / numbered lists with nesting (in reading order)
    * charts: title, type, axis labels, series and legend entries
    * speaker notes
    * tables (as :class:`TableData`), with merged cells resolved
    * embedded pictures (as :class:`ImageData`), each one OCR'd via the existing
      :class:`OCRProcessor`; identical pictures are OCR'd only once per file

Document-level metadata:
    * ``metadata["slides"]``: slide number / title / hidden flag (for citations
      and filtering)
    * ``metadata["images"]``: per-image OCR diagnostics
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from pptx import Presentation as load_pptx
from pptx.enum.shapes import PP_PLACEHOLDER
from pptx.oxml.ns import qn
from pptx.presentation import Presentation as PptxPresentation
from pptx.shapes.graphfrm import GraphicFrame
from pptx.shapes.group import GroupShape
from pptx.shapes.picture import Picture
from pptx.slide import Slide

from ai.ingestion.cleaners import cell_clean, clean_text
from ai.ingestion.figure_selection import SelectionConfig, figure_features, select_figures
from ai.ingestion.figures import Caption, figure_block, guess_figure_type, horizontal_overlap, parse_caption
from ai.ingestion.image_ocr import (
    SCORE_SKIPPED_DEFAULT,
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
    FigureData,
    ImageData,
    IngestionError,
    PageContent,
    TableData,
)
from ai.ingestion.ocr_processor import OCRProcessor
from ai.ingestion.structure import (
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

PPTX_SUFFIXES: frozenset[str] = frozenset({".pptx"})

_VERTICAL_TAB = "\x0b"  # python-pptx represents soft line breaks as vertical tabs

# Reading order: shapes whose tops fall in the same ~0.1" band count as one row,
# so side-by-side boxes that differ slightly in Y are read left-to-right.
_ROW_BUCKET_EMU = 100_000

_INFERRED_TITLE_MIN_PT = 18.0
_TITLE_PLACEHOLDERS = (PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE)
# Body-like placeholders inherit bullets from the slide master even when the
# paragraph itself carries no explicit bullet properties.
_BULLETED_PLACEHOLDERS = (PP_PLACEHOLDER.BODY, PP_PLACEHOLDER.OBJECT)
# Slide furniture repeated on every slide: its text ("6", a date) is not content.
_FURNITURE_PLACEHOLDERS = (
    PP_PLACEHOLDER.SLIDE_NUMBER,
    PP_PLACEHOLDER.FOOTER,
    PP_PLACEHOLDER.DATE,
)

_MAX_CHART_ITEMS = 50  # cap categories / series listed per chart

# --- EMF / WMF detection ---------------------------------------------------- #
# PIL can only rasterise these on Windows; elsewhere they are reported as the
# shared ``unsupported_format`` skip instead of a decode failure.
_VECTOR_EXTENSIONS: frozenset[str] = frozenset({"emf", "wmf"})
_WMF_PLACEABLE_MAGIC = b"\xd7\xcd\xc6\x9a"
_EMF_SIGNATURE = b" EMF"  # at byte offset 40 of an EMF header

# Charts take part in the slide confidence mean alongside images.
_SCORE_CHART_OK = 1.0
_SCORE_CHART_UNREADABLE = 0.5  # chart present but nothing could be extracted


class PptxParseError(IngestionError):
    """The PPTX file could not be found, opened or parsed."""


# --------------------------------------------------------------------------- #
# Internal value objects
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class _RawImage:
    """A picture blob found on a slide, before decoding / OCR."""

    slide_number: int
    index: int
    blob: bytes
    name: str
    sha1: str = ""  # content hash, used as the OCR cache key
    ext: str = ""  # file extension reported by python-pptx ("" if unknown)


@dataclass(slots=True)
class _SlideData:
    """A processed slide: its page plus the metadata needed for citations."""

    page: PageContent
    title: str
    has_notes: bool
    hidden: bool = False


# OCR cache for one read(): picture sha1 -> (first ImageData, warning detail).
_OcrCache = dict[str, tuple[ImageData, "str | None"]]


# --------------------------------------------------------------------------- #
# Reader
# --------------------------------------------------------------------------- #


class PptxReader:
    """Reads PPTX files into the IntelliStudy :class:`Document` model.

    Args:
        ocr_processor: OCR component used for embedded images. A default
            :class:`OCRProcessor` is created when omitted (useful for
            dependency injection in tests or custom configuration).
    """

    def __init__(
        self, ocr_processor: OCRProcessor | None = None, figure_config: SelectionConfig | None = None
    ) -> None:
        self._ocr: OCRProcessor = ocr_processor or OCRProcessor()
        self._figure_config = figure_config or SelectionConfig()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def read(self, path: str | Path, *, check_suffix: bool = True) -> Document:
        """Read a PPTX file and return the unified :class:`Document`.

        Args:
            path: file to read.
            check_suffix: require a ``.pptx`` extension. Pass ``False`` when the
                format was established another way (e.g. an upload's MIME type)
                and the stored filename has no usable extension.

        Raises:
            PptxParseError: if the file is missing, not a PPTX, or unreadable.
        """
        file_path = self._validate_path(path, check_suffix)
        presentation = self._open_presentation(file_path)
        logger.info("Reading PPTX: %s", file_path)

        # Scoped to this call (not the instance) so concurrent reads on one
        # reader never share state and the cache cannot grow across files.
        ocr_cache: _OcrCache = {}
        slides = [
            self._read_slide(slide, slide_number, ocr_cache)
            for slide_number, slide in enumerate(presentation.slides, start=1)
        ]
        pages = [item.page for item in slides]

        metadata = self._build_metadata(presentation, file_path, slides)
        source = build_source_info(
            file_path,
            "pptx",
            page_count=len(pages),
            title=metadata.get("title"),
            author=metadata.get("author"),
            created=metadata.get("created"),
            modified=metadata.get("modified"),
            language=metadata.get("language"),
        )
        document = Document(
            source_path=str(file_path),
            pages=pages,
            metadata=metadata,
            statistics=self._build_statistics(slides),
            source=source,
        )
        figure_summary = self._figure_pass(
            pages, ((presentation.slide_width or 9144000) / 12700, (presentation.slide_height or 6858000) / 12700)
        )
        if figure_summary:
            document.metadata["figures"] = figure_summary
        # Every slide is its own root: heading paths must not leak across slides.
        finalize_document(document, carry_across_pages=False)
        logger.info(
            "Finished PPTX %s: %d slides, %d tables, %d images (%d with OCR text)",
            file_path.name,
            document.statistics["slide_count"],
            document.statistics["table_count"],
            document.statistics["image_count"],
            document.statistics["image_ocr_count"],
        )
        return document

    # ------------------------------------------------------------------ #
    # Opening / validation
    # ------------------------------------------------------------------ #

    @staticmethod
    def _validate_path(path: str | Path, check_suffix: bool = True) -> Path:
        file_path = Path(path)
        if not file_path.is_file():
            raise PptxParseError(f"PPTX file not found: {file_path}")
        if check_suffix and file_path.suffix.lower() not in PPTX_SUFFIXES:
            raise PptxParseError(
                f"Unsupported file type '{file_path.suffix}' (expected .pptx): {file_path}"
            )
        return file_path

    @staticmethod
    def _open_presentation(file_path: Path) -> PptxPresentation:
        try:
            return load_pptx(str(file_path))
        except Exception as exc:  # python-pptx raises several unrelated types
            logger.exception("Failed to open PPTX: %s", file_path)
            raise PptxParseError(f"Could not open PPTX file '{file_path}': {exc}") from exc

    # ------------------------------------------------------------------ #
    # Slide processing
    # ------------------------------------------------------------------ #

    def _read_slide(self, slide: Slide, slide_number: int, ocr_cache: _OcrCache) -> _SlideData:
        """Process one slide. Never raises: a broken slide becomes an empty page."""
        hidden = self._is_hidden(slide)
        try:
            return self._build_slide(slide, slide_number, hidden, ocr_cache)
        except Exception as exc:
            logger.exception("Slide %d could not be processed", slide_number)
            page = PageContent(
                page_number=slide_number,
                confidence=0.0,
                warnings=[f"Slide {slide_number}: extraction failed ({exc})"],
            )
            return _SlideData(page=page, title="", has_notes=False, hidden=hidden)

    def _build_slide(
        self, slide: Slide, slide_number: int, hidden: bool, ocr_cache: _OcrCache
    ) -> _SlideData:
        """Walk the slide's shapes once, in reading order, emitting blocks."""
        warnings: list[str] = []
        shapes = list(self._iter_shapes(slide.shapes))
        title_shape, title = self._extract_title(slide, shapes)

        blocks: list[Block] = []
        tables: list[TableData] = []
        images: list[ImageData] = []
        chart_scores: list[float] = []

        if title:
            blocks.append(Block(BlockType.HEADING, title, slide_number, level=1))

        for shape in shapes:
            # python-pptx builds a fresh proxy per access, so ``is`` never
            # matches; ``==`` compares the underlying XML element instead.
            if title_shape is not None and shape == title_shape:
                continue
            blocks.extend(self._text_blocks(shape, slide_number))

            chart_texts, scores = self._extract_charts([shape], slide_number, warnings)
            chart_scores.extend(scores)
            blocks.extend(Block(BlockType.CHART, text, slide_number) for text in chart_texts)

            for table in self._extract_tables([shape], slide_number, warnings, len(tables)):
                tables.append(table)
                blocks.append(
                    Block(
                        BlockType.TABLE,
                        table.to_key_value_text().strip(),
                        slide_number,
                        ref_index=table.index,
                    )
                )

            for image in self._extract_and_ocr_images(
                [shape], slide_number, warnings, ocr_cache, len(images)
            ):
                images.append(image)
                if image.ocr_text:
                    confidence = (
                        None if image.ocr_confidence is None else image.ocr_confidence / 100.0
                    )
                    blocks.append(
                        Block(
                            BlockType.IMAGE_OCR,
                            image.ocr_text,
                            slide_number,
                            ref_index=image.index,
                            confidence=confidence,
                        )
                    )

        notes = self._extract_notes(slide, slide_number, warnings)
        if notes:
            blocks.append(Block(BlockType.NOTES, notes, slide_number))

        page = self._build_page(slide_number, blocks, tables, images, chart_scores, warnings)
        page.figures = self._figure_candidates(shapes, images, slide_number)
        return _SlideData(page=page, title=title, has_notes=bool(notes), hidden=hidden)

    def _figure_candidates(self, shapes: list[Any], images: list[ImageData], slide_number: int) -> list[FigureData]:
        """One candidate per picture, with the nearest "Figure N: ..." text box as its caption."""
        captions: list[tuple[Caption, tuple[float, float, float, float]]] = []
        for shape in shapes:
            if not getattr(shape, "has_text_frame", False):
                continue
            box = self._shape_bbox(shape)
            text = " ".join(clean_text(shape.text_frame.text.replace(_VERTICAL_TAB, " ")).split())
            parsed = parse_caption(text, bold_label=False) if text else None
            if parsed is not None and box is not None:
                captions.append((parsed, box))
        taken: set[int] = set()
        candidates: list[FigureData] = []
        for image in images:
            if image.width <= 0 or image.bbox is None:
                continue
            best: tuple[float, int] | None = None
            for number, (_caption, box) in enumerate(captions):
                if number in taken or horizontal_overlap(image.bbox, box) < 0.3:
                    continue
                below, above = box[1] - image.bbox[3], image.bbox[1] - box[3]
                gap = below if -6 <= below <= 80 else above if -6 <= above <= 40 else None
                if gap is not None and (best is None or gap < best[0]):
                    best = (gap, number)
            figure = FigureData(
                page_number=slide_number,
                index=len(candidates),
                kind="pptx_picture",
                bbox=image.bbox,
                image_index=image.index,
                alt_text=image.alt_text,
            )
            if best is not None:
                taken.add(best[1])
                caption, box = captions[best[1]]
                figure.label, figure.number, figure.caption, figure.caption_bbox = caption.label, caption.number, caption.text, box
                figure.figure_type = guess_figure_type(caption.text)
            candidates.append(figure)
        for number, (caption, box) in enumerate(captions):
            if number not in taken:  # a caption whose graphic is not a picture (shapes, SmartArt)
                candidates.append(
                    FigureData(
                        page_number=slide_number,
                        index=len(candidates),
                        kind="caption_only",
                        bbox=box,
                        label=caption.label,
                        number=caption.number,
                        caption=caption.text,
                        caption_bbox=box,
                        figure_type=guess_figure_type(caption.text),
                    )
                )
        return candidates

    def _figure_pass(self, pages: list[PageContent], size: tuple[float, float]) -> dict[str, Any]:
        """Select figures over the whole deck, then swap the OCR blocks of kept pictures for figure blocks."""
        for page in pages:
            page.size = size
        candidates = sum(len(p.figures) for p in pages)
        if not candidates:
            return {}
        decisions = select_figures(pages, self._figure_config)
        kept_ids = {id(f) for f, d in decisions if d.keep}
        skipped = [{"page": f.page_number, "kind": f.kind, "reasons": list(d.reasons)} for f, d in decisions if not d.keep]
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
            if page.figures:
                self._swap_blocks_for_figures(page)
        return {"candidates": candidates, "kept": kept, "skipped": skipped[:200], "decisions": detail[:1000]}

    @staticmethod
    def _swap_blocks_for_figures(page: PageContent) -> None:
        blocks = page.blocks
        for figure in page.figures:
            source = page.images[figure.image_index] if figure.image_index is not None else None
            if source is not None:
                figure.ocr_text = source.ocr_text
                figure.ocr_confidence = None if source.ocr_confidence is None else source.ocr_confidence / 100.0
            position = len(blocks)
            if source is not None:
                for i, block in enumerate(blocks):
                    if block.type is BlockType.IMAGE_OCR and block.ref_index == source.index:
                        position = i
                        blocks.pop(i)
                        break
            if figure.caption:  # the caption now lives in the figure block
                wanted = " ".join(figure.caption.split())
                for i, block in enumerate(blocks):
                    if block.type is BlockType.PARAGRAPH and " ".join(block.text.split()) in wanted and len(block.text) > 3:
                        if i < position:
                            position -= 1
                        blocks.pop(i)
                        break
            block = figure_block(figure)
            if block.text.strip():
                if position == len(blocks) and blocks and blocks[-1].type is BlockType.NOTES:
                    position -= 1
                blocks.insert(position, block)
        page.text = render_blocks(blocks, TEXT_BLOCK_TYPES)
        page.final_text = render_blocks(blocks)

    @staticmethod
    def _is_hidden(slide: Slide) -> bool:
        """True when the slide is hidden in slide-show mode (``<p:sld show="0">``).

        Hidden slides are kept (not discarded) and only flagged, so callers
        can decide whether to filter them out later.
        """
        try:
            return str(slide._element.get("show", "1")).lower() in {"0", "false"}
        except Exception as exc:  # defensive: never let metadata break a slide
            logger.debug("Could not read slide 'show' attribute: %s", exc)
            return False

    # ------------------------------------------------------------------ #
    # Shape traversal (reading order)
    # ------------------------------------------------------------------ #

    def _iter_shapes(self, shapes: Any) -> Iterator[Any]:
        """Yield leaf shapes in reading order (top-to-bottom, then left-to-right).

        Group shapes are expanded in place so their children are visited at the
        group's position in the reading order.

        Charts are read by :meth:`_extract_charts`. TODO(SmartArt / OLE
            objects): they are yielded like any other shape and reported as a
            warning, but their content is not extracted yet.
        """
        for shape in sorted(shapes, key=self._reading_position):
            if isinstance(shape, GroupShape):
                yield from self._iter_shapes(shape.shapes)
            elif not self._is_furniture(shape):
                yield shape

    @staticmethod
    def _is_furniture(shape: Any) -> bool:
        try:
            return bool(shape.is_placeholder and shape.placeholder_format.type in _FURNITURE_PLACEHOLDERS)
        except Exception as exc:  # odd placeholders must not break the slide
            logger.debug("Could not read placeholder type: %s", exc)
            return False

    @staticmethod
    def _reading_position(shape: Any) -> tuple[int, int]:
        """Sort key ``(row_bucket, left)``; shapes without a position sort first.

        ``top`` is bucketed into coarse rows so boxes that sit side by side but
        differ slightly in Y are ordered left-to-right instead of by the few
        EMUs separating their tops.
        """
        top = getattr(shape, "top", None)
        left = getattr(shape, "left", None)
        return ((top or 0) // _ROW_BUCKET_EMU, left or 0)

    # ------------------------------------------------------------------ #
    # Text, title and notes
    # ------------------------------------------------------------------ #

    @classmethod
    def _extract_title(cls, slide: Slide, shapes: list[Any]) -> tuple[Any | None, str]:
        """Return ``(title_shape, title_text)``; title is empty if the slide has none.

        ``slide.shapes.title`` only sees top-level placeholders, so when it
        finds nothing the already-flattened ``shapes`` (which includes group
        children) are searched for a title placeholder.
        """
        title_shape: Any | None = None
        try:
            title_shape = slide.shapes.title
        except Exception as exc:
            logger.debug("Could not read slide title shape: %s", exc)
        if title_shape is None:
            title_shape = cls._find_grouped_title(shapes)
        if title_shape is None:
            title_shape = cls._infer_title(shapes)
        if title_shape is None or not getattr(title_shape, "has_text_frame", False):
            return None, ""
        title = " ".join(clean_text(title_shape.text_frame.text.replace(_VERTICAL_TAB, " ")).split())
        return title_shape, title

    @classmethod
    def _infer_title(cls, shapes: list[Any]) -> Any | None:
        """Title of a slide that has no title placeholder (designs built from plain text boxes).

        Conservative: the text box with the clearly largest explicit font size, when it is
        a short, non-numeric phrase of at least ``_INFERRED_TITLE_MIN_PT``, and no other
        text box ties with it. Anything ambiguous returns ``None`` (no heading is better
        than a wrong one).
        """
        sized: list[tuple[float, Any, str]] = []
        for shape in shapes:
            try:
                if cls._is_furniture(shape) or not getattr(shape, "has_text_frame", False):
                    continue
                text = " ".join(clean_text(shape.text_frame.text.replace(_VERTICAL_TAB, " ")).split())
                sizes = [
                    run.font.size.pt
                    for paragraph in shape.text_frame.paragraphs
                    for run in paragraph.runs
                    if run.font.size is not None and run.text.strip()
                ]
            except Exception as exc:  # odd shapes must not break the slide
                logger.debug("Skipping shape while inferring a title: %s", exc)
                continue
            if text and sizes:
                sized.append((max(sizes), shape, text))
        if not sized:
            return None
        sized.sort(key=lambda item: -item[0])
        best_size, best_shape, best_text = sized[0]
        others = [item for item in sized[1:] if abs(item[0] - best_size) < 0.5]
        letters = sum(ch.isalpha() for ch in best_text)
        plausible = (
            best_size >= _INFERRED_TITLE_MIN_PT
            and len(best_text) <= 100
            and len(best_text.split()) <= 12
            and letters >= 2
            and not best_text.endswith((".", ",", ";"))
        )
        if not plausible:
            return None
        # a tie with another *title-like* box (not a number or a long sentence) is ambiguous
        if any(
            sum(ch.isalpha() for ch in text) >= 2 and len(text.split()) <= 12
            for _size, _shape, text in others
        ):
            return None
        return best_shape

    @staticmethod
    def _find_grouped_title(shapes: list[Any]) -> Any | None:
        """First title / centered-title placeholder with text among ``shapes``."""
        for shape in shapes:
            try:
                if not shape.is_placeholder:
                    continue
                if shape.placeholder_format.type not in _TITLE_PLACEHOLDERS:
                    continue
                if getattr(shape, "has_text_frame", False) and shape.text_frame.text.strip():
                    return shape
            except Exception as exc:  # odd placeholders must not break the slide
                logger.debug("Skipping shape while looking for a title: %s", exc)
        return None

    @classmethod
    def _text_blocks(cls, shape: Any, slide_number: int) -> list[Block]:
        """Paragraph / list-item blocks for one shape's text frame.

        Lists keep their structure: bullets become ``list_item`` blocks with
        their nesting ``level``; auto-numbered items carry the rendered number
        (``1.``, ``a)``, ``(iv)``) as ``list_marker``.
        """
        if not getattr(shape, "has_text_frame", False):
            return []
        bulleted_by_default = cls._inherits_bullets(shape)
        blocks: list[Block] = []
        counters: dict[int, int] = {}  # paragraph level -> last number used
        for paragraph in shape.text_frame.paragraphs:
            text = clean_text(paragraph.text.replace(_VERTICAL_TAB, " "))  # same as PDF text
            if not text:
                continue
            level = max(int(paragraph.level or 0), 0)
            for deeper in [lvl for lvl in counters if lvl > level]:
                del counters[deeper]  # a shallower item restarts nested numbering

            kind, scheme, start_at = cls._list_style(paragraph, bulleted_by_default)
            if kind == "number":
                number = counters.get(level, start_at - 1) + 1
                counters[level] = number
                marker = format_number(number, scheme)
            elif kind == "bullet":
                counters.pop(level, None)
                marker = "-"
            else:
                counters.clear()  # plain text interrupts any running list
                blocks.append(Block(BlockType.PARAGRAPH, text, slide_number))
                continue
            blocks.append(
                Block(
                    BlockType.LIST_ITEM,
                    text,
                    slide_number,
                    level=level,
                    list_marker=marker,
                )
            )
        return blocks

    @staticmethod
    def _inherits_bullets(shape: Any) -> bool:
        """Body-like placeholders show bullets unless a paragraph opts out."""
        try:
            return bool(
                shape.is_placeholder and shape.placeholder_format.type in _BULLETED_PLACEHOLDERS
            )
        except Exception:
            return False

    @staticmethod
    def _list_style(paragraph: Any, bulleted_by_default: bool) -> tuple[str, str, int]:
        """Classify a paragraph as ``"number"``, ``"bullet"`` or ``"none"``.

        Returns ``(kind, auto_number_scheme, start_at)``. Explicit paragraph
        properties win; otherwise the shape's inherited default applies.
        """
        props = paragraph._p.pPr
        if props is not None:
            if props.find(qn("a:buNone")) is not None:
                return "none", "", 1
            auto = props.find(qn("a:buAutoNum"))
            if auto is not None:
                start = auto.get("startAt", "")
                scheme = auto.get("type", "arabicPeriod")
                return "number", scheme, int(start) if start.isdigit() else 1
            if props.find(qn("a:buChar")) is not None or props.find(qn("a:buBlip")) is not None:
                return "bullet", "", 1
        return ("bullet" if bulleted_by_default else "none"), "", 1

    # ------------------------------------------------------------------ #
    # Charts
    # ------------------------------------------------------------------ #

    def _extract_charts(
        self, shapes: list[Any], slide_number: int, warnings: list[str]
    ) -> tuple[list[str], list[float]]:
        """Describe every chart as readable text.

        Returns ``(texts, scores)``: one text per readable chart (rendered as
        a ``[Chart]`` block later),
        and one quality score per chart / unread graphic object so that lost
        content lowers the slide confidence instead of passing silently.
        """
        blocks: list[str] = []
        scores: list[float] = []
        for shape in shapes:
            name = getattr(shape, "name", "") or "chart"
            if getattr(shape, "has_chart", False):
                lines: list[str] = []
                error: Exception | None = None
                try:
                    lines = self._describe_chart(shape.chart)
                except Exception as exc:
                    error = exc
                if lines:
                    blocks.append("\n".join(lines))
                    scores.append(_SCORE_CHART_OK)
                else:
                    detail = f" ({error})" if error else ""
                    message = f"Slide {slide_number}: chart '{name}' could not be read{detail}"
                    logger.warning(message)
                    warnings.append(message)
                    scores.append(_SCORE_CHART_UNREADABLE)
            elif isinstance(shape, GraphicFrame) and not getattr(shape, "has_table", False):
                # SmartArt, OLE objects, ... : no extractor yet, but never silent.
                message = (
                    f"Slide {slide_number}: graphic object '{name}' "
                    "(SmartArt / embedded object) is not extracted"
                )
                logger.warning(message)
                warnings.append(message)
                scores.append(SCORE_SKIPPED_DEFAULT)
        return blocks, scores

    @classmethod
    def _describe_chart(cls, chart: Any) -> list[str]:
        """Readable lines for one chart; empty when nothing could be extracted.

        Chart type alone does not count as content, so a chart whose labels
        and series are all unreadable is reported as unreadable.
        """
        category_axis = cls._safe(lambda: chart.category_axis)
        value_axis = cls._safe(lambda: chart.value_axis)
        categories = cls._safe(lambda: cls._chart_categories(chart)) or []
        series = cls._safe(lambda: cls._chart_series(chart)) or []

        lines: list[str] = []
        title = cls._safe(lambda: cls._chart_title(chart))
        if title:
            lines.append(f"Title: {title}")

        x_title = (
            cls._safe(lambda: cls._axis_title(category_axis)) if category_axis is not None else ""
        )
        if x_title:
            lines.append(f"X-Axis Title: {x_title}")
        if categories:
            label = "X-Axis" if category_axis is not None else "Categories"
            lines.append(f"{label}: {cls._join_limited(categories)}")

        y_title = (
            cls._safe(lambda: cls._axis_title(value_axis)) if value_axis is not None else ""
        )
        if y_title:
            lines.append(f"Y-Axis: {y_title}")
        if series:
            lines.append(f"Series: {cls._join_limited(series)}")
        data = cls._safe(lambda: cls._chart_data_lines(chart, categories)) or []
        lines.extend(data)

        if cls._safe(lambda: bool(chart.has_legend)):
            # Pie-like charts (no category axis) list their slices in the legend.
            entries = series if category_axis is not None or not categories else categories
            if entries:
                lines.append(f"Legend: {cls._join_limited(entries)}")

        if not lines:
            return []
        chart_type = cls._safe(lambda: cls._chart_type_name(chart))
        if chart_type:
            lines.append(f"Chart Type: {chart_type}")
        return lines

    @staticmethod
    def _chart_data_lines(chart: Any, categories: list[str]) -> list[str]:
        """The plotted numbers: ``Data: Q1: Model A 0.82, Model B 0.91`` per category (bounded)."""
        names: list[str] = []
        columns: list[list[Any]] = []
        for plot in chart.plots:
            for series in plot.series:
                names.append(" ".join(str(series.name or f"series {len(names) + 1}").split()))
                columns.append(list(series.values))
        if not columns:
            return []

        def fmt(value: Any) -> str:
            if value is None:
                return "n/a"
            return f"{value:.4g}" if isinstance(value, float) else str(value)

        limit_series, limit_rows = 6, 15
        lines = []
        if categories and len(categories) == len(columns[0]):
            for i, category in enumerate(categories[:limit_rows]):
                cells = ", ".join(f"{names[j]} {fmt(columns[j][i])}" for j in range(min(len(columns), limit_series)) if i < len(columns[j]))
                lines.append(f"Data: {category}: {cells}")
            if len(categories) > limit_rows:
                lines.append(f"Data: ... {len(categories) - limit_rows} more categories")
        else:
            for j in range(min(len(columns), limit_series)):
                shown = ", ".join(fmt(v) for v in columns[j][:30])
                lines.append(f"Data: {names[j]}: {shown}")
        return lines

    @staticmethod
    def _safe(getter: Any) -> Any:
        """Call ``getter``; python-pptx raises for parts a chart type lacks."""
        try:
            return getter()
        except Exception:
            return None

    @staticmethod
    def _flatten(text: str) -> str:
        return " ".join(clean_text(text.replace(_VERTICAL_TAB, " ")).split())

    @classmethod
    def _chart_title(cls, chart: Any) -> str:
        if not chart.has_title or not chart.chart_title.has_text_frame:
            return ""
        return cls._flatten(chart.chart_title.text_frame.text)

    @classmethod
    def _axis_title(cls, axis: Any) -> str:
        if not axis.has_title or not axis.axis_title.has_text_frame:
            return ""
        return cls._flatten(axis.axis_title.text_frame.text)

    @classmethod
    def _chart_categories(cls, chart: Any) -> list[str]:
        plots = chart.plots
        if len(plots) == 0:
            return []
        return [label for label in (cls._flatten(str(c)) for c in plots[0].categories) if label]

    @classmethod
    def _chart_series(cls, chart: Any) -> list[str]:
        names: list[str] = []
        for plot in chart.plots:
            for series in plot.series:
                name = cls._flatten(series.name or "")
                if name and name not in names:
                    names.append(name)
        return names

    @staticmethod
    def _chart_type_name(chart: Any) -> str:
        chart_type = chart.chart_type
        raw = getattr(chart_type, "name", None) or str(chart_type).split(" ")[0]
        name = raw.replace("_", " ").title()
        return name if name.lower().endswith("chart") else f"{name} Chart"

    @staticmethod
    def _join_limited(items: list[str]) -> str:
        shown = ", ".join(items[:_MAX_CHART_ITEMS])
        extra = len(items) - _MAX_CHART_ITEMS
        return f"{shown}, ... (+{extra} more)" if extra > 0 else shown

    @staticmethod
    def _extract_notes(slide: Slide, slide_number: int, warnings: list[str]) -> str:
        """Return the slide's speaker notes, or an empty string."""
        try:
            if not slide.has_notes_slide:
                return ""
            notes_frame = slide.notes_slide.notes_text_frame
            if notes_frame is None:
                return ""
            return clean_text(notes_frame.text.replace(_VERTICAL_TAB, " "))
        except Exception as exc:
            logger.warning("Slide %d: could not read speaker notes: %s", slide_number, exc)
            warnings.append(f"Slide {slide_number}: speaker notes could not be read ({exc})")
            return ""

    # ------------------------------------------------------------------ #
    # Tables
    # ------------------------------------------------------------------ #

    def _extract_tables(
        self,
        shapes: list[Any],
        slide_number: int,
        warnings: list[str],
        start_index: int = 0,
    ) -> list[TableData]:
        tables: list[TableData] = []
        for shape in shapes:
            if not getattr(shape, "has_table", False):
                continue
            try:
                rows = self._table_to_rows(shape.table)
            except Exception as exc:
                logger.warning("Slide %d: skipping table (%s): %s", slide_number, shape.name, exc)
                warnings.append(f"Slide {slide_number}: table '{shape.name}' skipped ({exc})")
                continue
            if not any(cell.strip() for row in rows for cell in row):
                continue  # empty or purely decorative table: nothing to read or cite
            index = start_index + len(tables)
            tables.append(TableData(page_number=slide_number, index=index, rows=rows))
        return tables

    @staticmethod
    def _table_to_rows(table: Any) -> list[list[str]]:
        """Convert a python-pptx table to a grid of cleaned cell strings.

        Every row and cell is preserved so the grid keeps its shape. Merged
        cells are resolved so the table keeps its meaning:

        * vertical merges: the origin text is repeated on every row it spans,
          so each row stays self-describing (e.g. a merged category column);
        * horizontal merges: the origin text is repeated across the span in
          the header row only, so no column ends up with a meaningless
          ``Column N`` header. In body rows the continuation cells stay empty,
          which avoids emitting the same ``Header: value`` pair twice.
        """
        grid = [list(row.cells) for row in table.rows]
        texts = [[cell_clean(cell.text) for cell in row] for row in grid]

        for r, row in enumerate(grid):
            for c, cell in enumerate(row):
                if not cell.is_merge_origin or not texts[r][c]:
                    continue
                for dr in range(cell.span_height):
                    for dc in range(cell.span_width):
                        if dr == 0 and dc == 0:
                            continue
                        rr, cc = r + dr, c + dc
                        if rr >= len(texts) or cc >= len(texts[rr]):
                            continue  # malformed span; ignore
                        if dc > 0 and rr != 0:
                            continue  # horizontal propagation: header row only
                        if not texts[rr][cc]:
                            texts[rr][cc] = texts[r][c]
        return texts

    # ------------------------------------------------------------------ #
    # Images + OCR
    # ------------------------------------------------------------------ #

    def _extract_and_ocr_images(
        self,
        shapes: list[Any],
        slide_number: int,
        warnings: list[str],
        ocr_cache: _OcrCache,
        start_index: int = 0,
    ) -> list[ImageData]:
        """Extract every picture on the slide and run OCR on it.

        Identical pictures (same content hash) are OCR'd once per file; later
        occurrences reuse the cached result, so a logo repeated on every slide
        costs a single OCR run while still appearing on each slide.

        TODO(picture fills / backgrounds): images used as shape fills or slide
            backgrounds are not detected; extend the filter below to cover them.
        """
        images: list[ImageData] = []
        for shape in shapes:
            if not isinstance(shape, Picture):
                continue
            index = start_index + len(images)
            try:
                picture = shape.image
                blob = picture.blob
                sha1 = picture.sha1
                try:
                    ext = str(picture.ext or "").lower()
                except Exception:  # python-pptx raises for formats it can't name
                    ext = ""
            except Exception as exc:  # e.g. linked (external) picture
                message = f"Slide {slide_number} image {index + 1} ({shape.name}): could not read image data ({exc})"
                logger.warning(message)
                warnings.append(message)
                images.append(
                    ImageData(
                        page_number=slide_number,
                        index=index,
                        xref=0,
                        width=0,
                        height=0,
                        ocr_skipped_reason=SKIP_READ_FAILED,
                    )
                )
                continue

            raw = _RawImage(
                slide_number=slide_number,
                index=index,
                blob=blob,
                name=shape.name,
                sha1=sha1,
                ext=ext,
            )
            image_data, warning = self._process_cached(raw, ocr_cache)
            # a copy: the cached object belongs to the first slide that used the picture
            image_data = replace(
                image_data,
                bbox=self._shape_bbox(shape),
                thumb_hash=sha1[:16] if sha1 else "",
                alt_text=self._alt_text(shape),
            )
            images.append(image_data)
            if warning:
                warnings.append(warning)
        return images

    @staticmethod
    def _shape_bbox(shape: Any) -> tuple[float, float, float, float] | None:
        """Position on the slide in points (1 pt = 12700 EMU)."""
        try:
            left, top, width, height = shape.left, shape.top, shape.width, shape.height
            if None in (left, top, width, height):
                return None
            return (left / 12700, top / 12700, (left + width) / 12700, (top + height) / 12700)
        except Exception:
            return None

    @staticmethod
    def _alt_text(shape: Any) -> str:
        """The author's description of a picture (``descr``), unless it is just the file name."""
        try:
            descr = str(shape._element.xpath("./p:nvPicPr/p:cNvPr/@descr")[0]).strip()
        except Exception:
            return ""
        if not descr or re.search(r"\.(png|jpe?g|gif|emf|wmf|bmp|tiff?)$", descr, re.IGNORECASE):
            return ""
        return " ".join(descr.split())

    def _process_cached(self, raw: _RawImage, ocr_cache: _OcrCache) -> tuple[ImageData, str | None]:
        """Run :meth:`_process_raw_image`, reusing the result for identical pictures.

        The cached entry is the first occurrence's :class:`ImageData` plus the
        warning detail; a hit re-labels it with this slide / index and builds
        the warning from the current location.
        """
        label = f"Slide {raw.slide_number} image {raw.index + 1} ({raw.name})"
        cached = ocr_cache.get(raw.sha1) if raw.sha1 else None
        if cached is None:
            image_data, detail = self._process_raw_image(raw, label)
            if raw.sha1:
                ocr_cache[raw.sha1] = (image_data, detail)
        else:
            first, detail = cached
            image_data = replace(first, page_number=raw.slide_number, index=raw.index)
            logger.debug("%s: reusing cached OCR result (sha1=%s)", label, raw.sha1[:10])
        return image_data, (f"{label}: {detail}" if detail else None)

    def _process_raw_image(self, raw: _RawImage, label: str) -> tuple[ImageData, str | None]:
        """Decode one image, run OCR, and build its :class:`ImageData`.

        Never raises: failures are reported via the returned warning detail.
        Decode / OCR / outcome handling is shared with the DOCX reader
        (:func:`ai.ingestion.image_ocr.ocr_image_blob`); EMF/WMF files that
        fail to decode are reported as ``unsupported_format``.
        """
        image_data = ImageData(
            page_number=raw.slide_number,
            index=raw.index,
            xref=0,  # PDF-specific concept; not applicable to PPTX
            width=0,
            height=0,
        )
        detail = ocr_image_blob(
            self._ocr,
            raw.blob,
            image_data,
            label,
            is_unsupported=lambda: self._is_vector_format(raw),
        )
        return image_data, detail

    @staticmethod
    def _is_vector_format(raw: _RawImage) -> bool:
        """True for EMF / WMF pictures (by extension, then by header signature)."""
        if raw.ext in _VECTOR_EXTENSIONS:
            return True
        header = raw.blob[:48]
        return header[:4] == _WMF_PLACEABLE_MAGIC or header[40:44] == _EMF_SIGNATURE

    # ------------------------------------------------------------------ #
    # Page assembly
    # ------------------------------------------------------------------ #

    def _build_page(
        self,
        slide_number: int,
        blocks: list[Block],
        tables: list[TableData],
        images: list[ImageData],
        chart_scores: list[float],
        warnings: list[str],
    ) -> PageContent:
        # ``text`` is the slide's own content; ``final_text`` adds image OCR,
        # tables and speaker notes, all inline in reading order.
        text = render_blocks(blocks, TEXT_BLOCK_TYPES)
        final_text = render_blocks(blocks)

        return PageContent(
            page_number=slide_number,
            text=text,
            ocr_text=join_ocr_text(images),
            tables=tables,
            images=images,
            page_type=classify_page(text, tables, images),
            text_length=len(text),
            image_count=len(images),
            has_text=bool(text),
            needs_ocr=False,
            ocr_applied=any(img.ocr_applied for img in images),
            ocr_confidence=mean_ocr_confidence(images),
            confidence=compute_confidence(images, chart_scores),
            final_text=final_text,
            warnings=list(warnings),
            blocks=blocks,
        )

    # ------------------------------------------------------------------ #
    # Metadata / statistics
    # ------------------------------------------------------------------ #

    def _build_metadata(
        self,
        presentation: PptxPresentation,
        file_path: Path,
        slides: list[_SlideData],
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "file_name": file_path.name,
            "file_type": "pptx",
            "file_size_bytes": file_path.stat().st_size,
            "page_model": "one_page_per_slide",
            "slides": self._build_slide_metadata(slides),
            "images": self._build_image_metadata([item.page for item in slides]),
        }
        try:
            props = presentation.core_properties
            for key in ("title", "author", "subject", "keywords", "language"):
                value = getattr(props, key, None)
                if value:
                    metadata[key] = str(value)
            for key in ("created", "modified"):
                value = getattr(props, key, None)
                if value:
                    metadata[key] = value.isoformat()
        except Exception as exc:  # metadata is best-effort
            logger.debug("Could not read PPTX core properties: %s", exc)
        return metadata

    @staticmethod
    def _build_slide_metadata(slides: list[_SlideData]) -> list[dict[str, Any]]:
        """Slide number / title entries used for citations and slide references."""
        return [
            {
                "slide_number": item.page.page_number,
                "title": item.title,
                "has_notes": item.has_notes,
                "hidden": item.hidden,  # kept in the document, flagged for filtering
            }
            for item in slides
        ]

    @staticmethod
    def _build_image_metadata(pages: list[PageContent]) -> list[dict[str, Any]]:
        """Per-image diagnostics for analytics and debugging."""
        return [
            {
                "slide_number": page.page_number,
                "image_index": img.index,
                "width": img.width,
                "height": img.height,
                "ocr_applied": img.ocr_applied,
                "ocr_confidence": (
                    round(img.ocr_confidence, 1) if img.ocr_confidence is not None else None
                ),
                "ocr_skipped_reason": img.ocr_skipped_reason,
            }
            for page in pages
            for img in page.images
        ]

    @staticmethod
    def _build_statistics(slides: list[_SlideData]) -> dict[str, Any]:
        pages = [item.page for item in slides]
        return {
            "slide_count": len(pages),
            "hidden_slide_count": sum(1 for item in slides if item.hidden),
            "table_count": sum(len(page.tables) for page in pages),
            "image_count": sum(len(page.images) for page in pages),
            "image_ocr_count": sum(len(page.images_with_text) for page in pages),
            "total_characters": sum(len(page.final_text) for page in pages),
        }


# --------------------------------------------------------------------------- #
# Convenience function
# --------------------------------------------------------------------------- #


def read_pptx(path: str | Path, ocr_processor: OCRProcessor | None = None) -> Document:
    """Read a PPTX file into a :class:`Document` using a one-off :class:`PptxReader`."""
    return PptxReader(ocr_processor=ocr_processor).read(path)
