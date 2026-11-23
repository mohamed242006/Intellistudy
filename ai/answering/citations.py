"""Citation handling: parse the model's ``[S#]`` tags, validate them, and render reader-facing ``[n]`` citations.

A tag is valid only if it names a source that was actually offered. Invalid tags are removed and reported - the
model cannot cite what it was not given. Numbers shown to the reader follow first appearance in the final text.

Lists are read as structure, not as unrelated lines (models cite a list once, on its introduction or per item):
    * an untagged list item takes the tags of its own tagged sentences, else of its parent (the enclosing item, or the
      ``...:`` line that introduces the list);
    * an untagged ``...:`` introduction takes the tags of the items it introduces;
    * an inline enumeration ("approaches: 1. A, 2. B") is one sentence, not one per number.
Inherited tags are marked (``Sentence.inherited``) and still go through the grounding check against the source they
name, so inheritance never lets an unsupported sentence through. The answer keeps the reply's lines and paragraphs.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from ai.answering.models import Citation, ContextBundle, Sentence, SourceRef

_TAG_GROUP = re.compile(r"\[\s*(S\d+(?:\s*[,;]\s*S\d+)*)\s*\]")
# "x. [S1]" -> "x [S1]."; spaces after the tags are consumed, a line break is not (it separates list items)
_TAG_AFTER_STOP = re.compile(r"([.!?])\s*((?:\[\s*S\d+(?:\s*[,;]\s*S\d+)*\s*\][ \t]*)+)")
_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[\"'(\[A-Z0-9؀-ۿ])")
_LIST_ITEM = re.compile(r"^(?:[-*•+–]|\d{1,3}[.)]|[a-zA-Z][.)]|\(\w{1,3}\))\s+")
_ENUMERATOR_END = re.compile(r"(?:^|[:;,(])\s*\d{1,2}\.$")  # "...weaving: 1." / ", 2." - an inline list continues
_ABBREVIATION_END = re.compile(r"\b(?:e\.g|i\.e|vs|cf|Fig|Eq|No|al)\.$")


@dataclass(frozen=True, slots=True)
class Parsed:
    sentences: tuple[Sentence, ...]
    invalid_tags: tuple[str, ...]  # tags the model used that name no offered source


@dataclass(slots=True)
class _Line:
    number: int
    indent: int
    item: bool
    gap: bool
    sentences: list[Sentence] = field(default_factory=list)

    @property
    def intro(self) -> bool:  # "The steps are:" introduces what follows
        return bool(self.sentences) and self.sentences[-1].text.endswith(":")

    def tags(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(t for s in self.sentences for t in s.tags))


def _pieces(line: str) -> list[str]:
    """Sentences of one line; never split after an inline enumerator or a common abbreviation."""
    out: list[str] = []
    for piece in _SPLIT.split(line):
        if out and (_ENUMERATOR_END.search(out[-1]) or _ABBREVIATION_END.search(out[-1])):
            out[-1] = f"{out[-1]} {piece}"
        else:
            out.append(piece)
    return out


def _sentence(raw: str, bundle: ContextBundle, invalid: list[str]) -> tuple[str, tuple[str, ...]]:
    tags: list[str] = []
    for group in _TAG_GROUP.findall(raw):
        for tag in re.findall(r"S\d+", group):
            if bundle.by_tag(tag) is None:
                invalid.append(tag)
            elif tag not in tags:
                tags.append(tag)
    clean = _TAG_GROUP.sub("", raw)
    clean = re.sub(r"\s+([.,;:!?])", r"\1", re.sub(r"\s+", " ", clean)).strip()
    return clean, tuple(tags)


def _inherit(lines: list[_Line]) -> None:
    """Give untagged list items and untagged list introductions the tags of the structure they belong to."""
    original = [line.tags() for line in lines]  # introductions lend only the tags the model wrote on them
    for i, line in enumerate(lines):
        if not line.item:
            continue
        tags = line.tags()
        if not tags:
            for j in range(i - 1, -1, -1):
                other = lines[j]
                if other.item and other.indent >= line.indent:
                    continue  # a sibling or a deeper item
                if other.item:
                    tags = other.tags()  # the enclosing item (already resolved)
                elif other.intro:
                    tags = original[j]
                break
        if tags:
            line.sentences = [s if s.tags else dataclasses.replace(s, tags=tags, inherited=True) for s in line.sentences]
    for i, line in enumerate(lines):
        if line.item or not line.intro or line.sentences[-1].tags:
            continue
        items: list[str] = []
        for other in lines[i + 1:]:
            if not other.item:
                break
            items.extend(t for t in original[lines.index(other)] if t not in items)
        if items:
            line.sentences[-1] = dataclasses.replace(line.sentences[-1], tags=tuple(items), inherited=True)


def parse(text: str, bundle: ContextBundle) -> Parsed:
    """Split ``text`` into sentences with their valid source tags (list-aware); collect invalid tags."""
    moved = _TAG_AFTER_STOP.sub(lambda m: f" {m.group(2).strip()}{m.group(1)} ", text)  # "x. [S1]" -> "x [S1]."
    invalid: list[str] = []
    lines: list[_Line] = []
    gap = False
    for number, raw_line in enumerate(moved.split("\n")):
        stripped = raw_line.strip()
        if not stripped:
            gap = bool(lines)
            continue
        line = _Line(number, len(raw_line) - len(raw_line.lstrip()), bool(_LIST_ITEM.match(stripped)), gap)
        for raw in _pieces(stripped):
            clean, tags = _sentence(raw, bundle, invalid)
            if re.search(r"\w", clean):  # dot leaders, stray bullets and the like are not sentences
                first = not line.sentences
                line.sentences.append(Sentence(clean, tags, line=number, gap=gap and first, indent=line.indent))
        if line.sentences:
            lines.append(line)
            gap = False
    _inherit(lines)
    sentences = tuple(s for line in lines for s in line.sentences)
    return Parsed(sentences, tuple(dict.fromkeys(invalid)))


def render(sentences: Sequence[Sentence], bundle: ContextBundle) -> tuple[str, list[Citation]]:
    """Reader-facing text with ``[1]``-style citations and the list of citations in order of first use."""
    numbers: dict[str, int] = {}
    citations: list[Citation] = []
    out: list[str] = []
    previous_line: int | None = None
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
            if text and text[-1] in ".!?:":
                text, tail = text[:-1], text[-1]
            text = f"{text} [{', '.join(marks)}]{tail}"
        if out:  # keep the reply's lines (lists) and paragraphs; sentences without layout stay inline
            new_line = sentence.line >= 0 and previous_line is not None and sentence.line != previous_line
            out.append(("\n\n" if sentence.gap else "\n") + " " * sentence.indent if new_line else " ")
        out.append(text)
        previous_line = sentence.line
    return "".join(out), citations


def reference_line(source: SourceRef) -> str:
    """One-line reference for a citation list, e.g. ``lecture.pdf - p. 7 > Caching > Figure 2``."""
    return f"{source.file_name} - {source.citation_label}"
