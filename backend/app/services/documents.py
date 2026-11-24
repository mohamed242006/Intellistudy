"""Documents: accept uploads, list, retry, delete (contract UPL-01..03, UPL-11, ISO-03, ISO-08, FILE-*).

Ownership: every course and document access goes through ``get_owned`` (OWN-03). Deletion follows ISO-03: the row is
marked ``deleting`` first (never retrievable again, RET-05), then vectors and parents, then the stored file, then the
rows. A document whose job is running is finished off by the job runner.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from backend.app.core.clock import Clock
from backend.app.core.config import Settings
from backend.app.core.errors import ApiError
from backend.app.core.logging import security_event
from backend.app.core.ratelimit import LIMITS, RateLimiter, enforce
from backend.app.db.base import new_uuid
from backend.app.db.models import Course, Document, DocumentStatus, JobStatus, ProcessingJob, User
from backend.app.services.ai_container import AIContainer
from backend.app.services.lifecycle import on_document_purged
from backend.app.services.ownership import get_owned
from backend.app.services.storage import FileStorage
from backend.app.services.uploads import IncomingFile, discard_all, type_problem

logger = logging.getLogger(__name__)

RESOURCE = "document"
ACTIVE_JOB = (JobStatus.QUEUED.value, JobStatus.RUNNING.value)

#: Client-facing sentence for every failure code (UPL-13). Nothing else about a failure reaches clients.
REASONS = {
    "empty_file": "The file is empty.",
    "unsupported_type": "This file type isn't supported. Upload PDF, Word (.docx) or PowerPoint (.pptx).",
    "type_mismatch": "The file's content does not match its extension.",
    "password_protected": "The file is password-protected.",
    "macro_document": "Files with macros are not accepted.",
    "archive_rejected": "The file's internal structure was rejected as unsafe.",
    "too_many_pages": "The file has too many pages or slides.",
    "corrupted": "The file appears to be damaged.",
    "unreadable": "The file couldn't be read.",
    "timed_out": "Processing the file took too long.",
    "too_large": "The file needs too much memory to process.",
    "invalid_output": "The file couldn't be processed.",
    "no_text": "No readable text was found in the file.",
    "internal_error": "Processing failed. Try again later.",
}


def reason_for(code: str | None) -> str | None:
    return None if code is None else REASONS.get(code, REASONS["internal_error"])


@dataclass(frozen=True, slots=True)
class Accepted:
    document: Document
    duplicate: bool


class DocumentService:
    def __init__(self, settings: Settings, storage: FileStorage, ai: AIContainer, limiter: RateLimiter,
                 clock: Clock) -> None:
        self._settings = settings
        self._storage = storage
        self._ai = ai
        self._limiter = limiter
        self._clock = clock

    # ------------------------------------------------------------------------------------------- upload
    def owned_course(self, session: Session, user: User, course_id: str) -> Course:
        return get_owned(session, Course, course_id, user.id, resource="course")

    def precheck_upload(self, session: Session, user: User, course_id: str) -> Course:
        """Checks that need no file bytes: the course is the caller's (UPL-01), queue capacity (9a)."""
        course = self.owned_course(session, user, course_id)
        if self._active_jobs(session, user) >= self._settings.max_queued_jobs_per_user:
            raise ApiError(429, "Too many documents are still processing. Try again later.", code="queue_full")
        return course

    def accept(self, session: Session, user: User, course: Course, files: list[IncomingFile]) -> list[Accepted]:
        """Validate the received files and create documents + jobs. All-or-nothing: any problem rejects all."""
        try:
            problems = [{"file": f.display_name, "reason": code, "message": REASONS[code]}
                        for f in files if (code := type_problem(f))]
            if problems:
                security_event("upload_rejected", user_id=user.id, reasons=[p["reason"] for p in problems])
                raise ApiError(422, "Some files were rejected.", code="upload_rejected", extra={"files": problems})
            for _ in files:  # upload:user counts files (contract 9a)
                enforce(self._limiter, LIMITS["upload:user"], user.id, actor=user.id)
            if self._active_jobs(session, user) + len(files) > self._settings.max_queued_jobs_per_user:
                raise ApiError(429, "Too many documents are still processing. Try again later.", code="queue_full")
            used = int(session.scalar(select(func.coalesce(func.sum(Document.size_bytes), 0)).where(
                Document.owner_id == user.id, Document.status != DocumentStatus.DELETING.value)) or 0)
            if used + sum(f.size for f in files) > self._settings.storage_quota_bytes:
                raise ApiError(413, "Your storage quota is full. Delete documents to upload more.",
                               code="quota_exceeded")
        except ApiError:
            discard_all(self._storage, files)
            raise

        accepted: list[Accepted] = []
        placed: list[tuple[str, str]] = []
        try:
            seen: dict[str, Document] = {}
            for item in files:
                existing = seen.get(item.sha256) or self._duplicate(session, user, course, item.sha256)
                if existing is not None:  # same user, same course only (UPL-11, ISO-08)
                    self._storage.discard(item.path)
                    accepted.append(Accepted(existing, duplicate=True))
                    continue
                document = Document(
                    id=new_uuid(), owner_id=user.id, course_id=course.id, file_name=item.display_name,
                    file_type=item.extension, size_bytes=item.size, sha256=item.sha256,
                    status=DocumentStatus.QUEUED.value, progress=0,
                )
                self._storage.place(item.path, user.id, document.id, item.extension)
                placed.append((user.id, document.id))
                session.add(document)
                session.add(ProcessingJob(owner_id=user.id, document_id=document.id, kind="ingest",
                                          status=JobStatus.QUEUED.value))
                seen[item.sha256] = document
                accepted.append(Accepted(document, duplicate=False))
            session.commit()
        except Exception:
            session.rollback()
            discard_all(self._storage, files)
            for owner_id, document_id in placed:
                self._storage.delete_document(owner_id, document_id)
            raise
        return accepted

    def _duplicate(self, session: Session, user: User, course: Course, sha256: str) -> Document | None:
        return session.scalars(select(Document).where(
            Document.owner_id == user.id, Document.course_id == course.id, Document.sha256 == sha256,
            Document.status.not_in((DocumentStatus.DELETING.value, DocumentStatus.FAILED.value)),
        ).limit(1)).first()

    def _active_jobs(self, session: Session, user: User) -> int:
        return int(session.scalar(select(func.count()).select_from(ProcessingJob).where(
            ProcessingJob.owner_id == user.id, ProcessingJob.status.in_(ACTIVE_JOB))) or 0)

    # -------------------------------------------------------------------------------------------- reads
    def list_for_course(self, session: Session, user: User, course_id: str, *, limit: int, offset: int
                        ) -> list[Document]:
        course = self.owned_course(session, user, course_id)
        return list(session.scalars(
            select(Document).where(Document.owner_id == user.id, Document.course_id == course.id,
                                   Document.status != DocumentStatus.DELETING.value)
            .order_by(Document.created_at.desc(), Document.id).limit(limit).offset(offset)))

    def get(self, session: Session, user: User, document_id: str) -> Document:
        document = get_owned(session, Document, document_id, user.id, resource=RESOURCE)
        if document.status == DocumentStatus.DELETING.value:
            raise ApiError(404, "Resource not found.", code="not_found")
        return document

    def file_path_for(self, document: Document) -> str:
        return str(self._storage.document_path(document.owner_id, document.id, document.file_type))

    # ------------------------------------------------------------------------------------------ actions
    def retry(self, session: Session, user: User, document_id: str) -> Document:
        document = self.get(session, user, document_id)
        if document.status != DocumentStatus.FAILED.value:
            raise ApiError(409, "Only failed documents can be retried.", code="not_failed")
        if self._active_jobs(session, user) >= self._settings.max_queued_jobs_per_user:
            raise ApiError(429, "Too many documents are still processing. Try again later.", code="queue_full")
        document.status, document.progress, document.error_code = DocumentStatus.QUEUED.value, 0, None
        session.add(ProcessingJob(owner_id=user.id, document_id=document.id, kind="ingest",
                                  status=JobStatus.QUEUED.value))
        session.commit()
        return document

    def delete(self, session: Session, user: User, document_id: str) -> None:
        document = self.get(session, user, document_id)
        self._mark_deleting(session, [document])
        self.finish_deletions(session, [document.id])

    def delete_course(self, session: Session, user: User, course_id: str) -> None:
        """ISO-03 for a course: documents first (marked, then purged), then the course row."""
        course = self.owned_course(session, user, course_id)
        documents = list(session.scalars(select(Document).where(
            Document.owner_id == user.id, Document.course_id == course.id)))
        self._mark_deleting(session, documents)
        self.finish_deletions(session, [d.id for d in documents])
        session.delete(course)  # FK cascade removes any rows the runner has not purged yet
        session.commit()

    def _mark_deleting(self, session: Session, documents: list[Document]) -> None:
        for document in documents:
            document.status = DocumentStatus.DELETING.value
        session.execute(update(ProcessingJob).where(
            ProcessingJob.document_id.in_([d.id for d in documents]), ProcessingJob.status == JobStatus.QUEUED.value,
        ).values(status=JobStatus.CANCELLED.value))
        session.commit()

    def finish_deletions(self, session: Session, document_ids: list[str]) -> None:
        """Purge documents marked ``deleting`` whose job is not running (the runner purges the others)."""
        for document_id in document_ids:
            document = session.scalars(select(Document).where(Document.id == document_id)).one_or_none()
            if document is None or document.status != DocumentStatus.DELETING.value:
                continue
            running = session.scalar(select(func.count()).select_from(ProcessingJob).where(
                ProcessingJob.document_id == document_id, ProcessingJob.status == JobStatus.RUNNING.value))
            if running:
                continue
            purge(session, self._ai, self._storage, document)


def purge(session: Session, ai: AIContainer, storage: FileStorage, document: Document) -> None:
    """Vectors and parents, then the stored file, then the row (ISO-03). Ids come from the owned row (VEC-04)."""
    owner_id, document_id = document.owner_id, document.id
    ai.remove_document(document_id)
    storage.delete_document(owner_id, document_id)
    on_document_purged(session, document)  # summaries and quizzes (M4 gate T-1..T-3)
    session.delete(document)
    session.commit()
    logger.info("document %s purged", document_id)
