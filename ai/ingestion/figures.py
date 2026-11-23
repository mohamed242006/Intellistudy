"""Figure detection (Phase 0: no model, no network).

A *figure* here is a region of a page that carries meaning through graphics - a chart, a diagram, a photo with a
caption - together with the words the author attached to it. This module finds those regions and their captions
and links the sentences that cite them ("as shown in Figure 3"). Whether a figure is worth keeping is decided
separately by ``figure_selection``; whether it is *understood* (a generated description) is a later phase.

PDF specifics
    * raster pictures come from ``ImageData`` (already extracted, with positions);
    * charts and diagrams drawn as vector graphics have no image at all, so drawing operators are clustered
      into regions (``page.get_drawings()``), and the text objects inside a region become ``inner_text``;
    * a caption is a line that *starts* with ``Figure N`` / ``Fig. N`` followed by punctuation (or a bold label),
      which separates it from a sentence that merely begins with "Figure 3 shows ...".
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from ai.ingestion.cleaners import clean_text
from ai.ingestion.models import Block, BlockType, Document, FigureData, ImageData

logger = logging.getLogger(__name__)

BBox = tuple[float, float, float, float]

_CAPTION = re.compile(
    r"^\s*(?P<word>Figure|Fig\.?|FIG\.?|Chart|Diagram|Scheme)\s*(?P<num>\d+(?:\.\d+)?[A-Za-z]?)\b"
    r"(?P<sep>\s*[.:\-–—|)]+)?\s*(?P<rest>.*)$",
    re.IGNORECASE | re.DOTALL,
)
_MENTION = r"\b(?:Figure|Fig\.?|Chart|Diagram|Scheme)s?\s*{num}(?![0-9A-Za-z])"

_TYPE_WORDS = (
    ("chart", ("accuracy", "plot", "graph", "curve", "comparison", "versus", " vs ", "performance", "results", "loss", "histogram", "distribution", "trend", "chart")),
    ("diagram", ("architecture", "diagram", "framework", "pipeline", "overview", "flow", "workflow", "schematic", "block diagram", "model of", "structure")),
    ("screenshot", ("screenshot", "interface", "ui ", "screen")),
    ("photo", ("photo", "picture", "image of", "microscope", "specimen")),
)

MAX_MENTIONS = 2
MAX_MENTION_CHARS = 320


# --------------------------------------------------------------------------- captions
@dataclass(frozen=True, slots=True)
class Caption:
    label: str  # "Figure 3"
    number: str  # "3"
    text: str  # the full caption, label included
    bbox: BBox | None = None


def canonical_label(word: str, number: str) -> str:
    return f"{'Figure' if word.lower().startswith('fig') else word.capitalize()} {number}"


def parse_caption(text: str, *, bold_label: bool = False) -> Caption | None:
    """``Caption`` when ``text`` starts like one, else ``None``.

    "Figure 3: Accuracy per model" and "Fig. 2. The pipeline" are captions; "Figure 3 shows that ..." is a
    sentence, unless the label is typeset in bold (the usual style of papers without punctuation).
    """
    match = _CAPTION.match(text)
    if match is None:
        return None
    rest = (match.group("rest") or "").strip()
    if not rest:
        return None
    if match.group("sep") is None and not bold_label:
        return None
    label = canonical_label(match.group("word"), match.group("num"))
    return Caption(label=label, number=match.group("num"), text=clean_text(text.strip()))


def guess_figure_type(caption: str) -> str:
    lowered = f" {caption.lower()} "
    for kind, words in _TYPE_WORDS:
        if any(word in lowered for word in words):
            return kind
    return "unknown"


# --------------------------------------------------------------------------- geometry
def area(box: BBox) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def intersection(a: BBox, b: BBox) -> float:
    return area((max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])))


def union(boxes: Iterable[BBox]) -> BBox:
    items = list(boxes)
    return (min(b[0] for b in items), min(b[1] for b in items), max(b[2] for b in items), max(b[3] for b in items))


def centre_inside(inner: BBox, outer: BBox) -> bool:
    cx, cy = (inner[0] + inner[2]) / 2, (inner[1] + inner[3]) / 2
    return outer[0] <= cx <= outer[2] and outer[1] <= cy <= outer[3]


def horizontal_overlap(a: BBox, b: BBox) -> float:
    """Shared width as a fraction of the narrower box."""
    shared = min(a[2], b[2]) - max(a[0], b[0])
    narrow = min(a[2] - a[0], b[2] - b[0])
    return shared / narrow if narrow > 0 and shared > 0 else 0.0


# --------------------------------------------------------------------------- PDF detection
@dataclass(slots=True)
class _Line:
    text: str
    bbox: BBox
    size: float
    bold: bool
    block: int


@dataclass(slots=True)
class Region:
    bbox: BBox
    kind: str  # raster | vector_region
    image_index: int | None = None
    paths: int = 0
    inner_text: str = ""
    axis_only: bool = False


def _lines(fitz_page) -> list[_Line]:
    out: list[_Line] = []
    for index, block in enumerate(fitz_page.get_text("dict")["blocks"]):
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            spans = [s for s in line["spans"] if s["text"].strip()]
            if not spans:
                continue
            out.append(
                _Line(
                    text="".join(s["text"] for s in line["spans"]).strip(),
                    bbox=tuple(line["bbox"]),
                    size=max(s["size"] for s in spans),
                    bold=bool(spans[0]["flags"] & 16),
                    block=index,
                )
            )
    return out


def find_captions(fitz_page) -> list[Caption]:
    """Captions on the page, each with the union box of its lines."""
    lines = _lines(fitz_page)
    captions: list[Caption] = []
    used: set[int] = set()
    for position, line in enumerate(lines):
        if position in used:
            continue
        caption = parse_caption(line.text, bold_label=line.bold)
        if caption is None:
            continue
        members = [position]
        last = line
        for later in range(position + 1, len(lines)):
            nxt = lines[later]
            gap = nxt.bbox[1] - last.bbox[3]
            same_flow = nxt.block == last.block or (gap < 0.6 * last.size and abs(nxt.size - line.size) <= 0.6)
            if (
                not same_flow
                or gap > 1.2 * last.size
                or parse_caption(nxt.text, bold_label=nxt.bold) is not None
                or nxt.bbox[0] < line.bbox[0] - 40
            ):
                break
            members.append(later)
            last = nxt
        used.update(members)
        text = clean_text(" ".join(lines[i].text for i in members))
        full = parse_caption(text, bold_label=True)
        captions.append(
            Caption(
                label=caption.label,
                number=caption.number,
                text=full.text if full else text,
                bbox=union(lines[i].bbox for i in members),
            )
        )
    return captions


def _cluster_boxes(items: Sequence[tuple[BBox, int]], grow: float) -> list[tuple[BBox, int]]:
    """Merge boxes that touch once grown by ``grow`` points (grid-bucketed union-find, near-linear)."""
    parent = list(range(len(items)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    cell = max(grow * 2.5, 12.0)
    buckets: dict[tuple[int, int], int] = {}
    for i, (box, _) in enumerate(items):
        for gx in range(int((box[0] - grow) // cell), int((box[2] + grow) // cell) + 1):
            for gy in range(int((box[1] - grow) // cell), int((box[3] + grow) // cell) + 1):
                other = buckets.setdefault((gx, gy), i)
                if other != i:
                    ra, rb = find(i), find(other)
                    if ra != rb:
                        parent[rb] = ra
    groups: dict[int, list[int]] = {}
    for i in range(len(items)):
        groups.setdefault(find(i), []).append(i)
    return [(union(items[i][0] for i in members), sum(items[i][1] for i in members)) for members in groups.values()]


def vector_regions(fitz_page, *, avoid: Sequence[BBox] = (), min_paths: int = 12) -> list[Region]:
    """Clusters of drawing operators that look like a chart or a diagram (not a table frame or a rule)."""
    page = fitz_page.rect
    page_area = float(page.width * page.height)
    try:
        drawings = fitz_page.get_drawings()
    except Exception as exc:  # exotic content streams must not break ingestion
        logger.debug("get_drawings failed on page %d: %s", fitz_page.number + 1, exc)
        return []
    items: list[tuple[BBox, int]] = []
    straight = 0
    total = 0
    for drawing in drawings:
        rect = drawing["rect"]
        box = (float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1))
        if area(box) > 0.85 * page_area and len(drawing["items"]) <= 2:
            continue  # page background / frame
        paths = len(drawing["items"])
        items.append((box, paths))
        total += paths
        straight += sum(1 for it in drawing["items"] if it[0] == "l" and (abs(it[1].x - it[2].x) < 0.5 or abs(it[1].y - it[2].y) < 0.5))
    if not items:
        return []
    regions: list[Region] = []
    for box, paths in _cluster_boxes(items, grow=8.0):
        width, height = box[2] - box[0], box[3] - box[1]
        if paths < min_paths or width < 60 or height < 40:
            continue
        if area(box) > 0.85 * page_area:
            continue
        if any(intersection(box, a) > 0.5 * area(box) for a in avoid):
            continue
        regions.append(Region(bbox=box, kind="vector_region", paths=paths))
    return regions


_LABEL_MARGIN = 22.0  # axis ticks and legends sit just outside the drawn area
_MAX_LABEL_CHARS = 50  # a longer line is prose, not a label


def _label_lines(lines: Sequence[_Line], box: BBox) -> list[_Line]:
    """Lines inside ``box`` plus short labels hugging it (tick labels, legend entries)."""
    grown = (box[0] - _LABEL_MARGIN, box[1] - _LABEL_MARGIN, box[2] + _LABEL_MARGIN, box[3] + _LABEL_MARGIN)
    return [
        ln
        for ln in lines
        if centre_inside(ln.bbox, box) or (centre_inside(ln.bbox, grown) and len(ln.text) <= _MAX_LABEL_CHARS)
    ]


def _inner_text(lines: Sequence[_Line], box: BBox) -> str:
    inside = _label_lines(lines, box)
    inside.sort(key=lambda ln: (round(ln.bbox[1] / 4), ln.bbox[0]))
    return clean_text(" ".join(ln.text for ln in inside))


def detect_pdf_figures(
    fitz_page, images: Sequence[ImageData], *, tables: Sequence[BBox] = (), min_raster_px: int = 48
) -> list[FigureData]:
    """Figure candidates for one PDF page, captions attached. Selection happens later, over the whole document."""
    lines = _lines(fitz_page)
    captions = find_captions(fitz_page)
    caption_boxes = [c.bbox for c in captions if c.bbox]

    regions: list[Region] = []
    for image in images:
        if image.bbox is None or min(image.width, image.height) < min_raster_px:
            continue
        regions.append(Region(bbox=image.bbox, kind="raster", image_index=image.index))
    for region in vector_regions(fitz_page, avoid=list(tables)):
        if any(intersection(region.bbox, r.bbox) > 0.6 * area(region.bbox) for r in regions if r.kind == "raster"):
            continue
        # text objects inside the region are the labels of the figure; reject frames full of prose
        prose = [ln for ln in lines if not any(centre_inside(ln.bbox, c) for c in caption_boxes)]
        region.inner_text = _inner_text(prose, region.bbox)
        if len(region.inner_text) > 1500:
            continue
        labels = _label_lines(prose, region.bbox)
        region.bbox = union([region.bbox, *(ln.bbox for ln in labels)])  # the box the page text must exclude
        regions.append(region)

    # assign each region to the nearest caption above or below it (a caption may own several panels)
    owner: dict[int, int] = {}
    for r_index, region in enumerate(regions):
        best: tuple[float, int] | None = None
        for c_index, caption in enumerate(captions):
            if caption.bbox is None or horizontal_overlap(region.bbox, caption.bbox) < 0.3:
                continue
            below = caption.bbox[1] - region.bbox[3]  # caption under the figure
            above = region.bbox[1] - caption.bbox[3]  # caption over the figure
            gap = below if -6 <= below <= 70 else above if -6 <= above <= 40 else None
            if gap is not None and (best is None or gap < best[0]):
                best = (gap, c_index)
        if best is not None:
            owner[r_index] = best[1]

    figures: list[FigureData] = []
    page_number = fitz_page.number + 1
    claimed: set[int] = set()
    for c_index, caption in enumerate(captions):
        members = [regions[r] for r, c in owner.items() if c == c_index]
        if members:
            claimed.add(c_index)
            box = union(m.bbox for m in members)
            raster = [m for m in members if m.kind == "raster"]
            figures.append(
                FigureData(
                    page_number=page_number,
                    index=len(figures),
                    kind="raster" if raster and len(raster) == len(members) else "vector_region",
                    bbox=box,
                    label=caption.label,
                    number=caption.number,
                    caption=caption.text,
                    caption_bbox=caption.bbox,
                    inner_text=" ".join(m.inner_text for m in members if m.inner_text),
                    image_index=raster[0].image_index if len(raster) == 1 else None,
                    figure_type=guess_figure_type(caption.text),
                )
            )
        else:
            figures.append(  # a caption with no graphic nearby: the words alone are still worth keeping
                FigureData(
                    page_number=page_number,
                    index=len(figures),
                    kind="caption_only",
                    bbox=caption.bbox,
                    label=caption.label,
                    number=caption.number,
                    caption=caption.text,
                    caption_bbox=caption.bbox,
                    figure_type=guess_figure_type(caption.text),
                )
            )
    for r_index, region in enumerate(regions):
        if r_index in owner:
            continue
        figures.append(
            FigureData(
                page_number=page_number,
                index=len(figures),
                kind=region.kind,
                bbox=region.bbox,
                inner_text=region.inner_text,
                image_index=region.image_index,
            )
        )
    return figures


# --------------------------------------------------------------------------- rendering
def figure_text(figure: FigureData) -> str:
    """The author's words for a figure, as stored in its block (nothing generated)."""
    parts: list[str] = []
    if figure.caption:
        parts.append(figure.caption)
    elif figure.alt_text:
        parts.append(f"Alt text: {figure.alt_text}")
    body = figure.inner_text or figure.ocr_text
    if body:
        parts.append(f"Text in figure: {body}")
    return "\n".join(parts)


def figure_block(figure: FigureData) -> Block:
    return Block(
        BlockType.FIGURE,
        figure_text(figure),
        figure.page_number,
        ref_index=figure.index,
        bbox=figure.bbox,
        confidence=figure.ocr_confidence,
    )


# --------------------------------------------------------------------------- citing sentences
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\[])")


def _sentences_with(text: str, pattern: re.Pattern[str]) -> list[str]:
    return [s.strip() for s in _SENTENCE.split(text) if pattern.search(s)]


def link_mentions(document: Document) -> int:
    """Fill ``mentions`` / ``referenced_by`` of every figure from the body text. Returns the links made.

    A label that identifies several figures of the document (every chapter has a "Figure 1") is matched only
    on the same page and its neighbours; a unique label is matched anywhere.
    """
    figures = [f for page in document.pages for f in page.figures if f.number]
    if not figures:
        return 0
    counts: dict[str, int] = {}
    for fig in figures:
        counts[fig.number] = counts.get(fig.number, 0) + 1
    body = [b for b in document.blocks if b.type in (BlockType.PARAGRAPH, BlockType.LIST_ITEM)]
    linked = 0
    for fig in figures:
        pattern = re.compile(_MENTION.format(num=re.escape(fig.number)), re.IGNORECASE)
        unique = counts[fig.number] == 1
        fig.mentions.clear()
        fig.referenced_by.clear()
        for block in body:
            if not unique and abs(block.page_number - fig.page_number) > 1:
                continue
            if fig.caption and block.text.strip() == fig.caption.strip():
                continue
            if not pattern.search(block.text):
                continue
            fig.referenced_by.append(block.order)
            for sentence in _sentences_with(block.text, pattern):
                if len(fig.mentions) < MAX_MENTIONS:
                    fig.mentions.append(" ".join(sentence.split())[:MAX_MENTION_CHARS])
            linked += 1
    return linked


@dataclass(slots=True)
class FigureReport:
    """Counts kept for the document statistics and the benchmark."""

    candidates: int = 0
    kept: int = 0
    skipped: int = 0
    reasons: dict[str, int] = field(default_factory=dict)
