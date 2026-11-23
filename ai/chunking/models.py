"""Chunk data model: ``Chunk`` (shared base), ``ChildChunk`` (embedded), ``ParentChunk`` (context).

Hierarchy (docs/chunking_design_spec.md):

* a **ChildChunk** is what gets embedded and retrieved (about 400 tokens);
* a **ParentChunk** is the surrounding section text (a leaf ``heading_path`` or one
  slide) that the RAG layer can fetch for context. Parents are never embedded.

Both carry the same provenance, location and quality fields so citations and
filters work identically on either level.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from ai.chunking.citation import format_ranges
from ai.chunking.ids import content_hash, vector_id

BBoxEntry = tuple[int, tuple[float, float, float, float]]
MetaValue = str | int | float | bool


@dataclass(frozen=True, slots=True)
class ChunkContext:
    """Facts about the upload that are not in the ingested ``Document``."""

    user_id: str
    course_id: str
    document_uid: str  # stable DB identity of the upload slot (survives re-upload)
    embedding_model: str = ""  # recorded on child chunks; checked when indexing


@dataclass(frozen=True, slots=True)
class Chunk:
    """Fields shared by every chunk level."""

    # identity
    chunk_id: str
    ordinal: int
    kind: str  # text | table | chart | notes | image_ocr | mixed | section
    text: str  # own content, no overlap; shown to users and given to the LLM
    token_count: int
    content_hash: str

    # document provenance
    doc_id: str
    document_uid: str
    sha256: str
    file_name: str
    file_type: str
    unit: str
    title: str | None
    author: str | None
    created: str | None
    modified: str | None
    language: str | None
    ingested_at: str

    # ownership (enforced server-side on retrieval)
    user_id: str
    course_id: str

    # location / citation
    page_start: int
    page_end: int
    slide_number: int | None
    heading_path: tuple[str, ...]
    section_titles: tuple[str, ...]
    block_start: int
    block_end: int
    block_orders: tuple[int, ...]
    block_ranges: tuple[tuple[int, int], ...]
    block_types: tuple[str, ...]
    citation_label: str
    bboxes: tuple[BBoxEntry, ...]

    # quality
    confidence: float
    ocr_confidence: float | None  # lowest OCR confidence inside the chunk, None if no OCR
    low_confidence: bool
    source_kind: str  # native | ocr_page | image_ocr | mixed

    # versioning
    chunker_version: str
    schema_version: str
    tokenizer: str

    @property
    def page_number(self) -> int:
        """First page (PDF) or slide (PPTX) the chunk touches; 1 for DOCX."""
        return self.page_start

    @property
    def vector_id(self) -> str:
        return vector_id(self.document_uid, self.chunk_id)

    def base_metadata(self) -> dict[str, MetaValue]:
        """Flat scalar metadata shared by both levels (no lists, no None)."""
        path = list(self.heading_path)
        return {
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "document_uid": self.document_uid,
            "user_id": self.user_id,
            "course_id": self.course_id,
            "file_name": self.file_name,
            "file_type": self.file_type,
            "unit": self.unit,
            "title": self.title or "",
            "author": self.author or "",
            "language": self.language or "",
            "page_number": self.page_number,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "slide_number": -1 if self.slide_number is None else self.slide_number,
            "heading_path": " > ".join(path),
            "heading_path_json": json.dumps(path, ensure_ascii=False),
            "heading_top": path[0] if path else "",
            "kind": self.kind,
            "source_kind": self.source_kind,
            "block_start": self.block_start,
            "block_end": self.block_end,
            "block_ranges": format_ranges(self.block_ranges),
            "block_types": ",".join(self.block_types),
            "citation_label": self.citation_label,
            "confidence": round(self.confidence, 3),
            "ocr_confidence": -1.0 if self.ocr_confidence is None else round(self.ocr_confidence, 3),
            "low_confidence": self.low_confidence,
            "token_count": self.token_count,
            "ordinal": self.ordinal,
            "content_hash": self.content_hash,
            "chunker_version": self.chunker_version,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class ChildChunk(Chunk):
    """The retrievable unit: embedded, stored in the vector database."""

    parent_id: str
    embedding_text: str  # context prefix + overlap + text: what is actually embedded
    overlap_prefix: str  # <= overlap_tokens, may be ""
    embedding_hash: str  # hash of embedding_text: decides whether a vector can be reused
    has_table: bool
    table_index: int | None
    table_part: int | None
    table_parts: int | None
    embedding_model: str
    oversize: bool = False
    figure_id: str | None = None  # figure chunks: stable id of the figure, label ("Figure 3") and kind
    figure_label: str | None = None
    figure_type: str | None = None
    figure_kind: str | None = None

    def _metadata_without_record_hash(self) -> dict[str, MetaValue]:
        meta = self.base_metadata()
        meta.update(
            {
                "parent_chunk_id": self.parent_id,
                "embedding_hash": self.embedding_hash,
                "has_table": self.has_table,
                "table_index": -1 if self.table_index is None else self.table_index,
                "table_part": -1 if self.table_part is None else self.table_part,
                "embedding_model": self.embedding_model,
            }
        )
        if self.figure_id is not None:
            meta.update(
                {
                    "figure_id": self.figure_id,
                    "figure_label": self.figure_label or "",
                    "figure_type": self.figure_type or "unknown",
                    "figure_kind": self.figure_kind or "",
                }
            )
        return meta

    @property
    def record_hash(self) -> str:
        """Hash of everything stored next to the vector (metadata + text).

        ``embedding_hash`` says whether the *vector* is still valid; ``record_hash`` says whether
        the *stored record* is: a chunk can keep its id and vector while its parent, page number
        or citation label change (e.g. when text above it shifts).
        """
        payload = json.dumps(self._metadata_without_record_hash(), sort_keys=True, ensure_ascii=False)
        return content_hash(payload + "\x00" + self.text)

    def chroma_metadata(self) -> dict[str, MetaValue]:
        meta = self._metadata_without_record_hash()
        meta["record_hash"] = self.record_hash
        return meta

    def to_chroma_record(self) -> dict[str, Any]:
        """Everything a vector store needs except the embedding itself."""
        return {
            "id": self.vector_id,
            "document": self.text,
            "embedding_text": self.embedding_text,
            "metadata": self.chroma_metadata(),
        }


@dataclass(frozen=True, slots=True)
class ParentChunk(Chunk):
    """Section-level context for a group of children. Stored relationally, never embedded."""

    child_ids: tuple[str, ...]

    @property
    def store_key(self) -> str:
        """Key in the parent store: ``{document_uid}:{chunk_id}``.

        ``chunk_id`` alone is not unique across users, because ``doc_id`` is a content hash
        and two users may upload the same file; ``document_uid`` makes it unique.
        """
        return self.vector_id

    def to_record(self) -> dict[str, Any]:
        record: dict[str, Any] = dict(self.base_metadata())
        record["text"] = self.text
        record["child_ids"] = list(self.child_ids)
        return record

    def to_dict(self) -> dict[str, Any]:
        """Lossless, JSON-friendly form (tuples become lists)."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ParentChunk":
        """Inverse of :meth:`to_dict` (restores the tuple-typed fields)."""
        values = dict(data)
        for name in ("heading_path", "section_titles", "block_orders", "block_types", "child_ids"):
            values[name] = tuple(values[name])
        values["block_ranges"] = tuple((int(a), int(b)) for a, b in values["block_ranges"])
        values["bboxes"] = tuple((int(p), tuple(box)) for p, box in values["bboxes"])
        return cls(**values)


@dataclass(slots=True)
class ChunkReport:
    chunk_count: int = 0
    parent_count: int = 0
    skipped_pages: list[int] = field(default_factory=list)  # whole-page OCR below threshold
    skipped_slides: list[int] = field(default_factory=list)  # title-only slides
    hidden_slides_excluded: list[int] = field(default_factory=list)
    dropped_blocks: int = 0
    oversize_chunks: int = 0
    merged_chunks: int = 0
    warnings: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)  # invariant violations (validator)


@dataclass(slots=True)
class ChunkSet:
    """Result of chunking one document."""

    parents: list[ParentChunk]
    children: list[ChildChunk]
    report: ChunkReport

    @property
    def chunks(self) -> list[ChildChunk]:
        """The retrievable chunks (alias of ``children``)."""
        return self.children

    def children_of(self, parent: ParentChunk) -> list[ChildChunk]:
        wanted = set(parent.child_ids)
        return [c for c in self.children if c.chunk_id in wanted]

    def parent_of(self, child: ChildChunk) -> ParentChunk | None:
        return next((p for p in self.parents if p.chunk_id == child.parent_id), None)
