"""Shared helpers for the chunking tests: synthetic documents, counters, fakes."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence

from ai.chunking.config import ChunkConfig
from ai.chunking.models import ChunkContext
from ai.ingestion.models import Block, BlockType, Document, PageContent, SourceInfo
from ai.ingestion.structure import finalize_document


class WordCounter:
    """1 token = 1 whitespace-separated word: easy to reason about in tests."""

    name = "words"

    def count(self, text: str) -> int:
        return len(text.split())


CTX = ChunkContext(user_id="u1", course_id="c1", document_uid="doc-1", embedding_model="fake-embed")
SMALL = ChunkConfig(
    target_tokens=40, max_tokens=60, min_tokens=10, overlap_tokens=8,
    slide_min_body_tokens=3, table_max_tokens=40, context_max_tokens=12,
    parent_max_tokens=120, prefix_max_tokens=12,
)


def words(n: int, prefix: str = "w") -> str:
    return " ".join(f"{prefix}{i}" for i in range(n)) + "."


def sentences(n: int, per: int = 8, prefix: str = "s") -> str:
    return " ".join(words(per, f"{prefix}{i}_") for i in range(n))


def build(
    blocks: list[Block],
    unit: str = "page",
    file_type: str = "pdf",
    pages: list[PageContent] | None = None,
    metadata: dict | None = None,
    title: str | None = None,
    author: str | None = None,
    language: str | None = None,
) -> Document:
    numbers = sorted({b.page_number for b in blocks}) or [1]
    page_objs = pages or [PageContent(page_number=n) for n in numbers]
    by_page = {p.page_number: p for p in page_objs}
    for b in blocks:
        by_page[b.page_number].blocks.append(b)
    source = SourceInfo(
        doc_id="d0c0000000000001", sha256="0" * 64, file_name="x." + file_type,
        file_type=file_type, file_size_bytes=1, unit=unit, page_count=len(page_objs),
        title=title, author=author, language=language,
        ingested_at="2026-01-01T00:00:00+00:00",
    )
    doc = Document(source_path="x", pages=page_objs, metadata=metadata or {}, source=source)
    return finalize_document(doc, carry_across_pages=(unit != "slide"))


def H(text: str, level: int = 1, page: int = 1) -> Block:
    return Block(BlockType.HEADING, text, page, level=level)


def Pg(text: str, page: int = 1) -> Block:
    return Block(BlockType.PARAGRAPH, text, page)


def LI(text: str, page: int = 1, level: int = 0, marker: str = "-") -> Block:
    return Block(BlockType.LIST_ITEM, text, page, level=level, list_marker=marker)


def OCR(text: str, confidence: float | None, page: int = 1, ref: int = 0) -> Block:
    return Block(BlockType.IMAGE_OCR, text, page, ref_index=ref, confidence=confidence)


def slide_meta(*hidden: int, count: int = 6) -> dict:
    return {
        "slides": [
            {"slide_number": n, "title": f"S{n}", "has_notes": False, "hidden": n in hidden}
            for n in range(1, count + 1)
        ]
    }


class FakeEmbedder:
    """Deterministic bag-of-words embedder that records how often it is called."""

    def __init__(self, model_name: str = "fake-embed", dimension: int = 16) -> None:
        self.model_name = model_name
        self.dimension = dimension
        self.document_calls = 0
        self.texts_embedded: list[str] = []

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.document_calls += 1
        self.texts_embedded.extend(texts)
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * self.dimension
        for word in text.lower().split():
            slot = int(hashlib.md5(word.encode()).hexdigest(), 16) % self.dimension
            vec[slot] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]
