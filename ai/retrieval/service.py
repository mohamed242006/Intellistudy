"""RetrievalService: semantic search over child chunks, parents returned as expansion context.

Flow (docs/embedding_retrieval_architecture.md, sections C and D):

    query -> Embedder.embed_query -> VectorStore.query(user, course, filters, k)
          -> drop hits under ``min_score`` -> RetrievedChunk list (children first)
          -> unique parent ids in rank order -> ParentStore.get_many(user, course)
          -> ParentContext list (each knows which hits it expands)

The service depends only on the ``Embedder``, ``VectorStore`` and ``ParentStore`` protocols.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence

from ai.chunking.config import collection_name
from ai.chunking.errors import EmbeddingError
from ai.chunking.interfaces import Embedder, FilterValue, ParentStore, VectorStore
from ai.retrieval.models import ParentContext, RetrievalResult, RetrievedChunk

logger = logging.getLogger(__name__)


class RetrievalService:
    def __init__(
        self,
        embedder: Embedder,
        store: VectorStore,
        parent_store: ParentStore | None = None,
        *,
        collection: str | None = None,
    ) -> None:
        self.embedder = embedder
        self.store = store
        self.parent_store = parent_store
        self.collection = collection or collection_name(embedder.model_name)

    def search(
        self,
        query: str,
        *,
        user_id: str,
        course_id: str,
        k: int = 5,
        document_uids: Sequence[str] | None = None,
        filters: Mapping[str, FilterValue] | None = None,
        min_score: float | None = None,
        include_low_confidence: bool = True,
        expand_parents: bool = True,
        parent_token_budget: int | None = None,
    ) -> RetrievalResult:
        """Top-``k`` child chunks for ``query`` inside one user's course.

        Args:
            document_uids: restrict to these documents.
            filters: extra metadata filters (scalar = equals, list = one of), e.g.
                ``{"heading_top": "Caching", "kind": "table"}``.
            min_score: drop hits below this similarity (an empty result means "not found
                in the material", the signal the answer layer uses to refuse).
            include_low_confidence: ``False`` removes chunks flagged ``low_confidence``.
            expand_parents: also return the parent chunk of every hit.
            parent_token_budget: cap on the total tokens of returned parents (lowest-ranked
                parents are dropped first; the best one is always kept).
        """
        if not query or not query.strip():
            raise ValueError("query must not be empty")
        if not user_id or not course_id:
            raise ValueError("user_id and course_id are mandatory")
        if k < 1:
            raise ValueError("k must be >= 1")

        merged: dict[str, FilterValue] = dict(filters or {})
        if document_uids is not None:
            merged["document_uid"] = list(document_uids)
        if not include_low_confidence:
            merged["low_confidence"] = False

        vector = self.embedder.embed_query(query)
        if len(vector) != self.embedder.dimension:
            raise EmbeddingError(
                f"query embedding has {len(vector)} dimensions, expected {self.embedder.dimension}"
            )
        records = self.store.query(
            self.collection, vector, user_id=user_id, course_id=course_id, k=k, filters=merged
        )
        hits = [
            RetrievedChunk.from_record(r)
            for r in records
            if min_score is None or r.score >= min_score
        ]
        result = RetrievalResult(query=query, hits=hits)
        if expand_parents and hits:
            self._expand(result, user_id, course_id, parent_token_budget)
        return result

    # ----------------------------------------------------------------- parents
    def _expand(
        self, result: RetrievalResult, user_id: str, course_id: str, budget: int | None
    ) -> None:
        if self.parent_store is None:
            result.warnings.append("parent expansion requested but no parent store is configured")
            return

        order: list[str] = []
        by_parent: dict[str, list[str]] = {}
        best: dict[str, float] = {}
        for hit in result.hits:  # hits are already best-first
            pid = f"{hit.document_uid}:{hit.parent_chunk_id}" if hit.parent_chunk_id else ""
            if not pid:
                result.warnings.append(f"chunk {hit.chunk_id} has no parent_chunk_id")
                continue
            if pid not in by_parent:
                order.append(pid)
                by_parent[pid] = []
                best[pid] = hit.score
            by_parent[pid].append(hit.chunk_id)

        found = self.parent_store.get_many(order, user_id=user_id, course_id=course_id)
        used = 0
        for pid in order:
            parent = found.get(pid)
            if parent is None:
                result.warnings.append(f"parent {pid} not found (hit returned without context)")
                continue
            if budget is not None and result.parents and used + parent.token_count > budget:
                result.warnings.append(f"parent {pid} omitted: token budget {budget} reached")
                continue
            used += parent.token_count
            result.parents.append(
                ParentContext(parent=parent, hit_chunk_ids=tuple(by_parent[pid]), best_score=best[pid])
            )
