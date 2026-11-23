"""Plug-in point for figure understanding (Phase 1). No vision model is bundled or required.

A ``FigureDescriber`` turns a cropped figure image plus the author's own words (caption, text in the figure, citing
sentences) into a short description. ``enrich_figures`` runs one over a finished ``Document`` and stores the result on
``FigureData.description``; the chunker already renders a described figure with a labelled "Generated description"
line, and chunk ids depend only on chunk text, so re-chunking after enrichment renames only the figure chunks.

Safety rules enforced here, whatever the model:
    * source text and generated text stay separate (``description`` never overwrites caption / OCR / inner text);
    * a description whose numbers are not found in the author's own text is rejected (``conflict``) - numbers in an
      answer must come from the document, not from a model's reading of a plot;
    * empty or boilerplate descriptions are rejected;
    * results are cached by ``image sha256 + model + prompt version``: re-ingesting an unchanged file costs nothing and a
      model upgrade invalidates exactly the entries it should.

The adoption gate (see docs/phase0_report.md section 5): a real describer must beat the Phase 0 baseline on the figure
benchmark before it is switched on by default.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from ai.ingestion.models import Block, Document, FigureData

logger = logging.getLogger(__name__)

_NUMBER = re.compile(r"(?<![A-Za-z])-?\d[\d,]*(?:\.\d+)?")
_BOILERPLATE = re.compile(r"^(this|the)\s+(image|figure|picture|chart|diagram)\s+(shows|is|depicts|displays)\s+an?\s+\w+\.?$", re.I)
MIN_DESCRIPTION_CHARS = 25


@dataclass(frozen=True, slots=True)
class FigureCrop:
    png: bytes
    width: int
    height: int

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.png).hexdigest()


@dataclass(frozen=True, slots=True)
class FigureContext:
    """What the author wrote about the figure, offered to the model as context (never as instructions)."""

    file_name: str
    page_number: int
    heading_path: tuple[str, ...]
    label: str
    caption: str
    inner_text: str
    ocr_text: str
    mentions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FigureDescription:
    text: str
    figure_type: str = "unknown"
    visible_numbers: tuple[str, ...] = ()
    legibility: str = "good"  # good | partial | poor
    model: str = ""
    prompt_version: str = ""


class FigureDescriber(Protocol):
    model_name: str
    prompt_version: str

    def describe(self, crop: FigureCrop, context: FigureContext) -> FigureDescription: ...


class FigureCropper(Protocol):
    def crop(self, source_path: str | Path, figure: FigureData) -> FigureCrop | None: ...


class PdfFigureCropper:
    """Render the figure's box from a PDF page; ``None`` when the figure has no box or the page cannot be read."""

    def __init__(self, dpi: int = 150, padding: float = 4.0) -> None:
        self._dpi = dpi
        self._padding = padding

    def crop(self, source_path: str | Path, figure: FigureData) -> FigureCrop | None:
        if figure.bbox is None or figure.kind == "caption_only":
            return None
        import pymupdf

        try:
            with pymupdf.open(str(source_path)) as document:
                page = document[figure.page_number - 1]
                x0, y0, x1, y1 = figure.bbox
                pad = self._padding
                clip = pymupdf.Rect(x0 - pad, y0 - pad, x1 + pad, y1 + pad) & page.rect
                pixmap = page.get_pixmap(clip=clip, dpi=self._dpi)
                return FigureCrop(pixmap.tobytes("png"), pixmap.width, pixmap.height)
        except Exception as exc:  # unreadable file / page: the figure simply stays undescribed
            logger.warning("Could not crop figure on page %d: %s", figure.page_number, exc)
            return None


class NullFigureDescriber:
    """Describes nothing: the default, so enrichment is opt-in and Phase 0 behaviour is unchanged."""

    model_name = "none"
    prompt_version = "none"

    def describe(self, crop: FigureCrop, context: FigureContext) -> FigureDescription:
        return FigureDescription(text="")


class StubFigureDescriber:
    """Deterministic test double: echoes the caption as a description (or a fixed text)."""

    model_name = "stub"
    prompt_version = "stub-1"

    def __init__(self, text: str | None = None) -> None:
        self._text = text

    def describe(self, crop: FigureCrop, context: FigureContext) -> FigureDescription:
        text = self._text if self._text is not None else f"The figure illustrates: {context.caption or context.label}."
        return FigureDescription(text=text, model=self.model_name, prompt_version=self.prompt_version)


class DescriptionCache:
    """``image sha256 + model + prompt version`` -> description; optionally persisted as JSON."""

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path else None
        self._data: dict[str, dict[str, object]] = {}
        if self._path is not None and self._path.exists():
            try:
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                logger.warning("Ignoring unreadable description cache %s", self._path)

    @staticmethod
    def key(sha256: str, model: str, prompt_version: str) -> str:
        return f"{sha256}|{model}|{prompt_version}"

    def get(self, key: str) -> FigureDescription | None:
        raw = self._data.get(key)
        if raw is None:
            return None
        return FigureDescription(
            text=str(raw["text"]),
            figure_type=str(raw.get("figure_type", "unknown")),
            visible_numbers=tuple(str(n) for n in raw.get("visible_numbers", ())),  # type: ignore[attr-defined]
            legibility=str(raw.get("legibility", "good")),
            model=str(raw.get("model", "")),
            prompt_version=str(raw.get("prompt_version", "")),
        )

    def put(self, key: str, description: FigureDescription) -> None:
        self._data[key] = {
            "text": description.text,
            "figure_type": description.figure_type,
            "visible_numbers": list(description.visible_numbers),
            "legibility": description.legibility,
            "model": description.model,
            "prompt_version": description.prompt_version,
        }
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._data, ensure_ascii=False), encoding="utf-8")

    def __len__(self) -> int:
        return len(self._data)


@dataclass(slots=True)
class EnrichmentReport:
    described: int = 0
    from_cache: int = 0
    skipped: int = 0  # no crop available (caption-only figure, unsupported format) or nothing to say
    failed: int = 0  # the describer raised
    rejected: list[tuple[str, str]] = field(default_factory=list)  # (figure label or location, reason)


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "").rstrip(".") for n in _NUMBER.findall(text)}


def source_text(figure: FigureData) -> str:
    return " ".join([figure.caption, figure.inner_text, figure.ocr_text, figure.alt_text, *figure.mentions])


def validate_description(description: FigureDescription, figure: FigureData) -> str | None:
    """``None`` when acceptable, else the reason it is rejected."""
    text = description.text.strip()
    if len(text) < MIN_DESCRIPTION_CHARS or _BOILERPLATE.match(text):
        return "empty or boilerplate"
    allowed = _numbers(source_text(figure))
    invented = sorted(n for n in _numbers(text) | {x.replace(",", "") for x in description.visible_numbers} if n not in allowed and len(n.lstrip("-")) >= 2)
    if invented:
        return f"conflict: numbers not in the author's text ({', '.join(invented[:4])})"
    return None


def figure_context(document: Document, figure: FigureData, heading_path: tuple[str, ...] = ()) -> FigureContext:
    file_name = document.source.file_name if document.source else Path(document.source_path).name
    return FigureContext(
        file_name=file_name,
        page_number=figure.page_number,
        heading_path=heading_path,
        label=figure.label,
        caption=figure.caption,
        inner_text=figure.inner_text,
        ocr_text=figure.ocr_text,
        mentions=tuple(figure.mentions),
    )


def enrich_figures(
    document: Document,
    describer: FigureDescriber,
    cropper: FigureCropper,
    *,
    cache: DescriptionCache | None = None,
    redo: bool = False,
    max_figures: int | None = None,
) -> EnrichmentReport:
    """Describe the document's kept figures in place; returns what happened. Never raises for one bad figure."""
    report = EnrichmentReport()
    done = 0
    blocks = {(b.page_number, b.ref_index): b for b in document.blocks if b.type.value == "figure"}
    for page in document.pages:
        for figure in page.figures:
            if figure.description_status == "done" and not redo:
                continue
            if max_figures is not None and done >= max_figures:
                return report
            crop = cropper.crop(document.source_path, figure)
            where = figure.label or f"page {figure.page_number} figure {figure.index}"
            if crop is None:
                figure.description_status = "skipped"
                report.skipped += 1
                continue
            figure.image_sha256 = crop.sha256
            key = DescriptionCache.key(crop.sha256, describer.model_name, describer.prompt_version)
            description = cache.get(key) if cache is not None else None
            cached = description is not None
            if description is None:
                try:
                    description = describer.describe(crop, figure_context(document, figure, _path_of(blocks, figure)))
                except Exception as exc:
                    logger.warning("Describer failed for %s: %s", where, exc)
                    figure.description_status = "failed"
                    report.failed += 1
                    continue
                if cache is not None and description.text.strip():
                    cache.put(key, description)
            reason = validate_description(description, figure)
            done += 1
            if reason is not None:
                figure.description, figure.description_status = "", ("conflict" if reason.startswith("conflict") else "skipped")
                report.rejected.append((where, reason))
                continue
            figure.description = description.text.strip()
            figure.description_status = "done"
            if description.figure_type != "unknown":
                figure.figure_type = description.figure_type
            report.described += 1
            report.from_cache += cached
    return report


def _path_of(blocks: Mapping[tuple[int, int | None], Block], figure: FigureData) -> tuple[str, ...]:
    block = blocks.get((figure.page_number, figure.index))
    return tuple(block.heading_path) if block is not None else ()


__all__: Sequence[str] = [
    "DescriptionCache",
    "EnrichmentReport",
    "FigureContext",
    "FigureCrop",
    "FigureCropper",
    "FigureDescriber",
    "FigureDescription",
    "NullFigureDescriber",
    "PdfFigureCropper",
    "StubFigureDescriber",
    "enrich_figures",
    "validate_description",
]
