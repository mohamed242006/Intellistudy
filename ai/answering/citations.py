"""Citation handling: parse the model's ``[S#]`` tags, validate them, and render reader-facing ``[n]`` citations.

A tag is valid only if it names a source that was actually offered. Invalid tags are removed and reported - the
model cannot cite what it was not given. Numbers shown to the reader follow first appearance in the final text.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from ai.answering.models import Citation, ContextBundle, Sentence, SourceRef

_TAG_GROUP = re.compile(r"\[\s*(S\d+(?:\s*[,;]\s*S\d+)*)\s*\]")
_TAG_AFTER_STOP = re.compile(r"([.!?])\s*((?:\[\s*S\d+(?:\s*[,;]\s*S\d+)*\s*\]\s*)+)")
_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[\"'(\[A-Z0-9؀-ۿ])|\n+")


@dataclass(frozen=True, slots=True)
class Parsed:
    sentences: tuple[Sentence, ...]
    invalid_tags: tuple[str, ...]  # tags the model used that name no offered source


def parse(text: str, bundle: ContextBundle) -> Parsed:
    """Split ``text`` into sentences with their valid source tags; collect invalid tags."""
    moved = _TAG_AFTER_STOP.sub(lambda m: f" {m.group(2).strip()}{m.group(1)} ", text)  # "x. [S1]" -> "x [S1]."
    sentences: list[Sentence] = []
    invalid: list[str] = []
    for raw in _SPLIT.split(moved):
        if not raw or not raw.strip():
            continue
        tags: list[str] = []
        for group in _TAG_GROUP.findall(raw):
            for tag in re.findall(r"S\d+", group):
                if bundle.by_tag(tag) is None:
                    invalid.append(tag)
                elif tag not in tags:
                    tags.append(tag)
        clean = _TAG_GROUP.sub("", raw)
        clean = re.sub(r"\s+([.,;:!?])", r"\1", re.sub(r"\s+", " ", clean)).strip()
        if re.search(r"\w", clean):  # dot leaders, stray bullets and the like are not sentences
            sentences.append(Sentence(clean, tuple(tags)))
    return Parsed(tuple(sentences), tuple(dict.fromkeys(invalid)))


def render(sentences: Sequence[Sentence], bundle: ContextBundle) -> tuple[str, list[Citation]]:
    """Reader-facing text with ``[1]``-style citations and the list of citations in order of first use."""
    numbers: dict[str, int] = {}
    citations: list[Citation] = []
    out: list[str] = []
    for sentence in sentences:
        marks: list[str] = []
        for tag in sentence.tags:
            source = bundle.by_tag(tag)
            if source is None:
                continue
            if tag not in numbers:
                numbers[tag] = len(numbers) + 1
                citations.append(Citation(numbers[tag], source))
            marks.append(str(numbers[tag]))
        text = sentence.text
        if marks:
            tail = ""
            if text and text[-1] in ".!?":
                text, tail = text[:-1], text[-1]
            text = f"{text} [{', '.join(marks)}]{tail}"
        out.append(text)
    return " ".join(out), citations


def reference_line(source: SourceRef) -> str:
    """One-line reference for a citation list, e.g. ``lecture.pdf - p. 7 > Caching > Figure 2``."""
    return f"{source.file_name} - {source.citation_label}"
