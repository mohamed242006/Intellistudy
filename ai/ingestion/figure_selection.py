"""Image Selection Layer: which figure candidates are worth keeping.

Deterministic, cheap, no model at run time. Every decision comes with reasons so it can be audited and tuned
against the benchmark (``evaluation/figure_benchmark``). Rules mirror docs/multimodal_ingestion_design.md s.5.

keep   charts, graphs, scientific figures, architecture diagrams, process flows, comparison visuals
skip   logos, decorative graphics, watermarks, backgrounds, repeated icons, thin banners, tiny pictures,
       text that merely happens to be an image, later copies of a figure shown again on a slide "build"

Decision order
  1. hard rejections: tiny picture, banner/rule, small picture repeated on several pages (template furniture),
     later copy of a large repeated picture;
  2. a caption ("Figure 3: ...") keeps the figure - the author said it is one;
  3. otherwise a small logistic model over pixel / layout / text statistics gives a probability, raised when the
     figure is cited in the text ("see Figure 3") or has author alt text, and compared with ``keep_threshold``.

The model's coefficients were fitted on the hand-labelled candidates in ``real_annotations.json`` (230 uncaptioned
candidates, 50 figures; 2026-10-19). Tested leave-one-file-out - each file scored by a model that never saw it -
it reached precision ~0.68 / recall ~0.82 at the chosen threshold. That is a baseline for a later triage model,
not a finished classifier: what it cannot tell apart is semantic (clip art vs diagram, a slide title rendered as an
image vs a chart). Refit with ``python -m evaluation.figure_benchmark.detection_eval --dump`` whenever the labels grow.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from ai.ingestion.models import FigureData, ImageData, PageContent

KEEP = "keep"
SKIP = "skip"


@dataclass(frozen=True, slots=True)
class SelectionConfig:
    keep_threshold: float = 0.25  # probability above which an uncaptioned candidate is kept
    min_side_points: float = 40.0  # smaller than ~0.55 inch: an icon, a bullet, a glyph
    min_side_pixels: int = 64
    max_aspect: float = 6.0  # banners and rules
    repeated_pages: int = 3  # the same picture on this many pages is template furniture / a slide build
    large_area: float = 0.12  # a repeated picture covering this much of the page is content, shown again
    header_band: float = 0.08  # fraction of the page height treated as running header / footer
    background_area: float = 0.85  # share of the page above which an uncaptioned picture is a backdrop
    max_per_document: int = 60
    cited_bonus: float = 0.25
    alt_text_bonus: float = 0.10


@dataclass(frozen=True, slots=True)
class Decision:
    keep: bool
    score: float
    reasons: tuple[str, ...]


_NUMBER = re.compile(r"(?<![A-Za-z])-?\d+(?:[.,]\d+)?%?")
_WORD = re.compile(r"[A-Za-z]{2,}")

# Fitted logistic model: p = sigmoid(INTERCEPT + sum(w * (x - mean) / scale)). See the module docstring.
_INTERCEPT = -1.7997
_TERMS = (
    ("sqrt_area", 0.6827, 0.2934, 0.2476),
    ("log_colors", -0.0629, 2.9212, 1.1578),
    ("dominant", 0.4942, 0.5683, 0.2426),
    ("white", 0.3350, 0.4138, 0.3179),
    ("edge", 0.3767, 0.1453, 0.0932),
    ("log_words", 0.6331, 0.7507, 1.2828),
    ("log_numbers", 0.4518, 0.1719, 0.5328),
    ("log_aspect", 0.1793, 0.3291, 0.3518),
)


# --------------------------------------------------------------------------- image statistics
@dataclass(frozen=True, slots=True)
class ImageStats:
    thumb_hash: str
    distinct_colors: int
    dominant_fraction: float
    white_fraction: float
    edge_density: float


def image_stats(image) -> ImageStats:
    """Cheap content statistics of a decoded PIL image (pixels are not kept)."""
    gray8 = list(image.convert("L").resize((8, 8)).getdata())
    mean = sum(gray8) / len(gray8)
    bits = "".join("1" if p >= mean else "0" for p in gray8)
    rgb = list(image.convert("RGB").resize((32, 32)).getdata())
    counts: dict[tuple[int, int, int], int] = {}
    for r, g, b in rgb:
        key = (r // 32, g // 32, b // 32)
        counts[key] = counts.get(key, 0) + 1
    white = sum(1 for r, g, b in rgb if r > 235 and g > 235 and b > 235) / len(rgb)
    px = list(image.convert("L").resize((64, 64)).getdata())
    edges = 0
    for y in range(63):
        for x in range(63):
            here = px[y * 64 + x]
            if abs(here - px[y * 64 + x + 1]) > 48 or abs(here - px[(y + 1) * 64 + x]) > 48:
                edges += 1
    return ImageStats(f"{int(bits, 2):016x}", len(counts), max(counts.values()) / len(rgb), white, edges / (63 * 63))


def fingerprint(image) -> tuple[str, int]:
    """(average hash, distinct colours): enough to recognise the same picture again."""
    stats = image_stats(image)
    return stats.thumb_hash, stats.distinct_colors


def apply_stats(target: ImageData, image) -> None:
    """Write the statistics of ``image`` onto ``target`` (an :class:`ImageData`)."""
    stats = image_stats(image)
    target.thumb_hash = target.thumb_hash or stats.thumb_hash
    target.distinct_colors = stats.distinct_colors
    target.dominant_fraction = stats.dominant_fraction
    target.white_fraction = stats.white_fraction
    target.edge_density = stats.edge_density


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------- features and model
def _image_of(figure: FigureData, page: PageContent) -> ImageData | None:
    index = figure.image_index
    return page.images[index] if index is not None and 0 <= index < len(page.images) else None


def figure_features(figure: FigureData, page: PageContent) -> dict[str, float]:
    """Numeric evidence about a candidate (feeds the model and is written to the decision trace for tuning)."""
    image = _image_of(figure, page)
    page_w, page_h = page.size or (0.0, 0.0)
    box = figure.bbox
    area_fraction, aspect = 0.0, 1.0
    if box is not None and page_w * page_h > 0:
        width, height = box[2] - box[0], box[3] - box[1]
        area_fraction = (width * height) / (page_w * page_h)
        aspect = max(width, height) / max(min(width, height), 1.0)
    text = figure.inner_text or figure.ocr_text or (image.ocr_text if image is not None else "")
    return {
        "area": round(area_fraction, 4),
        "aspect": round(aspect, 2),
        "colors": float(image.distinct_colors) if image is not None else -1.0,
        "dominant": round(image.dominant_fraction, 3) if image is not None else -1.0,
        "white": round(image.white_fraction, 3) if image is not None else -1.0,
        "edge": round(image.edge_density, 3) if image is not None else -1.0,
        "ocr_words": float(len(_WORD.findall(text))),
        "numbers": float(len(_NUMBER.findall(text))),
    }


def model_probability(features: dict[str, float]) -> float:
    """Probability that an uncaptioned candidate is a figure worth understanding."""
    values = {
        "sqrt_area": math.sqrt(max(features["area"], 0.0)),
        "log_colors": math.log1p(max(features["colors"], 0.0)),
        "dominant": features["dominant"] if features["dominant"] >= 0 else 0.5,  # unknown -> neutral
        "white": features["white"] if features["white"] >= 0 else 0.3,
        "edge": features["edge"] if features["edge"] >= 0 else 0.1,
        "log_words": math.log1p(features["ocr_words"]),
        "log_numbers": math.log1p(features["numbers"]),
        "log_aspect": math.log(min(max(features["aspect"], 1.0), 10.0)),
    }
    z = _INTERCEPT + sum(weight * (values[name] - mean) / scale for name, weight, mean, scale in _TERMS)
    return 1.0 / (1.0 + math.exp(-z))


# --------------------------------------------------------------------------- repetition
def _image_keys(image: ImageData) -> list[str]:
    keys = []
    if image.xref:
        keys.append(f"xref:{image.xref}")
    if image.thumb_hash:
        keys.append(f"hash:{image.thumb_hash}")
    return keys


def _occurrences(pages: Sequence[PageContent], config: SelectionConfig) -> dict[str, set[int]]:
    seen: dict[str, set[int]] = defaultdict(set)
    for page in pages:
        for image in page.images:
            for key in _image_keys(image):
                seen[key].add(page.page_number)
    return {key: where for key, where in seen.items() if len(where) >= config.repeated_pages}


# --------------------------------------------------------------------------- scoring
def score_figure(
    figure: FigureData,
    page: PageContent,
    config: SelectionConfig,
    *,
    repeated: dict[str, set[int]],
    first_seen: set[str],
    cited: bool,
) -> Decision:
    """Decide one candidate. ``first_seen`` collects the keys of large repeated pictures already kept."""
    image = _image_of(figure, page)
    features = figure_features(figure, page)
    box = figure.bbox

    # --- 1. hard rejections ------------------------------------------------------------------------
    if image is not None:
        if min(image.width, image.height) < config.min_side_pixels:
            return Decision(False, 0.0, (f"tiny picture ({image.width}x{image.height}px)",))
        keys = [k for k in _image_keys(image) if k in repeated]
        if keys:
            if features["area"] < config.large_area:
                return Decision(False, 0.0, ("small picture on several pages (logo / template element)",))
            if any(k in first_seen for k in keys):
                return Decision(False, 0.0, ("later copy of a figure already kept (slide build / reused picture)",))
    if box is not None and figure.kind != "caption_only":
        width, height = box[2] - box[0], box[3] - box[1]
        if min(width, height) < config.min_side_points:
            return Decision(False, 0.0, (f"tiny on the page ({width:.0f}x{height:.0f}pt)",))
        if features["aspect"] > config.max_aspect and not figure.caption:
            return Decision(False, 0.0, ("thin banner / rule",))

    reasons: list[str] = []
    page_h = (page.size or (0.0, 0.0))[1]
    if figure.caption:
        reasons.append(f"caption '{figure.label or 'unlabelled'}'")
        if figure.kind == "caption_only":
            reasons.append("caption without a detected graphic")
        score = 1.0
        keep = True
    else:
        score = model_probability(features)
        reasons.append(f"model probability {score:.2f}")
        if cited:
            score = min(1.0, score + config.cited_bonus)
            reasons.append("cited in the text")
        if figure.alt_text and len(figure.alt_text) > 8:
            score = min(1.0, score + config.alt_text_bonus)
            reasons.append("author alt text")
        if box is not None and page_h > 0:
            centre = (box[1] + box[3]) / 2 / page_h
            if centre < config.header_band or centre > 1 - config.header_band:
                score *= 0.3
                reasons.append("in the header / footer band")
            if features["area"] > config.background_area:
                score *= 0.3
                reasons.append("page-sized backdrop")
        keep = score >= config.keep_threshold
    if keep and image is not None:
        for key in _image_keys(image):
            if key in repeated:
                first_seen.add(key)
    return Decision(keep, round(score, 3), tuple(reasons))


def count_citations(pages: Sequence[PageContent], figure: FigureData) -> bool:
    """True when ``Figure N`` is mentioned in running text other than the figure's own caption."""
    if not figure.number:
        return False
    pattern = re.compile(
        rf"\b(?:Figure|Fig\.?|Chart|Diagram|Scheme)s?\s*{re.escape(figure.number)}(?![0-9A-Za-z])", re.IGNORECASE
    )
    ambiguous = sum(1 for page in pages for other in page.figures if other.number == figure.number) > 1
    for page in pages:
        if ambiguous and abs(page.page_number - figure.page_number) > 1:
            continue
        for chunk in re.split(r"\n\s*\n", page.text):
            if figure.caption and chunk.strip().startswith(figure.caption[:40]):
                continue
            if pattern.search(chunk):
                return True
    return False


def select_figures(
    pages: Sequence[PageContent], config: SelectionConfig | None = None
) -> list[tuple[FigureData, Decision]]:
    """Decide every candidate of the document; fills score / reasons and returns ``(figure, decision)`` pairs.

    Document-level because repetition is only visible across pages, and because a per-document budget keeps the
    highest-scoring figures when there are more candidates than ``max_per_document``.
    """
    config = config or SelectionConfig()
    repeated = _occurrences(pages, config)
    first_seen: set[str] = set()
    decided: list[tuple[FigureData, Decision]] = []
    for page in pages:
        for figure in page.figures:
            decision = score_figure(
                figure, page, config, repeated=repeated, first_seen=first_seen, cited=count_citations(pages, figure)
            )
            figure.selection_score = decision.score
            figure.selection_reasons = list(decision.reasons)
            decided.append((figure, decision))
    keepers = sorted((d for d in decided if d[1].keep), key=lambda d: -d[1].score)
    over = {id(fig) for fig, _ in keepers[config.max_per_document :]}
    final: list[tuple[FigureData, Decision]] = []
    for figure, decision in decided:
        outcome = decision
        if id(figure) in over:
            outcome = Decision(
                False, decision.score, (*decision.reasons, f"over the per-document budget ({config.max_per_document})")
            )
            figure.selection_reasons = list(outcome.reasons)
        final.append((figure, outcome))
    return final
