"""Replaceable boundaries: embedding models and vector databases.

The chunker never imports an embedding library or a database client. Anything that
satisfies these protocols can be plugged into :class:`ai.chunking.indexing.IndexingService`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:  # avoid a runtime import cycle with ai.chunking.models
    from ai.chunking.models import ParentChunk

MetaValue = str | int | float | bool
#: A filter value: a scalar means "equals", a list/tuple means "is one of".
FilterValue = MetaValue | Sequence[MetaValue]


_SCALARS = (str, int, float, bool)
RESERVED_FILTERS = frozenset({"user_id", "course_id"})


def validate_filters(filters: "Mapping[str, FilterValue] | None") -> dict[str, FilterValue]:
    """Check metadata filters: scalar or list-of-scalar values only, scope keys not overridable.

    Rejecting operator dicts (``{"$ne": ...}``) stops a caller from smuggling backend query
    operators through a filter value.
    """
    clean: dict[str, FilterValue] = {}
    for key, value in (filters or {}).items():
        if key in RESERVED_FILTERS:
            raise ValueError(f"filter {key!r} is reserved: scope is set by the query arguments")
        if not isinstance(key, str) or not key or key.startswith("$"):
            raise ValueError(f"invalid filter key {key!r}")
        if isinstance(value, (list, tuple, set)):
            if not all(isinstance(v, _SCALARS) for v in value):
                raise ValueError(f"filter {key!r} must be a list of str/int/float/bool")
        elif not isinstance(value, _SCALARS):
            raise ValueError(f"filter {key!r} must be a str/int/float/bool or a list of them")
        clean[key] = value
    return clean


@runtime_checkable
class Embedder(Protocol):
    """An embedding model. Documents and queries may be embedded differently
    (e.g. bge models prepend an instruction to queries only)."""

    model_name: str
    dimension: int

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


@dataclass(frozen=True, slots=True)
class VectorRecord:
    id: str
    embedding: Sequence[float]
    document: str
    metadata: Mapping[str, MetaValue]


@dataclass(frozen=True, slots=True)
class ScoredRecord:
    id: str
    score: float  # higher is more similar
    document: str
    metadata: Mapping[str, MetaValue]


@runtime_checkable
class VectorStore(Protocol):
    """A vector database collection store (ChromaDB adapter, in-memory store, ...)."""

    def upsert(self, collection: str, records: Sequence[VectorRecord]) -> None: ...

    def delete(self, collection: str, ids: Sequence[str]) -> int: ...

    def list_ids(self, collection: str, *, document_uid: str) -> dict[str, str]:
        """``{vector id: embedding_hash}`` of everything stored for one document."""
        ...

    def list_record_hashes(self, collection: str, *, document_uid: str) -> dict[str, str]:
        """``{vector id: record_hash}``: detects stale metadata on vectors that are still valid."""
        ...

    def get_embeddings(self, collection: str, ids: Sequence[str]) -> dict[str, list[float]]: ...

    def query(
        self,
        collection: str,
        vector: Sequence[float],
        *,
        user_id: str,
        course_id: str,
        k: int,
        filters: Mapping[str, FilterValue] | None = None,
    ) -> list[ScoredRecord]:
        """Nearest neighbours restricted to the given user and course (mandatory)."""
        ...


@runtime_checkable
class ParentStore(Protocol):
    """Relational home of :class:`ParentChunk` rows. Parents are context, never vectors."""

    def put_many(self, parents: Sequence["ParentChunk"]) -> None: ...

    def get_many(
        self, keys: Sequence[str], *, user_id: str, course_id: str
    ) -> dict[str, "ParentChunk"]:
        """Parents by store key (``ParentChunk.store_key``), restricted to the given user
        and course (mandatory)."""
        ...

    def list_ids(self, *, document_uid: str) -> set[str]:
        """Store keys of every parent of one document."""
        ...

    def delete(self, keys: Sequence[str]) -> int: ...
