"""Scoped source loading for summaries and quizzes (contract RET-09, RET-05, RET-06; M4 gate G4-SIS-04/08, QIS-04).

Generation reads whole sections (parent chunks), not search hits. The only path: an owned, **ready** document row ->
its parent keys -> ``parent_store.get_many(keys, user_id, course_id)``. Every parent is then checked against the
row's scope (tripwire: dropped and logged at error level, expected never to fire).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai.answering.models import SourceRef
from ai.chunking.models import ParentChunk
from backend.app.core.logging import security_event
from backend.app.db.models import Document, DocumentStatus
from backend.app.services.ai_container import AIContainer


class SourceUnavailable(Exception):
    """The document is gone, foreign, or not ``ready`` (anymore)."""


@dataclass(frozen=True, slots=True)
class Section:
    """One parent chunk of a document, in document order."""

    key: str  # parent-store key ({document_uid}:{chunk_id})
    document_id: str
    file_name: str
    citation_label: str
    page: int | None
    slide: int | None
    heading: str
    text: str
    tokens: int

    def source(self, tag: str) -> SourceRef:
        return SourceRef(tag=tag, chunk_id=self.key, document_uid=self.document_id, file_name=self.file_name,
                         citation_label=self.citation_label, page_number=self.page or 0, slide_number=self.slide,
                         kind="text", text=self.text, score=1.0)


def ready_document(session: Session, owner_id: str, course_id: str, document_id: str) -> Document:
    """The document row, owned and in that course and ``ready`` -- re-read from the database every time."""
    document = session.scalars(select(Document).where(
        Document.id == document_id, Document.owner_id == owner_id, Document.course_id == course_id)).one_or_none()
    if document is None or document.status != DocumentStatus.READY.value:
        raise SourceUnavailable(document_id)
    return document


def load_sections(session: Session, ai: AIContainer, owner_id: str, course_id: str, document_id: str
                  ) -> list[Section]:
    document = ready_document(session, owner_id, course_id, document_id)
    store = ai.parent_store()
    keys = sorted(store.list_ids(document_uid=document.id))  # ids from the owned row, never from a request
    parents = store.get_many(keys, user_id=owner_id, course_id=course_id)
    kept: list[ParentChunk] = []
    dropped = 0
    for parent in parents.values():
        if (parent.user_id, parent.course_id, parent.document_uid) != (owner_id, course_id, document.id):
            dropped += 1
            continue
        kept.append(parent)
    if dropped:
        security_event("source_scope_violation", level=logging.ERROR, user_id=owner_id, course_id=course_id,
                       document_id=document.id, dropped=dropped)
    kept.sort(key=lambda p: (p.ordinal, p.chunk_id))
    return [_section(p, document) for p in kept if p.text.strip()]


def _section(parent: ParentChunk, document: Document) -> Section:
    heading = " > ".join(h for h in parent.heading_path if h)[:200] if parent.heading_path else ""
    return Section(
        key=parent.store_key, document_id=document.id, file_name=document.file_name,
        citation_label=parent.citation_label, page=None if parent.slide_number is not None else parent.page_start,
        slide=parent.slide_number, heading=heading or parent.citation_label, text=parent.text,
        tokens=max(int(parent.token_count or 0), 1),
    )
