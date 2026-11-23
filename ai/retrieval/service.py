"""RetrievalService: semantic search over child chunks, parents returned as expansion context.

Flow (docs/embedding_retrieval_architecture.md, sections C and D):

    query -> Embedder.embed_query -> VectorStore.query(user, course, filters, k)
          -> drop hits under ``min_score`` -> RetrievedChunk list (children first)
          -> unique parent ids in rank order -> ParentStore.get_many(user, course)
          -> ParentContext list (each knows which hits it expands)

The service depends only on the ``Embedder``, ``VectorStore`` and ``ParentStore`` protocols.
"""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Mapping, Sequence

from ai.chunking.config import collection_name
from ai.chunking.errors import EmbeddingError
from ai.chunking.interfaces import Embedder, FilterValue, ParentStore, VectorStore
from ai.retrieval.assessment import RelevanceAssessment, RetrievalPolicy, assess
from ai.retrieval.calibration import DEFAULT_POLICY
from ai.retrieval.models import ParentContext, RetrievalResult, RetrievedChunk
from ai.retrieval.references import asks_for_references, is_reference_section
from ai.retrieval.rerank import Reranker

logger = logging.getLogger(__name__)


class RetrievalService:
    def __init__(
        self,
        embedder: Embedder,
        store: VectorStore,
        parent_store: ParentStore | None = None,
        *,
        collection: str | None = None,
        reranker: Reranker | None = None,
        policy: RetrievalPolicy | None = None,
        candidate_pool: int = 20,
    ) -> None:
        self.embedder = embedder
        self.store = store
        self.parent_store = parent_store
        self.collection = collection or collection_name(embedder.model_name)
        self.reranker = reranker
        self.policy = policy or DEFAULT_POLICY
        self._explicit_policy = policy is not None
        self.candidate_pool = candidate_pool

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
        include_references: bool | None = None,
        rerank: bool | None = None,
        assess_relevance: bool | None = None,
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
            include_references: ``None`` (default) ranks bibliography chunks after body text unless
                the query asks about authors / citations / sources; ``False`` removes them;
                ``True`` leaves the ranking untouched.
            rerank: ``None`` uses the cross-encoder when one is configured; ``False`` skips it.
            assess_relevance: attach ``result.assessment`` (strong / weak / none advice). ``None`` (default)
                assesses when the policy applies: one passed explicitly, or the built-in policy with the
                embedder it was calibrated for. ``True`` forces it (warning on a model mismatch).
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

        use_rerank = self.reranker is not None and rerank is not False
        demote = (
            include_references is None
            and self.policy.demote_references
            and not asks_for_references(query)
        )
        pool = max(k, self.candidate_pool) if (use_rerank or demote or include_references is False) else k

        vector = self.embedder.embed_query(query)
        if len(vector) != self.embedder.dimension:
            raise EmbeddingError(
                f"query embedding has {len(vector)} dimensions, expected {self.embedder.dimension}"
            )
        records = self.store.query(
            self.collection, vector, user_id=user_id, course_id=course_id, k=pool, filters=merged
        )
        hits = [
            dataclasses.replace(chunk, is_reference=is_reference_section(chunk.heading_path, chunk.text))
            for chunk in (
                RetrievedChunk.from_record(r)
                for r in records
                if min_score is None or r.score >= min_score
            )
        ]
        if include_references is False:
            hits = [h for h in hits if not h.is_reference]
        result = RetrievalResult(query=query, hits=hits)
        if use_rerank and hits:
            hits = self._rerank(query, hits, result)
        if demote:
            hits = [h for h in hits if not h.is_reference] + [h for h in hits if h.is_reference]
        hits = hits[:k]
        result.hits = hits
        if assess_relevance or (assess_relevance is None and self._policy_applies()):
            result.assessment = self._assess(query, hits, result)
        if expand_parents and hits:
            self._expand(result, user_id, course_id, parent_token_budget)
        return result

    # --------------------------------------------------------------- assessment
    def _policy_applies(self) -> bool:
        """A policy chosen by the caller always applies; the built-in one only for the model it was measured with."""
        if self._explicit_policy:
            return True
        return not self.policy.embedding_model or self.policy.embedding_model == self.embedder.model_name

    def _assess(self, query: str, hits: list[RetrievedChunk], result: RetrievalResult) -> RelevanceAssessment:
        policy = self.policy
        if policy.embedding_model and policy.embedding_model != self.embedder.model_name:
            result.warnings.append(
                f"relevance policy {policy.version} was calibrated for {policy.embedding_model}, "
                f"not {self.embedder.model_name}; its levels are unreliable"
            )
        use_rerank = self.reranker is not None and (
            not policy.reranker_model or self.reranker.name == policy.reranker_model
        )
        if self.reranker is not None and not use_rerank:
            result.warnings.append(
                f"relevance policy {policy.version} was calibrated for reranker {policy.reranker_model}, "
                f"not {self.reranker.name}; using vector scores only"
            )
        return assess(query, hits, policy, use_rerank=use_rerank)

    # ---------------------------------------------------------------- reranking
    def _rerank(self, query: str, hits: list[RetrievedChunk], result: RetrievalResult) -> list[RetrievedChunk]:
        assert self.reranker is not None
        passages = [
            "\n".join((" > ".join(h.heading_path), h.text)) if h.heading_path else h.text for h in hits
        ]
        try:
            scores = self.reranker.score(query, passages)
        except Exception as exc:  # a failing reranker must not take search down
            logger.warning("reranker failed, keeping vector order: %s", exc)
            result.warnings.append(f"reranker failed ({type(exc).__name__}); results are in vector order")
            return hits
        if len(scores) != len(hits):
            result.warnings.append("reranker returned a different number of scores; ignored")
            return hits
        scored = [dataclasses.replace(h, rerank_score=s) for h, s in zip(hits, scores, strict=True)]
        scored.sort(key=lambda h: (-(h.rerank_score or 0.0), -h.score, h.chunk_id))
        return scored

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
