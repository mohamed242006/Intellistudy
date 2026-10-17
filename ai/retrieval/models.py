"""Result types of the retrieval layer: child hits first, parent chunks as expansion context."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field

from ai.chunking.interfaces import ScoredRecord
from ai.chunking.models import ParentChunk


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    """One ranked child chunk, decoded from vector-store metadata (no extra lookup needed)."""

    chunk_id: str
    parent_chunk_id: str
    score: float  # cosine similarity, higher is better
    text: str  # child text (never the embedding text)
    kind: str
    doc_id: str
    document_uid: str
    file_name: str
    heading_path: tuple[str, ...]
    citation_label: str
    page_number: int
    slide_number: int | None
    block_types: tuple[str, ...]
    ocr_confidence: float | None
    low_confidence: bool
    user_id: str
    course_id: str
    metadata: Mapping[str, str | int | float | bool] = field(repr=False, default_factory=dict)

    @classmethod
    def from_record(cls, record: ScoredRecord) -> "RetrievedChunk":
        m = record.metadata
        path_json = m.get("heading_path_json")
        path = tuple(json.loads(path_json)) if isinstance(path_json, str) and path_json else ()
        slide = int(m.get("slide_number", -1))
        ocr = float(m.get("ocr_confidence", -1.0))
        types = str(m.get("block_types", ""))
        return cls(
            chunk_id=str(m["chunk_id"]),
            parent_chunk_id=str(m.get("parent_chunk_id", "")),
            score=record.score,
            text=record.document,
            kind=str(m.get("kind", "")),
            doc_id=str(m.get("doc_id", "")),
            document_uid=str(m.get("document_uid", "")),
            file_name=str(m.get("file_name", "")),
            heading_path=path,
            citation_label=str(m.get("citation_label", "")),
            page_number=int(m.get("page_number", 0)),
            slide_number=None if slide < 0 else slide,
            block_types=tuple(t for t in types.split(",") if t),
            ocr_confidence=None if ocr < 0 else ocr,
            low_confidence=bool(m.get("low_confidence", False)),
            user_id=str(m.get("user_id", "")),
            course_id=str(m.get("course_id", "")),
            metadata=dict(m),
        )


@dataclass(frozen=True, slots=True)
class ParentContext:
    """A parent chunk that expands one or more hits."""

    parent: ParentChunk
    hit_chunk_ids: tuple[str, ...]  # the retrieved children it covers, best first
    best_score: float


@dataclass(slots=True)
class RetrievalResult:
    query: str
    hits: list[RetrievedChunk] = field(default_factory=list)  # children, best first
    parents: list[ParentContext] = field(default_factory=list)  # context, ordered by best child
    warnings: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.hits

    def parent_for(self, hit: RetrievedChunk) -> ParentContext | None:
        return next(
            (
                p
                for p in self.parents
                if p.parent.chunk_id == hit.parent_chunk_id
                and p.parent.document_uid == hit.document_uid
            ),
            None,
        )
