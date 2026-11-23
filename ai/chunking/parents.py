"""ParentBuilder: groups consecutive children of one section into section-level parents."""

from __future__ import annotations

import dataclasses

from ai.chunking.citation import block_ranges, citation_label
from ai.chunking.config import ChunkConfig
from ai.chunking.ids import content_hash, make_parent_id
from ai.chunking.models import BBoxEntry, ChildChunk, ParentChunk
from ai.chunking.tokens import TokenCounter


class ParentBuilder:
    """A parent is the text of the children that share one leaf ``heading_path``
    (and, for slides, one slide). A very long section is split into consecutive
    parents at child boundaries so that a parent stays small enough to put in a prompt.
    """

    def __init__(self, config: ChunkConfig, counter: TokenCounter) -> None:
        self._config = config
        self._counter = counter

    def build(self, children: list[ChildChunk]) -> tuple[list[ParentChunk], list[ChildChunk]]:
        """Return ``(parents, children_with_parent_id)``."""
        groups = self._group(children)
        parents: list[ParentChunk] = []
        linked: list[ChildChunk] = []
        seen: dict[str, int] = {}
        for ordinal, group in enumerate(groups):
            parent = self._parent(group, ordinal, seen)
            parents.append(parent)
            linked.extend(dataclasses.replace(c, parent_id=parent.chunk_id) for c in group)
        return parents, linked

    # ------------------------------------------------------------------ helpers
    def _group(self, children: list[ChildChunk]) -> list[list[ChildChunk]]:
        cap = self._config.parent_max_tokens
        groups: list[list[ChildChunk]] = []
        current: list[ChildChunk] = []
        used = 0
        key: tuple[tuple[str, ...], int | None] | None = None
        for child in children:
            child_key = (child.heading_path, child.page_start if child.unit == "slide" else None)
            tokens = self._counter.count(child.text)
            if current and (child_key != key or used + tokens > cap):
                groups.append(current)
                current, used = [], 0
            current.append(child)
            used += tokens
            key = child_key
        if current:
            groups.append(current)
        return groups

    def _parent(self, group: list[ChildChunk], ordinal: int, seen: dict[str, int]) -> ParentChunk:
        first = group[0]
        text = "\n\n".join(c.text for c in group)
        text_hash = content_hash(text)
        occurrence = seen.get(text_hash, 0)
        seen[text_hash] = occurrence + 1
        orders = tuple(sorted({o for c in group for o in c.block_orders}))
        types: list[str] = []
        titles: list[str] = []
        for c in group:
            types.extend(t for t in c.block_types if t not in types)
            titles.extend(t for t in c.section_titles if t not in titles)
        bboxes: list[BBoxEntry] = []
        for c in group:
            bboxes.extend(c.bboxes)
        ocr = [c.ocr_confidence for c in group if c.ocr_confidence is not None]
        sources = {c.source_kind for c in group}
        page_start = min(c.page_start for c in group)
        page_end = max(c.page_end for c in group)
        confidence = min(c.confidence for c in group)

        return ParentChunk(
            chunk_id=make_parent_id(text_hash, occurrence),
            ordinal=ordinal,
            kind="section",
            text=text,
            token_count=self._counter.count(text),
            content_hash=text_hash,
            doc_id=first.doc_id,
            document_uid=first.document_uid,
            sha256=first.sha256,
            file_name=first.file_name,
            file_type=first.file_type,
            unit=first.unit,
            title=first.title,
            author=first.author,
            created=first.created,
            modified=first.modified,
            language=first.language,
            ingested_at=first.ingested_at,
            user_id=first.user_id,
            course_id=first.course_id,
            page_start=page_start,
            page_end=page_end,
            slide_number=first.slide_number,
            heading_path=first.heading_path,
            section_titles=tuple(titles),
            block_start=orders[0],
            block_end=orders[-1],
            block_orders=orders,
            block_ranges=block_ranges(orders),
            block_types=tuple(types),
            citation_label=citation_label(first.unit, page_start, page_end, first.heading_path),
            bboxes=tuple(bboxes[: self._config.max_bboxes]),
            confidence=confidence,
            ocr_confidence=min(ocr) if ocr else None,
            low_confidence=any(c.low_confidence for c in group),
            source_kind=sources.pop() if len(sources) == 1 else "mixed",
            chunker_version=first.chunker_version,
            schema_version=first.schema_version,
            tokenizer=first.tokenizer,
            child_ids=tuple(c.chunk_id for c in group),
        )
