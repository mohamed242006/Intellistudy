"""Constants and defaults for the chunking layer (see docs/chunking_design_spec.md)."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

#: Embedding model decided for the project (English only, 384-d, 512-token window).
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIM = 384
MODEL_MAX_TOKENS = 512

#: bge models want this instruction on *queries* (never on documents).
QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "

CHUNKER_VERSION = "1.0.0"
TOMBSTONE_RETENTION_DAYS = 7


def collection_name(
    embedding_model: str = EMBEDDING_MODEL, chunker_version: str = CHUNKER_VERSION
) -> str:
    """Chroma collection name; a new model or chunker major version starts a new collection."""
    last = embedding_model.split("/")[-1].lower()
    slug = re.sub(r"[^a-z0-9._-]+", "-", last).strip("-._") or "model"
    if slug != last or len(slug) > 80:
        # sanitised or truncated: keep distinct model ids distinct ("a b" vs "a-b")
        digest = hashlib.sha1(embedding_model.encode("utf-8")).hexdigest()[:8]
        slug = f"{slug[:80].rstrip('-._')}-{digest}"
    major = re.sub(r"[^0-9a-z]+", "", chunker_version.split(".")[0]) or "0"
    return f"chunks__{slug}__c{major}"


@dataclass(frozen=True, slots=True)
class ChunkConfig:
    """Tunable chunking parameters (token counts use the configured TokenCounter)."""

    target_tokens: int = 400  # soft target per chunk (FR-RAG-01)
    max_tokens: int = 480  # hard cap of embedding_text; < MODEL_MAX_TOKENS minus specials
    min_tokens: int = 80  # smaller chunks are merged where allowed
    overlap_tokens: int = 60  # FR-RAG-01
    slide_min_body_tokens: int = 6  # slides with less body (subtitle noise) produce no chunk
    table_max_tokens: int = 400  # tables above this are split by rows
    context_max_tokens: int = 60  # preceding paragraph copied in front of a table
    prefix_max_tokens: int = 60  # heading-path / slide prefix added to embedding_text
    ocr_min_confidence: float = 0.3  # OCR (image or whole page) below this is not indexed
    low_confidence_page: float = 0.6  # chunks below are flagged
    drop_below_page_confidence: float = 0.3  # OCR pages below are not indexed
    parent_max_tokens: int = 1600  # parents above this are split at child boundaries
    max_bboxes: int = 16

    def __post_init__(self) -> None:
        if not 0 < self.min_tokens <= self.target_tokens <= self.max_tokens:
            raise ValueError("require 0 < min_tokens <= target_tokens <= max_tokens")
        if self.overlap_tokens < 0 or self.overlap_tokens >= self.target_tokens:
            raise ValueError("overlap_tokens must be in [0, target_tokens)")
        if self.parent_max_tokens < self.max_tokens:
            raise ValueError("parent_max_tokens must be >= max_tokens")
        if not 0 <= self.prefix_max_tokens < self.max_tokens:
            raise ValueError("prefix_max_tokens must be in [0, max_tokens)")
