"""Background processing of uploaded documents (FR-UPL-05, contract OWN-10, RET-05, ISO-03, UPL-12, VEC-01).

One in-process runner thread, one job at a time (the API process owns Chroma). A job carries ids only; at every stage
the runner re-loads the document **with its owner** and stops if it was deleted meanwhile. Parsing and chunking run
in the sandbox (sandbox.py); embedding and indexing run here. A document becomes ``ready`` only after all its chunks
are stored (RET-05); a failure removes whatever was indexed, so failed documents leave nothing retrievable.

Jobs are rows in ``processing_jobs``: a crash leaves them ``running``, and :meth:`JobRunner.recover` requeues them at
startup. Claiming uses a conditional UPDATE, so two runners can never take the same job.
"""

from __future__ import annotations

import dataclasses
import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.clock import Clock
from backend.app.core.config import Settings
from backend.app.core.logging import security_event
from backend.app.db.models import Document, DocumentStatus, JobStatus, ProcessingJob
from backend.app.services.ai_container import AIContainer
from backend.app.services.documents import purge
from backend.app.services.sandbox import ParseOutcome, run_parse
from backend.app.services.storage import FileStorage
from backend.app.services.uploads import container_of

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 2  # infrastructure errors are retried once; document problems are final
Parser = Callable[..., ParseOutcome]

_PROGRESS = {
    DocumentStatus.VALIDATING: 5, DocumentStatus.EXTRACTING: 10, DocumentStatus.CHUNKING: 40,
    DocumentStatus.EMBEDDING: 55, DocumentStatus.INDEXING: 90, DocumentStatus.READY: 100,
}


class _Gone(Exception):
    """The document was deleted (or marked for deletion) while its job ran."""


class JobRunner:
    def __init__(self, settings: Settings, session_factory: sessionmaker[Session], ai: AIContainer,
                 storage: FileStorage, clock: Clock, *, parser: Parser = run_parse) -> None:
        self._settings = settings
        self._sessions = session_factory
        self._ai = ai
        self._storage = storage
        self._clock = clock
        self._parser = parser
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.work_root = Path(settings.data_dir) / "work"

    # -------------------------------------------------------------------------------------- lifecycle
    def start(self) -> None:
        self.recover()
        self._thread = threading.Thread(target=self._loop, name="intellistudy-jobs", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=30)

    def notify(self) -> None:
        self._wake.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                while not self._stop.is_set() and self.run_next():
                    pass
            except Exception:
                logger.exception("job loop error")
            self._wake.wait(timeout=2.0)
            self._wake.clear()

    def recover(self) -> int:
        """Requeue jobs left ``running`` by a crash or restart."""
        with self._sessions() as session:
            stuck = list(session.scalars(select(ProcessingJob).where(ProcessingJob.status == JobStatus.RUNNING.value)))
            for job in stuck:
                job.status = JobStatus.QUEUED.value
                session.execute(update(Document).where(
                    Document.id == job.document_id, Document.status != DocumentStatus.DELETING.value,
                ).values(status=DocumentStatus.QUEUED.value, progress=0))
            session.commit()
            return len(stuck)

    def run_pending(self) -> int:
        """Process every queued job now (tests and scripts); returns how many ran."""
        count = 0
        while self.run_next():
            count += 1
        return count

    # ------------------------------------------------------------------------------------------ one job
    def run_next(self) -> bool:
        with self._sessions() as session:
            job_id = session.scalar(select(ProcessingJob.id).where(ProcessingJob.status == JobStatus.QUEUED.value)
                                    .order_by(ProcessingJob.created_at, ProcessingJob.id).limit(1))
            if job_id is None:
                return False
            claimed: Any = session.execute(
                update(ProcessingJob)
                .where(ProcessingJob.id == job_id, ProcessingJob.status == JobStatus.QUEUED.value)
                .values(status=JobStatus.RUNNING.value, attempts=ProcessingJob.attempts + 1,
                        started_at=self._clock.now())
                .execution_options(synchronize_session=False))
            session.commit()
            if claimed.rowcount != 1:
                return True  # another runner took it; look again
            job = session.scalars(select(ProcessingJob).where(ProcessingJob.id == job_id)).one()
            owner_id, document_id, attempts = job.owner_id, job.document_id, job.attempts
        self._run(job_id, owner_id, document_id, attempts)
        return True

    def _run(self, job_id: str, owner_id: str, document_id: str, attempts: int) -> None:
        try:
            failure = self._process(owner_id, document_id)
        except _Gone:
            self._finish(job_id, JobStatus.CANCELLED)
            self._purge_if_deleting(owner_id, document_id)
            return
        except Exception as exc:  # infrastructure error: retry once, then fail
            logger.exception("job %s failed: %s", job_id, type(exc).__name__)
            self._cleanup_index(document_id)
            if attempts < MAX_ATTEMPTS:
                self._requeue(job_id, owner_id, document_id)
            else:
                self._fail(job_id, owner_id, document_id, "internal_error")
            self._purge_if_deleting(owner_id, document_id)
            return
        if failure:  # a problem with the document itself: final, no retry
            self._cleanup_index(document_id)
            self._fail(job_id, owner_id, document_id, failure)
        else:
            self._finish(job_id, JobStatus.DONE)
        self._purge_if_deleting(owner_id, document_id)  # deleted while the job was finishing

    def _process(self, owner_id: str, document_id: str) -> str:
        """Run the pipeline for one document; return a failure code ("" on success)."""
        document = self._stage(owner_id, document_id, DocumentStatus.EXTRACTING)
        path = self._storage.document_path(owner_id, document_id, document["file_type"])
        with path.open("rb") as handle:
            container = container_of(handle.read(8))
        outcome = self._parser(path, kind=document["file_type"], container=container, user_id=owner_id,
                               course_id=document["course_id"], document_id=document_id, settings=self._settings,
                               work_root=self.work_root)
        if not outcome.ok:
            return outcome.error or "unreadable"
        # VEC-01: the chunks must carry exactly this row's scope (the sandbox checked; checked again here)
        for chunk in (*outcome.children, *outcome.parents):
            if (chunk.user_id, chunk.course_id, chunk.document_uid) != (owner_id, document["course_id"], document_id):
                security_event("chunk_scope_mismatch", document_id=document_id)
                return "invalid_output"
        # the parser only knows the stored name ("original.pdf"); citations must show the user's file name
        children = [dataclasses.replace(c, file_name=document["file_name"]) for c in outcome.children]
        parents = [dataclasses.replace(p, file_name=document["file_name"]) for p in outcome.parents]
        self._stage(owner_id, document_id, DocumentStatus.EMBEDDING, page_count=outcome.page_count)
        indexing = self._ai.indexing()
        self._stage(owner_id, document_id, DocumentStatus.INDEXING)
        indexing.index(children, document_uid=document_id, parents=parents)
        self._stage(owner_id, document_id, DocumentStatus.READY, chunk_count=len(outcome.children),
                    warnings=outcome.warnings, ready=True)
        return ""

    # ---------------------------------------------------------------------------------------- helpers
    def _stage(self, owner_id: str, document_id: str, status: DocumentStatus, *, page_count: int | None = None,
               chunk_count: int | None = None, warnings: list[str] | None = None, ready: bool = False
               ) -> dict[str, Any]:
        """Re-load the document with its owner (OWN-10), stop if it is gone, then record the stage."""
        with self._sessions() as session:
            document = session.scalars(select(Document).where(
                Document.id == document_id, Document.owner_id == owner_id)).one_or_none()
            if document is None or document.status == DocumentStatus.DELETING.value:
                raise _Gone
            document.status = status.value
            document.progress = _PROGRESS[status]
            document.error_code = None
            if page_count is not None:
                document.page_count = page_count
            if chunk_count is not None:
                document.chunk_count = chunk_count
            if warnings is not None:
                document.warnings = warnings
            if ready:
                document.ready_at = self._clock.now()
            session.commit()
            return {"file_type": document.file_type, "course_id": document.course_id, "file_name": document.file_name}

    def _fail(self, job_id: str, owner_id: str, document_id: str, code: str) -> None:
        with self._sessions() as session:
            session.execute(update(Document).where(
                Document.id == document_id, Document.owner_id == owner_id,
                Document.status != DocumentStatus.DELETING.value,
            ).values(status=DocumentStatus.FAILED.value, error_code=code, progress=0))
            session.execute(update(ProcessingJob).where(ProcessingJob.id == job_id).values(
                status=JobStatus.FAILED.value, error_code=code, finished_at=self._clock.now()))
            session.commit()

    def _finish(self, job_id: str, status: JobStatus) -> None:
        with self._sessions() as session:
            session.execute(update(ProcessingJob).where(ProcessingJob.id == job_id).values(
                status=status.value, finished_at=self._clock.now()))
            session.commit()

    def _requeue(self, job_id: str, owner_id: str, document_id: str) -> None:
        with self._sessions() as session:
            session.execute(update(ProcessingJob).where(ProcessingJob.id == job_id).values(
                status=JobStatus.QUEUED.value))
            session.execute(update(Document).where(
                Document.id == document_id, Document.owner_id == owner_id,
                Document.status != DocumentStatus.DELETING.value,
            ).values(status=DocumentStatus.QUEUED.value, progress=0))
            session.commit()

    def _cleanup_index(self, document_id: str) -> None:
        try:
            self._ai.remove_document(document_id)
        except Exception:
            logger.exception("could not remove partial index of %s", document_id)

    def _purge_if_deleting(self, owner_id: str, document_id: str) -> None:
        """Finish a deletion requested while the job ran (or a course deleted meanwhile, row already gone)."""
        with self._sessions() as session:
            document = session.scalars(select(Document).where(Document.id == document_id)).one_or_none()
            if document is None:
                self._ai.remove_document(document_id)
                self._storage.delete_document(owner_id, document_id)
            elif document.status == DocumentStatus.DELETING.value:
                purge(session, self._ai, self._storage, document)
