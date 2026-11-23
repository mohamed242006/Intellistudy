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


def make_chunk_id(text_hash: str, occurrence: int = 0) -> str:
    """``c-{hash12}`` (``c-{hash12}.{n}`` for the n-th later chunk with identical text in the same document).

    The id depends only on the chunk's own text, never on its position or on the file hash, so editing a file
    leaves every untouched chunk with the same id (E2E-08) and a re-upload can reuse its stored records.
    Ids are unique within one document; across documents ``vector_id`` adds the ``document_uid``.
    """
    return f"c-{text_hash[:12]}" + (f".{occurrence}" if occurrence else "")


def make_parent_id(text_hash: str, occurrence: int = 0) -> str:
    """``p-{hash12}`` (plus ``.{n}`` for repeated text): the parent counterpart of :func:`make_chunk_id`."""
    return f"p-{text_hash[:12]}" + (f".{occurrence}" if occurrence else "")


def vector_id(document_uid: str, chunk_id: str) -> str:
    """Key used in the vector store (two uploads of equal bytes share a doc_id)."""
    return f"{document_uid}:{chunk_id}"
