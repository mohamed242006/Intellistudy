"""Scoped retrieval: the **only** path from the backend to ``RetrievalService`` (contract RET-01..08; M3 gate 2.1, 2.8).

Release blocker F-M2-10: vectors are written before a document is ``ready``, so retrieval must never rely on the
vector store alone. Every search here:

1. loads the course with ``get_owned`` (RET-02) -- user and course never come from the client;
2. reads the course's searchable documents from the database with an **exact-equality allowlist**:
   ``status == 'ready'`` and nothing else (unknown or misspelt statuses are excluded, never "everything but ...");
3. intersects any client-chosen ``document_ids`` with that set; an id outside it is the same 404 (RET-04);
4. does not query the vector store at all when the scope is empty (RET-03);
5. searches with ``user_id``, ``course_id`` **and** ``document_uids`` = that scope;
6. **re-reads** the ready set after the search and drops every hit and parent whose document is no longer ready (a
   document deleted or reset mid-search, RET-05), and drops -- with a security event -- anything whose user, course
   or document lies outside the scope (tripwire, RET-06). Only what survives can reach a prompt (RET-08).

``BoundRetrieval`` exposes the same ``search`` signature as ``RetrievalService`` so the unchanged ``AnswerService``
can use it; it ignores the caller's scope arguments except to check that they match the bound user and course.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai.chunking.interfaces import FilterValue
from ai.retrieval.models import RetrievalResult
from backend.app.core.errors import not_found
from backend.app.core.logging import security_event
from backend.app.db.models import Course, Document, DocumentStatus, User
from backend.app.services.ai_container import AIContainer
from backend.app.services.ownership import get_owned, is_canonical_id

#: The one status whose documents may be retrieved. An allowlist, compared by equality (F-M2-10).
RETRIEVABLE_STATUSES: frozenset[str] = frozenset({DocumentStatus.READY.value})

NO_READY_DOCUMENTS = "no_ready_documents"


def ready_document_ids(session: Session, owner_id: str, course_id: str,
                       within: Iterable[str] | None = None) -> set[str]:
    """Ids of the owner's documents in the course whose status is exactly ``ready``."""
    query = select(Document.id).where(
        Document.owner_id == owner_id,
        Document.course_id == course_id,
        Document.status.in_(sorted(RETRIEVABLE_STATUSES)),
    )
    if within is not None:
        query = query.where(Document.id.in_(list(within)))
    return set(session.scalars(query))


@dataclass(slots=True)
class ScopedResult:
    result: RetrievalResult
    scope: frozenset[str]  # the document ids that were searchable
    reason: str = ""  # NO_READY_DOCUMENTS when the store was not queried
    dropped_not_ready: int = 0
    dropped_out_of_scope: int = 0


class ScopedRetrieval:
    def __init__(self, ai: AIContainer) -> None:
        self._ai = ai

    def resolve_scope(self, session: Session, user: User, course_id: str,
                      document_ids: Sequence[str] | None = None) -> tuple[Course, frozenset[str]]:
        """The owned course and its searchable documents (optionally narrowed by the client)."""
        course = get_owned(session, Course, course_id, user.id, resource="course")
        ready = ready_document_ids(session, user.id, course.id)
        if document_ids is None:
            return course, frozenset(ready)
        requested = list(document_ids)
        if not requested or len(requested) > 100:
            raise not_found()
        for raw in requested:  # RET-04: foreign, other-course, non-ready or malformed ids are the same 404
            if not isinstance(raw, str) or not is_canonical_id(raw) or raw not in ready:
                security_event("retrieval_scope_rejected", user_id=user.id, course_id=course.id,
                               document_id=raw if isinstance(raw, str) and is_canonical_id(raw) else "malformed")
                raise not_found()
        return course, frozenset(requested)

    def search(self, session: Session, user: User, course: Course, scope: frozenset[str], query: str, *,
               k: int = 6, filters: Mapping[str, FilterValue] | None = None, **options: Any) -> ScopedResult:
        if not scope:
            return ScopedResult(RetrievalResult(query=query), scope, reason=NO_READY_DOCUMENTS)
        result = self._ai.retrieval().search(
            query, user_id=user.id, course_id=course.id, k=k, document_uids=sorted(scope), filters=filters,
            **options,
        )
        return self._recheck(session, user, course, scope, result)

    def bind(self, session: Session, user: User, course: Course, scope: frozenset[str]) -> BoundRetrieval:
        return BoundRetrieval(self, session, user, course, scope)

    # ------------------------------------------------------------------------------------------ re-check
    def _recheck(self, session: Session, user: User, course: Course, scope: frozenset[str],
                 result: RetrievalResult) -> ScopedResult:
        returned = {h.document_uid for h in result.hits} | {p.parent.document_uid for p in result.parents}
        still_ready = ready_document_ids(session, user.id, course.id, within=returned & scope) if returned else set()
        dropped_not_ready = dropped_out_of_scope = 0

        def allowed(user_id: str, course_id: str, document_uid: str) -> bool:
            nonlocal dropped_not_ready, dropped_out_of_scope
            if user_id != user.id or course_id != course.id or document_uid not in scope:
                dropped_out_of_scope += 1
                return False
            if document_uid not in still_ready:  # changed status during the search (F-M2-10)
                dropped_not_ready += 1
                return False
            return True

        result.hits = [h for h in result.hits if allowed(h.user_id, h.course_id, h.document_uid)]
        result.parents = [p for p in result.parents
                          if allowed(p.parent.user_id, p.parent.course_id, p.parent.document_uid)]
        if dropped_out_of_scope:
            security_event("retrieval_scope_violation", user_id=user.id, course_id=course.id,
                           dropped=dropped_out_of_scope)
        if dropped_not_ready:
            result.warnings.append("some passages were skipped because their document is no longer available")
        return ScopedResult(result, scope, dropped_not_ready=dropped_not_ready, dropped_out_of_scope=dropped_out_of_scope)


class BoundRetrieval:
    """``RetrievalService``-compatible view bound to one user, course and scope (for ``AnswerService``)."""

    def __init__(self, scoped: ScopedRetrieval, session: Session, user: User, course: Course,
                 scope: frozenset[str]) -> None:
        self._scoped = scoped
        self._session = session
        self._user = user
        self._course = course
        self._scope = scope
        self.last: ScopedResult | None = None

    def search(self, query: str, *, user_id: str, course_id: str, k: int = 5,
               document_uids: Sequence[str] | None = None, filters: Mapping[str, FilterValue] | None = None,
               **options: Any) -> RetrievalResult:
        if user_id != self._user.id or course_id != self._course.id:  # a caller cannot widen the bound scope
            security_event("retrieval_scope_violation", user_id=self._user.id, course_id=self._course.id,
                           requested_course=course_id)
            raise not_found()
        scope = self._scope if document_uids is None else self._scope & frozenset(document_uids)
        self.last = self._scoped.search(self._session, self._user, self._course, scope, query, k=k,
                                        filters=filters, **options)
        return self.last.result
