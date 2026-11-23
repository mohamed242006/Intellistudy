"""Layer 1 - PyMuPDF primary parser.

Besides raw text / image extraction this layer repairs the layout artefacts
that hurt retrieval most:

* runs of one visual row that PDF stores as several "lines" are joined;
* bullet glyphs (``•``, ``○``, ``▪``, Symbol / Wingdings private-use glyphs,
  the ``\ufffd`` replacement character, Courier ``o``) become ``- item`` and are
  never promoted to headings; wrapped bullet lines are re-joined;
* headings that wrap over several lines become one heading;
* lines repeated across pages in the header / footer band (course title,
  ``Page 3 of 22``, slide numbers) are detected once per document and dropped.
"""

from __future__ import annotations

import io
import logging
import math
import re
import statistics
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf as fitz
from PIL import Image

from ai.ingestion.cleaners import clean_text
from ai.ingestion.models import ImageData, ImageExtractionError, PageContent, PDFParseError

logger = logging.getLogger(__name__)

BBox = tuple[float, float, float, float]

# --------------------------------------------------------------------------- #
# Bullets
# --------------------------------------------------------------------------- #

BULLET_GLYPHS: frozenset[str] = frozenset("•●○◦▪▫■□◆◇◈◉►▶▸▹➢➤➔➜✓✔✗✘‣⁃∙·")
_PRIVATE_USE = range(0xE000, 0xF900)  # Symbol / Wingdings bullets land here
_REPLACEMENT_CHAR = "\ufffd"

# "o Item" / "- Item" written as plain text in one span.
_TEXT_BULLET = re.compile(r"^(?:[o○◦]|[-–—*])\s+(?=\S)")
# Table-of-contents rows: text, a run of dot leaders, then the page number.
_TOC_LEADER = re.compile(r"\.{5,}\s*\d+\s*$")
MAX_HEADING_LEVEL = 3
# A heading that starts a new numbered item must not be glued to the previous one.
_STARTS_NEW_ITEM = re.compile(
    r"^(?:\d+(?:\.\d+)*[.)]?\s|[IVXLC]+\.\s|(?:chapter|section|part|lecture)\s+\w+)", re.I
)


def is_bullet_glyph(char: str) -> bool:
    """True for characters PDFs use as list markers (incl. broken glyph mappings)."""
    return (
        char in BULLET_GLYPHS
        or char == _REPLACEMENT_CHAR
        or (len(char) == 1 and ord(char) in _PRIVATE_USE)
    )


@dataclass(slots=True)
class _Span:
    text: str
    font: str
    x0: float
    x1: float


def split_bullet(spans: list[_Span], text: str) -> tuple[str, float | None] | None:
    """Detect a bullet at the start of a visual row.

    Returns ``(body_text, body_x0)`` when the row is a list item, else ``None``.
    ``body_x0`` is where the item's text starts (``None`` when unknown); it is
    what wrapped continuation lines are aligned against.
    """
    if not spans or not text:
        return None
    first = spans[0].text
    body = text[len(first):].strip() if text.startswith(first) else ""

    # Marker in its own span (different font): "\ufffd" in Arial, "o" in Courier New.
    if body and len(first) == 1 and is_bullet_glyph(first):
        return body, spans[1].x0 if len(spans) > 1 else None
    if body and first == "o" and len(spans) > 1 and spans[1].font != spans[0].font:
        return body, spans[1].x0

    # Marker inside the same span: "• Item", "•Item".
    if len(text) > 1 and is_bullet_glyph(text[0]):
        return text[1:].strip(), None

    match = _TEXT_BULLET.match(text)
    if match:
        return text[match.end():].strip(), None
    return None


# --------------------------------------------------------------------------- #
# Running headers / footers
# --------------------------------------------------------------------------- #

_DIGITS = re.compile(r"\d+")
_SPACES = re.compile(r"\s+")


def running_key(text: str) -> str:
    """Normalised form used to compare header / footer lines across pages.

    Digit runs collapse to ``#`` so ``Page 3 of 22`` and ``Page 4 of 22`` match.
    """
    return _SPACES.sub(" ", _DIGITS.sub("#", text.casefold())).strip()


def _is_running_candidate(key: str) -> bool:
    if not key or len(key) > 120:
        return False
    has_letters = any(ch.isalpha() for ch in key)
    return has_letters or "#" in key  # pure glyph / punctuation rows are not headers


@dataclass(frozen=True, slots=True)
class RunningLines:
    """Header / footer lines detected for one document.

    ``patterns`` holds ``(key, zone, relative_y, pages)``; a line matches when
    its normalised text equals ``key`` *and* it sits at (about) the same
    relative height, so a body sentence that merely repeats a header's words
    elsewhere on the page survives.
    """

    patterns: tuple[tuple[str, str, float, int], ...] = ()
    tolerance: float = 0.02

    def __bool__(self) -> bool:
        return bool(self.patterns)

    def matches(self, text: str, y0: float, page_height: float) -> bool:
        if not self.patterns or page_height <= 0:
            return False
        key = running_key(text)
        relative = y0 / page_height
        return any(
            pattern_key == key and abs(pattern_y - relative) <= self.tolerance
            for pattern_key, _zone, pattern_y, _pages in self.patterns
        )

    def summary(self) -> list[dict[str, object]]:
        """JSON-friendly description, stored in the document metadata."""
        return [
            {"pattern": key, "zone": zone, "pages": pages}
            for key, zone, _y, pages in self.patterns
        ]


def _is_rotated(line: dict) -> bool:
    """True for text not running left-to-right (PyMuPDF line direction ``(cos, sin)``)."""
    direction = line.get("dir", (1.0, 0.0))
    return abs(direction[0]) < 0.7


_INLINE_BULLETS = (chr(0x2022), chr(0x25AA), chr(0x25E6), chr(0x25CF))  # run-in bullet glyphs


@dataclass(frozen=True, slots=True)
class LayoutProfile:
    """Document-wide typography, so heading levels mean the same on every page.

    Per-page ratios would give identically sized slide titles different levels
    whenever the body text of their slides differs in size. The profile fixes
    one body size and ranks the heading font sizes of the whole document:
    the largest recurring heading size is level 1, the next level 2, ...
    """

    body_size: float = 0.0
    heading_sizes: tuple[float, ...] = ()  # distinct heading sizes, largest first

    def level_for(self, size: float, bold_only: bool = False) -> int:
        """Heading level (1..3) for a font size; bold body-size text ranks last."""
        if bold_only or not self.heading_sizes:
            return min(len(self.heading_sizes) + 1, MAX_HEADING_LEVEL)
        nearest = min(
            range(len(self.heading_sizes)),
            key=lambda i: (abs(self.heading_sizes[i] - size), i),
        )
        return min(nearest + 1, MAX_HEADING_LEVEL)


# --------------------------------------------------------------------------- #
# Line records
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class _Line:
    """One visual row of text (after merging same-row runs)."""

    text: str
    size: float
    bold: bool
    x0: float
    y0: float
    x1: float
    y1: float
    block: int
    spans: list[_Span] = field(default_factory=list)
    kind: str = "text"  # text | heading | bullet
    level: int = 0  # heading level (1-3) or bullet nesting depth
    body_x0: float = 0.0  # where a bullet's text starts (continuation alignment)
    rows: int = 1  # source rows merged into a heading


class PDFReader:
    """Opens PDFs and extracts text, images and per-page metadata with PyMuPDF.

    Args:
        min_text_chars: Pages with fewer extractable characters than this are
            flagged as needing OCR.
        heading_size_ratio: A line is a heading if its font size is at least
            this multiple of the page's body font size.
        heading_max_gap: Two heading rows are one wrapped heading when the gap
            between them is at most this multiple of the font size.
        running_zone: Fraction of the page height (top and bottom) searched
            for repeated header / footer lines.
        running_min_pages: Header / footer detection needs at least this many pages.
        running_min_ratio: Share of pages a line must appear on to count as
            running content.
    """

    def __init__(
        self,
        min_text_chars: int = 50,
        heading_size_ratio: float = 1.15,
        heading_max_gap: float = 0.5,
        running_zone: float = 0.18,
        running_min_pages: int = 3,
        running_min_ratio: float = 0.5,
    ) -> None:
        self.min_text_chars = min_text_chars
        self.heading_size_ratio = heading_size_ratio
        self.heading_max_gap = heading_max_gap
        self.running_zone = running_zone
        self.running_min_pages = running_min_pages
        self.running_min_ratio = running_min_ratio

    # ------------------------------------------------------------------ open
    def open(self, path: str | Path) -> fitz.Document:
        """Open a PDF, raising :class:`PDFParseError` on failure."""
        p = Path(path)
        if not p.is_file():
            raise PDFParseError(f"File not found: {p}")
        try:
            doc = fitz.open(p)
        except Exception as exc:  # fitz raises several error types
            raise PDFParseError(f"Cannot open PDF '{p}': {exc}") from exc
        if doc.needs_pass:
            doc.close()
            raise PDFParseError(f"PDF is password protected: {p}")
        logger.info("Opened %s (%d pages)", p.name, doc.page_count)
        return doc

    @staticmethod
    def extract_metadata(doc: fitz.Document) -> dict[str, object]:
        """Return document-level metadata (incl. the bookmark outline, if any)."""
        meta: dict[str, object] = {k: v for k, v in (doc.metadata or {}).items() if v}
        meta["page_count"] = doc.page_count
        outline = PDFReader.extract_outline(doc)
        if outline:
            meta["outline"] = [list(entry) for entry in outline]
        return meta

    @staticmethod
    def extract_outline(doc: fitz.Document) -> list[tuple[int, str, int]]:
        """Bookmarks as ``(level, title, page_number)``; the authoritative hierarchy.

        Entries that point nowhere (page <= 0) are dropped.
        """
        try:
            toc = doc.get_toc(simple=True)
        except Exception as exc:  # malformed outline must not fail ingestion
            logger.debug("Could not read PDF outline: %s", exc)
            return []
        return [
            (int(level), str(title).strip(), int(page))
            for level, title, page in toc
            if int(page) > 0 and str(title).strip()
        ]

    # ----------------------------------------------------- running header/footer
    def detect_running_lines(self, doc: fitz.Document) -> RunningLines:
        """Find lines repeated in the header / footer band of many pages.

        A line is running content when its normalised text appears on at least
        ``running_min_ratio`` of the pages (and on ``running_min_pages`` or
        more) at a stable height. Page counters (``Page 3 of 22``, ``7``) are
        covered by digit normalisation.
        """
        total = doc.page_count
        if total < self.running_min_pages:
            return RunningLines()

        seen: dict[tuple[str, str], list[tuple[int, float]]] = {}
        for page in doc.pages():
            height = page.rect.height
            if height <= 0:
                continue
            try:
                blocks = page.get_text("dict")["blocks"]
            except Exception as exc:  # one unreadable page must not disable detection
                logger.debug("Skipping page %d in header scan: %s", page.number + 1, exc)
                continue
            for block in blocks:
                if block.get("type") != 0:
                    continue
                for line in block["lines"]:
                    text = "".join(span["text"] for span in line["spans"]).strip()
                    key = running_key(text)
                    if not _is_running_candidate(key):
                        continue
                    y0, y1 = line["bbox"][1], line["bbox"][3]
                    if y1 <= self.running_zone * height:
                        zone = "header"
                    elif y0 >= (1 - self.running_zone) * height:
                        zone = "footer"
                    else:
                        continue
                    seen.setdefault((key, zone), []).append((page.number, y0 / height))

        needed = max(self.running_min_pages, math.ceil(self.running_min_ratio * total))
        patterns: list[tuple[str, str, float, int]] = []
        for (key, zone), hits in seen.items():
            centre = statistics.median(y for _, y in hits)
            stable_pages = {p for p, y in hits if abs(y - centre) <= 0.02}
            if len(stable_pages) >= needed:
                patterns.append((key, zone, centre, len(stable_pages)))
        if patterns:
            logger.info("Detected %d running header/footer line(s)", len(patterns))
        return RunningLines(patterns=tuple(sorted(patterns)))

    # ------------------------------------------------------- document typography
    def profile_document(
        self, doc: fitz.Document, running: RunningLines | None = None
    ) -> LayoutProfile:
        """Measure the document's body size and rank its heading sizes.

        A heading size must recur on at least two pages (one-off cover-page
        sizes would otherwise push every real heading down a level); in
        documents of one or two pages every candidate counts.
        """
        per_page: list[list[_Line]] = []
        for page in doc.pages():
            try:
                blocks = [b for b in page.get_text("dict", sort=True)["blocks"] if b.get("type") == 0]
            except Exception as exc:
                logger.debug("Skipping page %d in layout profile: %s", page.number + 1, exc)
                continue
            lines = self._collect_lines(blocks, [], running, page.rect.height)
            per_page.append(self._merge_rows(lines))

        every_line = [line for lines in per_page for line in lines]
        body_size = self._body_size(every_line)
        if body_size <= 0:
            return LayoutProfile()

        pages_with_size: Counter[float] = Counter()
        for lines in per_page:
            sizes_on_page = {
                round(line.size * 2) / 2
                for line in lines
                if self._is_heading_text(line.text)
                and line.size >= body_size * self.heading_size_ratio
                and split_bullet(line.spans, line.text) is None
            }
            pages_with_size.update(sizes_on_page)

        needed = 2 if len(per_page) > 2 else 1
        sizes = sorted((s for s, n in pages_with_size.items() if n >= needed), reverse=True)
        return LayoutProfile(body_size=body_size, heading_sizes=tuple(sizes))

    @staticmethod
    def _is_heading_text(text: str) -> bool:
        if any(glyph in text for glyph in _INLINE_BULLETS):
            return False  # run-in bullet list typeset as one paragraph, not a title
        return 0 < len(text) <= 100 and not text.endswith((".", ",", ";"))

    # --------------------------------------------------------------- analyze
    def analyze_page(
        self,
        page: fitz.Page,
        running: RunningLines | None = None,
        profile: LayoutProfile | None = None,
    ) -> PageContent:
        """Extract text/images for one page and compute detection metadata."""
        number = page.number + 1
        text = self.extract_text(page, running=running, profile=profile)
        images = self.extract_images(page)

        content = PageContent(page_number=number)
        content.text = text
        content.images = images
        content.image_count = len(images)
        content.text_length = len(text)
        content.has_text = content.text_length >= self.min_text_chars
        content.needs_ocr = not content.has_text
        logger.debug(
            "Page %d: %d chars, %d images, needs_ocr=%s",
            number, content.text_length, content.image_count, content.needs_ocr,
        )
        return content

    # ------------------------------------------------------------------ text
    def extract_text(
        self,
        page: fitz.Page,
        exclude_bboxes: Iterable[BBox] = (),
        running: RunningLines | None = None,
        profile: LayoutProfile | None = None,
    ) -> str:
        """Extract cleaned, structure-marked text.

        Output uses ``#`` x level (1-3) for headings and ``- `` (indented two
        spaces per depth) for list items; everything else is plain text.

        Args:
            page: the PyMuPDF page.
            exclude_bboxes: blocks whose centre lies inside any of these
                (e.g. tables) are skipped so table content is not duplicated.
            running: header / footer lines to drop (see :meth:`detect_running_lines`).
            profile: document typography (see :meth:`profile_document`); without
                it each page is judged against its own body size.
        """
        data = page.get_text("dict", sort=True)
        blocks = [b for b in data.get("blocks", []) if b.get("type") == 0]
        lines = self._collect_lines(blocks, list(exclude_bboxes), running, page.rect.height)
        lines = self._merge_rows(lines)
        if not lines:
            return ""

        body_size = profile.body_size if profile and profile.body_size > 0 else self._body_size(lines)
        rows_in_block: dict[int, int] = {}
        for line in lines:
            rows_in_block[line.block] = rows_in_block.get(line.block, 0) + 1

        for line in lines:
            self._classify(line, body_size, rows_in_block[line.block], profile)
        lines = self._merge_headings(lines)
        lines = self._join_bullet_continuations(lines)
        self._assign_bullet_depths(lines)
        return clean_text(self._render(lines), keep_indent=True)

    # -- step 1: raw lines -------------------------------------------------- #
    @staticmethod
    def _collect_lines(
        blocks: list[dict],
        excluded: list[BBox],
        running: RunningLines | None,
        page_height: float,
    ) -> list[_Line]:
        collected: list[_Line] = []
        # Rotated margin text (the arXiv stamp, "Preprint" banners) is not part of the reading
        # flow and its large font made it a heading. It is dropped when horizontal text clearly
        # dominates the page; a fully rotated (landscape) page keeps everything.
        amount = {True: 0, False: 0}
        for block in blocks:
            for line in block["lines"]:
                amount[_is_rotated(line)] += sum(len(s["text"].strip()) for s in line["spans"])
        drop_rotated = amount[True] > 0 and amount[False] >= 3 * amount[True]
        for index, block in enumerate(blocks):
            x0, y0, x1, y1 = block["bbox"]
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            if any(ex[0] <= cx <= ex[2] and ex[1] <= cy <= ex[3] for ex in excluded):
                continue
            for line in block["lines"]:
                visible = [s for s in line["spans"] if s["text"].strip()]
                if not visible or (drop_rotated and _is_rotated(line)):
                    continue
                spans = [
                    _Span(s["text"].strip(), s.get("font", ""), s["bbox"][0], s["bbox"][2])
                    for s in visible
                ]
                text = "".join(s["text"] for s in line["spans"]).strip()
                lx0, ly0, lx1, ly1 = line["bbox"]
                lcx, lcy = (lx0 + lx1) / 2, (ly0 + ly1) / 2
                if any(ex[0] <= lcx <= ex[2] and ex[1] <= lcy <= ex[3] for ex in excluded):
                    continue  # a caption or figure label sharing a text block with prose
                if running and running.matches(text, ly0, page_height):
                    continue
                if _TOC_LEADER.search(text):  # table-of-contents row: navigation, not content
                    continue
                collected.append(
                    _Line(
                        text=text,
                        size=max(s["size"] for s in visible),
                        bold=all(s["flags"] & 16 for s in visible),
                        x0=lx0,
                        y0=ly0,
                        x1=lx1,
                        y1=ly1,
                        block=index,
                        spans=spans,
                    )
                )
        return collected

    # -- step 2: join runs that share a visual row --------------------------- #
    @staticmethod
    def _same_row(prev: _Line, cur: _Line) -> bool:
        overlap = min(prev.y1, cur.y1) - max(prev.y0, cur.y0)
        smallest = min(prev.y1 - prev.y0, cur.y1 - cur.y0)
        if smallest <= 0 or overlap < 0.5 * smallest:
            return False
        if cur.x0 < prev.x1 - 1:  # must continue to the right
            return False
        if prev.block == cur.block:
            return True
        # Different blocks: only a lone marker glyph joins the text beside it.
        marker = len(prev.text) == 1 and (is_bullet_glyph(prev.text) or prev.text == "o")
        return marker and cur.x0 - prev.x1 <= 2 * prev.size

    def _merge_rows(self, lines: list[_Line]) -> list[_Line]:
        merged: list[_Line] = []
        for line in lines:
            if merged and self._same_row(merged[-1], line):
                prev = merged[-1]
                gap = line.x0 - prev.x1
                separator = " " if gap > 0.08 * max(prev.size, line.size) else ""
                prev.text = f"{prev.text}{separator}{line.text}"
                prev.spans.extend(line.spans)
                prev.x1 = max(prev.x1, line.x1)
                prev.y0 = min(prev.y0, line.y0)
                prev.y1 = max(prev.y1, line.y1)
                prev.size = max(prev.size, line.size)
                prev.bold = prev.bold and line.bold
            else:
                merged.append(line)
        return merged

    # -- step 3: classify ------------------------------------------------------ #
    @staticmethod
    def _body_size(lines: list[_Line]) -> float:
        sizes: list[float] = []
        for line in lines:
            sizes.extend([line.size] * len(line.text))
        return statistics.median(sizes) if sizes else 0.0

    def _classify(
        self,
        line: _Line,
        body_size: float,
        rows_in_block: int,
        profile: LayoutProfile | None = None,
    ) -> None:
        bullet = split_bullet(line.spans, line.text)
        if bullet is not None:
            body, body_x0 = bullet
            line.kind = "bullet"
            line.text = body
            line.body_x0 = body_x0 if body_x0 is not None else line.x0 + 0.6 * line.size
            return

        text = line.text
        larger = line.size >= body_size * self.heading_size_ratio
        bold_only = line.bold and len(text) <= 80 and rows_in_block == 1
        if body_size > 0 and self._is_heading_text(text) and rows_in_block <= 3 and (larger or bold_only):
            line.kind = "heading"
            if profile is not None and profile.body_size > 0:
                line.level = profile.level_for(line.size, bold_only=not larger)
            else:
                line.level = self._heading_level(line.size, body_size)

    @staticmethod
    def _heading_level(size: float, body_size: float) -> int:
        """Level 1-3 from the font-size ratio; bold-only headings are level 3.

        A bookmark outline, when present, later overrides these guesses
        (:func:`ai.ingestion.structure.apply_outline_levels`).
        """
        ratio = size / body_size if body_size > 0 else 1.0
        if ratio >= 1.8:
            return 1
        if ratio >= 1.4:
            return 2
        return 3

    # -- step 4: wrapped headings ------------------------------------------------ #
    def _continues_heading(self, prev: _Line, cur: _Line) -> bool:
        """Is ``cur`` the next row of the heading ``prev``?

        Evidence: same level and weight, a tight vertical gap, left- or
        centre-alignment with the heading above, and no new numbering
        (``2. Methods`` after ``1. Intro`` stays separate).
        """
        if prev.kind != "heading" or cur.kind != "heading":
            return False
        if prev.level != cur.level or prev.bold != cur.bold:
            return False
        # Document-level ranking can give a cover title and a smaller subtitle the
        # same level; a wrapped heading, however, keeps its font size.
        if abs(prev.size - cur.size) > 0.1 * max(prev.size, cur.size):
            return False
        if prev.rows >= 4 or len(prev.text) + len(cur.text) > 200:
            return False
        if _STARTS_NEW_ITEM.match(cur.text):
            return False
        size = max(prev.size, cur.size)
        # Tight leading makes consecutive line boxes overlap slightly (negative gap).
        gap = cur.y0 - prev.y1
        if not -0.5 * size <= gap <= self.heading_max_gap * size:
            return False
        left_aligned = abs(prev.x0 - cur.x0) <= max(3.0, 0.1 * size)
        # Centred text: rendering rounds each row's width, so allow a quarter em.
        centred = abs((prev.x0 + prev.x1) / 2 - (cur.x0 + cur.x1) / 2) <= 0.25 * size
        return left_aligned or centred

    def _merge_headings(self, lines: list[_Line]) -> list[_Line]:
        merged: list[_Line] = []
        for line in lines:
            if merged and self._continues_heading(merged[-1], line):
                prev = merged[-1]
                # A trailing hyphen is either a soft wrap or a real compound:
                # keep the newline so clean_text() makes that call.
                joiner = "\n" if prev.text.endswith("-") else " "
                prev.text = f"{prev.text}{joiner}{line.text}"
                prev.y1 = line.y1
                prev.x0 = min(prev.x0, line.x0)
                prev.x1 = max(prev.x1, line.x1)
                prev.rows += 1
            else:
                merged.append(line)
        return merged

    # -- step 5: wrapped bullets -------------------------------------------------- #
    @staticmethod
    def _join_bullet_continuations(lines: list[_Line]) -> list[_Line]:
        """Fold a wrapped follow-on row into the bullet above it.

        A row continues a bullet when it directly follows it (tight vertical
        gap, even across PyMuPDF blocks) and starts where the bullet's text
        starts - not further right, which would be a separate column such as
        a code panel beside the list.
        """
        result: list[_Line] = []
        for line in lines:
            prev = result[-1] if result else None
            if (
                prev is not None
                and prev.kind == "bullet"
                and line.kind == "text"
                and -0.5 * prev.size <= line.y0 - prev.y1 <= 0.8 * prev.size
                and prev.body_x0 - 4 <= line.x0 <= prev.body_x0 + 1.5 * prev.size
            ):
                joiner = "\n" if prev.text.endswith("-") else " "  # let clean_text decide
                prev.text = f"{prev.text}{joiner}{line.text}"
                prev.y1 = line.y1
                prev.x1 = max(prev.x1, line.x1)
            else:
                result.append(line)
        return result

    @staticmethod
    def _assign_bullet_depths(lines: list[_Line]) -> None:
        """Nesting depth of bullets from their left edge (clusters, max depth 3)."""
        edges = sorted({round(line.x0) for line in lines if line.kind == "bullet"})
        clusters: list[float] = []
        for edge in edges:
            if not clusters or edge - clusters[-1] > 6:
                clusters.append(float(edge))
        for line in lines:
            if line.kind == "bullet" and clusters:
                nearest = min(range(len(clusters)), key=lambda i: abs(clusters[i] - line.x0))
                line.level = min(nearest, 3)

    # -- step 6: render ------------------------------------------------------------ #
    @staticmethod
    def _render(lines: list[_Line]) -> str:
        out_blocks: list[str] = []
        current: list[str] = []
        current_block: int | None = None
        for line in lines:
            if line.kind == "heading":
                text = f"{'#' * line.level} {line.text}"
            elif line.kind == "bullet":
                text = f"{'  ' * line.level}- {line.text}"
            else:
                text = line.text
            if current_block is not None and line.block != current_block:
                out_blocks.append("\n".join(current))
                current = []
            current_block = line.block
            current.append(text)
        if current:
            out_blocks.append("\n".join(current))
        return "\n\n".join(out_blocks)

    # ---------------------------------------------------------------- images
    @staticmethod
    def extract_images(page: fitz.Page) -> list[ImageData]:
        """List images embedded on the page (metadata only, no pixel data)."""
        result: list[ImageData] = []
        for idx, img in enumerate(page.get_images(full=True)):
            xref, smask, width, height = img[0], img[1], img[2], img[3]
            bbox: BBox | None = None
            try:
                r = page.get_image_bbox(img)
                bbox = (r.x0, r.y0, r.x1, r.y1)
            except Exception:  # bbox not available for some image types
                logger.debug("No bbox for image xref=%s on page %d", xref, page.number + 1)
            result.append(
                ImageData(page_number=page.number + 1, index=idx, xref=xref,
                          width=width, height=height, bbox=bbox, smask=smask)
            )
        return result

    @staticmethod
    def load_image(doc: fitz.Document, image: ImageData) -> Image.Image:
        """Decode one embedded image into an RGB PIL image (ready for OCR).

        Handles grayscale/CMYK colour spaces and transparency (alpha channel or
        soft mask) by compositing onto a white background.

        Raises:
            ImageExtractionError: if the image cannot be decoded.
        """
        try:
            pix = fitz.Pixmap(doc, image.xref)
            if pix.colorspace is None:  # stencil/mask-only image, nothing to read
                raise ImageExtractionError(f"Image xref={image.xref} has no colour data")
            if pix.colorspace.n != 3:  # gray, CMYK, ...
                pix = fitz.Pixmap(fitz.csRGB, pix)
            img: Image.Image = Image.open(io.BytesIO(pix.tobytes("png")))
            img.load()

            if img.mode == "RGBA":
                alpha = img.getchannel("A")
                base = Image.new("RGB", img.size, "white")
                base.paste(img.convert("RGB"), mask=alpha)
                img = base
            else:
                img = img.convert("RGB")

            if image.smask:  # separate transparency mask
                mask_pix = fitz.Pixmap(doc, image.smask)
                mask = Image.open(io.BytesIO(mask_pix.tobytes("png"))).convert("L")
                if mask.size != img.size:
                    mask = mask.resize(img.size)
                base = Image.new("RGB", img.size, "white")
                base.paste(img, mask=mask)
                img = base
            return img
        except ImageExtractionError:
            raise
        except Exception as exc:
            raise ImageExtractionError(
                f"Cannot decode image xref={image.xref} on page {image.page_number}: {exc}"
            ) from exc
