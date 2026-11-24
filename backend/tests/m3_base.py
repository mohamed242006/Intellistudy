"""Shared fixture for M3 tests: M2's users, courses and real processing, plus a deterministic reranker that carries
the calibrated reranker's name (so the relevance policy stays active, as in production, contract RET-10)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from ai.retrieval.rerank import DEFAULT_RERANKER_MODEL
from backend.app.services.ai_container import AIContainer
from backend.app.services.retrieval import ScopedRetrieval
from backend.tests.m2_base import M2Case


class OverlapReranker:
    """Scores a passage by the share of query words it contains (deterministic, no model)."""

    name = DEFAULT_RERANKER_MODEL

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        words = set(re.findall(r"[a-z]{3,}", query.lower()))
        out = []
        for passage in passages:
            present = set(re.findall(r"[a-z]{3,}", passage.lower()))
            out.append(10.0 * len(words & present) / max(len(words), 1) - 2.0)
        return out


class M3Case(M2Case):
    def make_ai(self) -> AIContainer:
        container = super().make_ai()
        container._reranker = OverlapReranker()
        return container

    @property
    def scoped(self) -> ScopedRetrieval:
        return ScopedRetrieval(self.app.state.ai)

    def search(self, user_token_owner: str, course_id: str, query: str, document_ids: Any = None) -> Any:
        """Run a scoped search as ``user_token_owner`` (a user id) through the only allowed path."""
        from sqlalchemy import select

        from backend.app.db.models import User

        with self.db() as session:
            user = session.scalars(select(User).where(User.id == user_token_owner)).one()
            course, scope = self.scoped.resolve_scope(session, user, course_id, document_ids)
            return self.scoped.search(session, user, course, scope, query, k=6)
