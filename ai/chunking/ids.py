"""Deterministic identifiers and text normalisation for chunks."""

from __future__ import annotations

import hashlib
import re
import unicodedata

_SPACES = re.compile(r"\s+")


def normalize_for_hash(text: str) -> str:
    """NFC, collapsed whitespace, stripped - the form used for content hashes."""
    return _SPACES.sub(" ", unicodedata.normalize("NFC", text)).strip()


def content_hash(text: str) -> str:
    """16 hex chars of the SHA-1 of the normalised chunk text."""
    # "surrogatepass": text that never went through clean_text must not be able to crash hashing
    return hashlib.sha1(normalize_for_hash(text).encode("utf-8", "surrogatepass")).hexdigest()[:16]


def make_chunk_id(doc_id: str, ordinal: int, text_hash: str) -> str:
    """``{doc_id}-{ordinal:05d}-{hash8}``: sortable, unique per document, content-sensitive."""
    return f"{doc_id}-{ordinal:05d}-{text_hash[:8]}"


def vector_id(document_uid: str, chunk_id: str) -> str:
    """Key used in the vector store (two uploads of equal bytes share a doc_id)."""
    return f"{document_uid}:{chunk_id}"
