"""Embedding + vector-store indexing with idempotent re-ingestion.

Chunk ids are deterministic, so re-ingesting a document never has to create duplicates:
the planner diffs the new chunks against what the store already holds for the document
and only embeds what is genuinely new. Content that merely moved (ordinals shifted
because a section was inserted earlier) keeps its vector under the new id.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from ai.chunking.config import collection_name
from ai.chunking.errors import IndexingError
from ai.chunking.interfaces import Embedder, ParentStore, VectorRecord, VectorStore
from ai.chunking.models import ChildChunk, ParentChunk

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ReingestPlan:
    unchanged: list[str] = field(default_factory=list)  # vector ids already correct
    refresh: list[ChildChunk] = field(default_factory=list)  # vector valid, stored record stale
    embed: list[ChildChunk] = field(default_factory=list)  # need a fresh embedding
    reuse_chunks: list[ChildChunk] = field(default_factory=list)  # moved: reuse a stored vector
    reuse: dict[str, str] = field(default_factory=dict)  # new vector id -> old vector id
    delete: list[str] = field(default_factory=list)  # stale vector ids


class ReingestPlanner:
    """Pure diff between stored vectors (``id -> embedding_hash``) and new chunks."""

    def plan(
        self,
        existing: Mapping[str, str],
        chunks: Sequence[ChildChunk],
        records: Mapping[str, str] | None = None,
    ) -> ReingestPlan:
        """Diff stored state against ``chunks``.

        Args:
            existing: ``{vector id: embedding_hash}`` already stored for the document.
            chunks: the new chunks.
            records: optional ``{vector id: record_hash}``; when given, a chunk whose vector is
                valid but whose stored metadata is stale lands in ``plan.refresh``.
        """
        plan = ReingestPlan()
        new_ids = {c.vector_id for c in chunks}
        stale = [vid for vid in sorted(existing) if vid not in new_ids]

        pool: dict[str, list[str]] = {}
        for vid in stale:
            pool.setdefault(existing[vid], []).append(vid)

        for chunk in chunks:
            if existing.get(chunk.vector_id) == chunk.embedding_hash:
                if records is None or records.get(chunk.vector_id) == chunk.record_hash:
                    plan.unchanged.append(chunk.vector_id)
                else:
                    plan.refresh.append(chunk)
            elif pool.get(chunk.embedding_hash):
                plan.reuse[chunk.vector_id] = pool[chunk.embedding_hash].pop(0)
                plan.reuse_chunks.append(chunk)
            else:
                plan.embed.append(chunk)
        plan.delete = stale
        return plan


@dataclass(frozen=True, slots=True)
class IndexReport:
    embedded: int
    reused: int
    unchanged: int
    deleted: int
    parents_stored: int = 0
    parents_deleted: int = 0
    refreshed: int = 0  # metadata rewritten, vector kept

    @property
    def upserted(self) -> int:
        return self.embedded + self.reused + self.refreshed


class IndexingService:
    """Keeps a vector store (and optionally a parent store) in sync with one document.

    Only :class:`ChildChunk` objects are embedded; a :class:`ParentChunk` is rejected, and
    parents are written to the :class:`ParentStore` instead (never to the vector store).

    Order of operations makes a failure safe: embeddings are computed first (nothing is
    written if the model fails), then parents, then new vectors (so a retrievable child
    always has its parent), then stale vectors and stale parents are deleted last, so the
    document stays retrievable throughout.
    """

    def __init__(
        self,
        embedder: Embedder,
        store: VectorStore,
        *,
        collection: str | None = None,
        batch_size: int = 64,
        planner: ReingestPlanner | None = None,
        parent_store: ParentStore | None = None,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        self.embedder = embedder
        self.store = store
        self.collection = collection or collection_name(embedder.model_name)
        self.batch_size = batch_size
        self.planner = planner or ReingestPlanner()
        self.parent_store = parent_store

    # ------------------------------------------------------------------ API
    def index(
        self,
        chunks: Sequence[ChildChunk],
        *,
        document_uid: str,
        parents: Sequence[ParentChunk] | None = None,
    ) -> IndexReport:
        """Sync ``chunks`` (and, when given, their ``parents``) for one document.

        ``parents=None`` leaves stored parents alone; ``parents=[]`` removes them.
        """
        self._check(chunks, document_uid)
        self._check_parents(parents, document_uid)
        existing = self.store.list_ids(self.collection, document_uid=document_uid)
        record_hashes = None
        if hasattr(self.store, "list_record_hashes"):
            record_hashes = self.store.list_record_hashes(self.collection, document_uid=document_uid)
        plan = self.planner.plan(existing, chunks, record_hashes)

        wanted = [*plan.reuse.values(), *[c.vector_id for c in plan.refresh]]
        stored = self.store.get_embeddings(self.collection, wanted) if wanted else {}
        to_embed = list(plan.embed)
        records: list[VectorRecord] = []
        reused = refreshed = 0
        for chunk in plan.refresh:  # same vector, new metadata: rewrite the record, skip the model
            vector = stored.get(chunk.vector_id)
            if vector is None:
                to_embed.append(chunk)
                continue
            records.append(self._record(chunk, vector))
            refreshed += 1
        for chunk in plan.reuse_chunks:
            vector = stored.get(plan.reuse[chunk.vector_id])
            if vector is None:  # stored vector vanished: fall back to embedding
                to_embed.append(chunk)
                continue
            records.append(self._record(chunk, vector))
            reused += 1

        for chunk, vector in zip(to_embed, self._embed(to_embed), strict=True):
            records.append(self._record(chunk, vector))

        if parents is not None and self.parent_store is not None:
            self.parent_store.put_many(parents)  # before the vectors: children always find their parent
        if records:
            self.store.upsert(self.collection, records)
        deleted = self.store.delete(self.collection, plan.delete) if plan.delete else 0

        parents_deleted = 0
        if parents is not None and self.parent_store is not None:
            keep = {p.store_key for p in parents}
            stale = [pid for pid in self.parent_store.list_ids(document_uid=document_uid) if pid not in keep]
            parents_deleted = self.parent_store.delete(stale) if stale else 0
        report = IndexReport(
            embedded=len(to_embed),
            reused=reused,
            unchanged=len(plan.unchanged),
            deleted=deleted,
            parents_stored=len(parents or []),
            parents_deleted=parents_deleted,
            refreshed=refreshed,
        )
        logger.info("Indexed %s: %s", document_uid, report)
        return report

    def remove_document(self, document_uid: str) -> int:
        """Delete every vector of a document (e.g. when the user deletes it)."""
        ids = list(self.store.list_ids(self.collection, document_uid=document_uid))
        removed = self.store.delete(self.collection, ids) if ids else 0
        if self.parent_store is not None:
            parent_ids = list(self.parent_store.list_ids(document_uid=document_uid))
            if parent_ids:
                self.parent_store.delete(parent_ids)
        return removed

    # -------------------------------------------------------------- helpers
    def _check_parents(self, parents: Sequence[ParentChunk] | None, document_uid: str) -> None:
        if parents is None:
            return
        if self.parent_store is None and parents:
            raise IndexingError("parents were given but the service has no parent_store")
        for parent in parents:
            if not isinstance(parent, ParentChunk):
                raise IndexingError(f"expected ParentChunk, got {type(parent).__name__}")
            if parent.document_uid != document_uid:
                raise IndexingError(
                    f"parent {parent.chunk_id} belongs to {parent.document_uid!r}, not {document_uid!r}"
                )

    def _check(self, chunks: Sequence[ChildChunk], document_uid: str) -> None:
        for chunk in chunks:
            if isinstance(chunk, ParentChunk):
                raise IndexingError(
                    f"ParentChunk {chunk.chunk_id} must never be embedded; pass parents=... instead"
                )
            if not isinstance(chunk, ChildChunk):
                raise IndexingError(f"expected ChildChunk, got {type(chunk).__name__}")
            if chunk.document_uid != document_uid:
                raise IndexingError(
                    f"chunk {chunk.chunk_id} belongs to {chunk.document_uid!r}, not {document_uid!r}"
                )
            if chunk.embedding_model != self.embedder.model_name:
                raise IndexingError(
                    f"chunk {chunk.chunk_id} was prepared for model {chunk.embedding_model!r} "
                    f"but the embedder is {self.embedder.model_name!r}"
                )

    def _embed(self, chunks: Sequence[ChildChunk]) -> list[list[float]]:
        """Embed every distinct ``embedding_text`` once (repeated boilerplate is common)."""
        texts = [c.embedding_text for c in chunks]
        distinct = list(dict.fromkeys(texts))
        by_text = dict(zip(distinct, self._embed_distinct(distinct), strict=True))
        return [by_text[t] for t in texts]

    def _embed_distinct(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            result = self.embedder.embed_documents(list(batch))
            if len(result) != len(batch):
                raise IndexingError(f"embedder returned {len(result)} vectors for {len(batch)} texts")
            for vector in result:
                if len(vector) != self.embedder.dimension:
                    raise IndexingError(
                        f"embedding has {len(vector)} dimensions, expected {self.embedder.dimension}"
                    )
                # defence in depth: a custom Embedder must not poison the index
                if not all(math.isfinite(x) for x in vector) or not any(vector):
                    raise IndexingError("embedding contains NaN/inf values or is all zeros")
            vectors.extend(result)
        return vectors

    @staticmethod
    def _record(chunk: ChildChunk, vector: Sequence[float]) -> VectorRecord:
        return VectorRecord(
            id=chunk.vector_id,
            embedding=list(vector),
            document=chunk.text,
            metadata=chunk.chroma_metadata(),
        )
