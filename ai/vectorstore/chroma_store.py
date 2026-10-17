"""ChromaVectorStore: ChromaDB behind the :class:`ai.chunking.VectorStore` protocol.

Design (docs/embedding_retrieval_architecture.md, section B):

* one collection per embedding model and chunker major version (``collection_name()``),
  **not** one per user: isolation is a mandatory ``user_id`` + ``course_id`` filter that
  this adapter adds to every query and refuses to omit;
* embeddings are always supplied by the caller (``embedding_function=None``), so Chroma
  never loads or runs a model of its own;
* cosine space, so ``score = 1 - distance``;
* every call is batched below Chroma's maximum batch size.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import chromadb

from ai.chunking.interfaces import FilterValue, ScoredRecord, VectorRecord, validate_filters

logger = logging.getLogger(__name__)

_PAGE = 1000


class ChromaVectorStore:
    """Args:
        client: an existing ``chromadb`` client; if omitted one is created.
        path: directory for a persistent client (ignored when ``client`` is given);
            without a path an in-memory (ephemeral) client is used.
        space: distance function of new collections (``cosine`` for normalised BGE vectors).
    """

    def __init__(
        self,
        client: Any | None = None,
        *,
        path: str | Path | None = None,
        space: str = "cosine",
    ) -> None:
        if client is None:
            client = (
                chromadb.PersistentClient(path=str(path)) if path else chromadb.EphemeralClient()
            )
        self._client = client
        self._space = space
        self._collections: dict[str, Any] = {}
        self._batch = int(client.get_max_batch_size())

    # ------------------------------------------------------------ collections
    def _collection(self, name: str) -> Any:
        if name not in self._collections:
            self._collections[name] = self._client.get_or_create_collection(
                name,
                embedding_function=None,  # we always bring our own vectors
                configuration={"hnsw": {"space": self._space}},  # type: ignore[arg-type]
            )
        return self._collections[name]

    def drop_collection(self, name: str) -> None:
        self._collections.pop(name, None)
        self._client.delete_collection(name)

    def count(self, collection: str) -> int:
        return int(self._collection(collection).count())

    # -------------------------------------------------------------- protocol
    def upsert(self, collection: str, records: Sequence[VectorRecord]) -> None:
        col = self._collection(collection)
        for start in range(0, len(records), self._batch):
            batch = records[start : start + self._batch]
            col.upsert(
                ids=[r.id for r in batch],
                embeddings=[list(map(float, r.embedding)) for r in batch],
                documents=[r.document for r in batch],
                metadatas=[dict(r.metadata) for r in batch],
            )

    def delete(self, collection: str, ids: Sequence[str]) -> int:
        col = self._collection(collection)
        removed = 0
        for start in range(0, len(ids), self._batch):
            batch = list(ids[start : start + self._batch])
            present = col.get(ids=batch, include=[])["ids"]
            if present:
                col.delete(ids=present)
                removed += len(present)
        return removed

    def _metadata_field(self, collection: str, document_uid: str, field: str) -> dict[str, str]:
        col = self._collection(collection)
        found: dict[str, str] = {}
        offset = 0
        while True:
            page = col.get(
                where={"document_uid": {"$eq": document_uid}},
                include=["metadatas"],
                limit=_PAGE,
                offset=offset,
            )
            for vid, meta in zip(page["ids"], page["metadatas"], strict=True):
                found[vid] = str((meta or {}).get(field, ""))
            if len(page["ids"]) < _PAGE:
                return found
            offset += _PAGE

    def list_ids(self, collection: str, *, document_uid: str) -> dict[str, str]:
        return self._metadata_field(collection, document_uid, "embedding_hash")

    def list_record_hashes(self, collection: str, *, document_uid: str) -> dict[str, str]:
        return self._metadata_field(collection, document_uid, "record_hash")

    def get_embeddings(self, collection: str, ids: Sequence[str]) -> dict[str, list[float]]:
        col = self._collection(collection)
        out: dict[str, list[float]] = {}
        for start in range(0, len(ids), self._batch):
            batch = list(ids[start : start + self._batch])
            result = col.get(ids=batch, include=["embeddings"])
            embeddings = result["embeddings"]
            if embeddings is None:
                continue
            for vid, vector in zip(result["ids"], embeddings, strict=True):
                out[vid] = [float(x) for x in vector]
        return out

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
        if k < 1:
            raise ValueError("k must be >= 1")
        clauses: list[dict[str, Any]] = [
            {"user_id": {"$eq": user_id}},
            {"course_id": {"$eq": course_id}},
        ]
        for key, value in validate_filters(filters).items():
            if isinstance(value, (list, tuple, set)):
                if not value:
                    return []  # "is one of nothing" matches nothing
                clauses.append({key: {"$in": list(value)}})
            else:
                clauses.append({key: {"$eq": value}})

        col = self._collection(collection)
        total = col.count()
        if total == 0:
            return []
        result = col.query(
            query_embeddings=[list(map(float, vector))],
            n_results=min(k, total),
            where={"$and": clauses},
            include=["documents", "metadatas", "distances"],
        )
        hits = [
            ScoredRecord(
                id=vid,
                score=1.0 - float(distance),
                document=document or "",
                metadata=dict(meta or {}),
            )
            for vid, document, meta, distance in zip(
                result["ids"][0], result["documents"][0], result["metadatas"][0], result["distances"][0],
                strict=True,
            )
        ]
        hits.sort(key=lambda h: (-h.score, h.id))
        return hits
