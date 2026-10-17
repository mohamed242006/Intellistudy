"""In-memory :class:`VectorStore` for tests, local development and as a reference
implementation of the contract a real adapter (ChromaDB, ...) must satisfy."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from ai.chunking.interfaces import FilterValue, ScoredRecord, VectorRecord, validate_filters
from ai.chunking.models import ParentChunk


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b):
        raise ValueError(f"vector dimensions differ: {len(a)} != {len(b)}")
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


class InMemoryVectorStore:
    def __init__(self) -> None:
        self._data: dict[str, dict[str, VectorRecord]] = {}

    def upsert(self, collection: str, records: Sequence[VectorRecord]) -> None:
        bucket = self._data.setdefault(collection, {})
        for record in records:
            bucket[record.id] = record

    def delete(self, collection: str, ids: Sequence[str]) -> int:
        bucket = self._data.get(collection, {})
        return sum(1 for vid in ids if bucket.pop(vid, None) is not None)

    def list_ids(self, collection: str, *, document_uid: str) -> dict[str, str]:
        bucket = self._data.get(collection, {})
        return {
            vid: str(rec.metadata.get("embedding_hash", ""))
            for vid, rec in bucket.items()
            if rec.metadata.get("document_uid") == document_uid
        }

    def list_record_hashes(self, collection: str, *, document_uid: str) -> dict[str, str]:
        bucket = self._data.get(collection, {})
        return {
            vid: str(rec.metadata.get("record_hash", ""))
            for vid, rec in bucket.items()
            if rec.metadata.get("document_uid") == document_uid
        }

    def get_embeddings(self, collection: str, ids: Sequence[str]) -> dict[str, list[float]]:
        bucket = self._data.get(collection, {})
        return {vid: list(bucket[vid].embedding) for vid in ids if vid in bucket}

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
        if not user_id or not course_id:
            raise ValueError("user_id and course_id are mandatory on every query")
        wanted = {"user_id": user_id, "course_id": course_id, **validate_filters(filters)}

        def matches(metadata: Mapping[str, object]) -> bool:
            for key, value in wanted.items():
                allowed = list(value) if isinstance(value, (list, tuple, set)) else [value]
                if metadata.get(key) not in allowed:
                    return False
            return True

        hits = [
            ScoredRecord(rec.id, _cosine(vector, rec.embedding), rec.document, rec.metadata)
            for rec in self._data.get(collection, {}).values()
            if matches(rec.metadata)
        ]
        hits.sort(key=lambda h: (-h.score, h.id))
        return hits[:k]

    def count(self, collection: str) -> int:
        return len(self._data.get(collection, {}))


class InMemoryParentStore:
    """Reference :class:`ParentStore` for tests and local development."""

    def __init__(self) -> None:
        self._parents: dict[str, ParentChunk] = {}

    def put_many(self, parents: Sequence[ParentChunk]) -> None:
        for parent in parents:
            self._parents[parent.store_key] = parent

    def get_many(
        self, keys: Sequence[str], *, user_id: str, course_id: str
    ) -> dict[str, ParentChunk]:
        if not user_id or not course_id:
            raise ValueError("user_id and course_id are mandatory on every lookup")
        return {
            key: p
            for key in keys
            if (p := self._parents.get(key)) is not None
            and p.user_id == user_id
            and p.course_id == course_id
        }

    def list_ids(self, *, document_uid: str) -> set[str]:
        return {pid for pid, p in self._parents.items() if p.document_uid == document_uid}

    def delete(self, keys: Sequence[str]) -> int:
        return sum(1 for key in keys if self._parents.pop(key, None) is not None)

    def count(self) -> int:
        return len(self._parents)
