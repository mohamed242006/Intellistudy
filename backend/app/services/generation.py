"""Summaries and quizzes: requests, background generation and the deletion rules (M4; docs/M4_RELEASE_GATE.md).

* :class:`GenerationService` answers the API. A request is checked in this order: ownership (same 404) -> document /
  source readiness (409) -> stored summary returned as is (T-4) or an in-flight generation reused (CAC-02) -> provider
  configured (503, D-4) -> rate limit (9a) -> token budget with a cost estimate (BUD-01/02) -> job queued (202, D-2).
* :class:`GenerationRunner` runs queued jobs on its own thread (ingestion keeps its runner). Every model call goes
  through the usage ledger with a budget check before each call (BUD-03). Results are written in one transaction only
  after the sources were re-read and found still ``ready`` (DEL-04); nothing partial is ever stored (PRV-01..03).
* ``lifecycle.on_document_purged`` applies team decisions T-1..T-3 when a document row is deleted.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from ai.answering.llm import LLMError
from backend.app.core.clock import Clock
from backend.app.core.config import Settings
from backend.app.core.errors import ApiError, not_found
from backend.app.core.ratelimit import LIMITS, RateLimiter, enforce
from backend.app.db.models import (
    Document,
    DocumentStatus,
    GenerationJob,
    GenerationKind,
    JobStatus,
    Quiz,
    QuizAnswerKey,
    QuizQuestion,
    QuizSource,
    QuizStatus,
    Summary,
    UsageFeature,
    User,
)
from backend.app.services import quizgen, summaries
from backend.app.services.ai_container import AIContainer
from backend.app.services.chat import SafeLLM
from backend.app.services.lifecycle import clear_questions, delete_attempts, expire_attempts
from backend.app.services.ownership import get_owned
from backend.app.services.retrieval import ScopedRetrieval, ready_document_ids
from backend.app.services.sources import Section, SourceUnavailable, load_sections
from backend.app.services.usage import BudgetExhausted, MeteredLLM, UsageLedger

logger = logging.getLogger(__name__)

ACTIVE = (JobStatus.QUEUED.value, JobStatus.RUNNING.value)
MAX_QUIZ_DOCUMENTS = 20
QUIZ_NOTICE = "Your materials supported {count} good questions instead of the {requested} requested."


def _llm_unavailable() -> ApiError:
    return ApiError(503, "The AI service is not configured. Stored summaries and quizzes stay available.",
                    code="llm_unavailable")


# ============================================================================================ API service
class GenerationService:
    def __init__(self, settings: Settings, ai: AIContainer, limiter: RateLimiter, clock: Clock, ledger: UsageLedger,
                 runner: GenerationRunner) -> None:
        self._settings = settings
        self._ai = ai
        self._limiter = limiter
        self._clock = clock
        self._ledger = ledger
        self._runner = runner
        self._scoped = ScopedRetrieval(ai)

    # ------------------------------------------------------------------------------------------ summaries
    def _document(self, session: Session, user: User, document_id: str) -> Document:
        document = get_owned(session, Document, document_id, user.id, resource="document")
        if document.status == DocumentStatus.DELETING.value:
            raise not_found()
        return document

    def get_summary(self, session: Session, user: User, document_id: str) -> dict[str, Any]:
        document = self._document(session, user, document_id)
        view = self._summary_view(session, user, document)
        if view is None:
            raise not_found()
        return view

    def request_summary(self, session: Session, user: User, document_id: str, *, regenerate: bool
                        ) -> tuple[int, dict[str, Any]]:
        document = self._document(session, user, document_id)
        if document.status != DocumentStatus.READY.value:
            raise ApiError(409, "This document is not ready yet.", code="document_not_ready")
        stored = self._stored_summary(session, user, document.id)
        if stored is not None and not regenerate:
            return 200, self._view_or_fail(session, user, document)  # T-4: no job, no model call, no budget use
        if self._active_job(session, user, document_id=document.id) is None:
            self._admit(session, user, LIMITS["summary:user"])
            sections = load_sections(session, self._ai, user.id, document.course_id, document.id)
            self._ledger.check(session, user.id, estimated=summaries.estimate_tokens(
                sections, self._settings.summary_batch_tokens, self._settings.summary_max_tokens))
            session.add(GenerationJob(owner_id=user.id, course_id=document.course_id, kind=GenerationKind.SUMMARY.value,
                                      document_id=document.id, status=JobStatus.QUEUED.value))
            session.commit()
            self._runner.notify()
        return 202, self._view_or_fail(session, user, document)

    def _view_or_fail(self, session: Session, user: User, document: Document) -> dict[str, Any]:
        view = self._summary_view(session, user, document)
        if view is None:  # pragma: no cover - a job or a summary exists at this point
            raise not_found()
        return view

    def _stored_summary(self, session: Session, user: User, document_id: str) -> Summary | None:
        return session.scalars(select(Summary).where(Summary.document_id == document_id,
                                                     Summary.owner_id == user.id)).one_or_none()

    def _active_job(self, session: Session, user: User, *, document_id: str | None = None,
                    quiz_id: str | None = None) -> GenerationJob | None:
        query = select(GenerationJob).where(GenerationJob.owner_id == user.id, GenerationJob.status.in_(ACTIVE))
        query = query.where(GenerationJob.document_id == document_id) if document_id else \
            query.where(GenerationJob.quiz_id == quiz_id)
        return session.scalars(query.limit(1)).first()

    def _summary_view(self, session: Session, user: User, document: Document) -> dict[str, Any] | None:
        stored = self._stored_summary(session, user, document.id)
        jobs = list(session.scalars(select(GenerationJob).where(
            GenerationJob.owner_id == user.id, GenerationJob.document_id == document.id,
            GenerationJob.kind == GenerationKind.SUMMARY.value).order_by(GenerationJob.created_at.desc(),
                                                                         GenerationJob.id).limit(5)))
        pending = any(j.status in ACTIVE for j in jobs)
        failed = next((j for j in jobs if j.status == JobStatus.FAILED.value), None)
        latest = jobs[0] if jobs else None
        error = failed.error_code if failed is not None and latest is failed else None
        if stored is None and not pending and error is None:
            return None
        status = "ready" if stored is not None else "generating" if pending else "failed"
        view: dict[str, Any] = {"document_id": document.id, "status": status, "pending": pending, "error_code": error,
                                "sections": [], "citations": [], "warnings": [], "grounding": None, "chunk_count": None,
                                "model": None, "generated_at": None}
        if stored is not None:
            view.update(sections=stored.sections, citations=stored.citations, warnings=stored.warnings,
                        grounding=stored.grounding, chunk_count=stored.chunk_count, model=stored.model,
                        generated_at=stored.generated_at)
        return view

    # -------------------------------------------------------------------------------------------- quizzes
    def create_quiz(self, session: Session, user: User, course_id: str, *, document_ids: Sequence[str] | None,
                    count: int, types: Sequence[str], title: str | None) -> Quiz:
        course, scope = self._scoped.resolve_scope(session, user, course_id, document_ids)
        if not scope:
            raise ApiError(409, "This course has no ready documents yet.", code="document_not_ready")
        if len(scope) > MAX_QUIZ_DOCUMENTS:
            raise ApiError(422, f"Select at most {MAX_QUIZ_DOCUMENTS} documents for one quiz.",
                           code="too_many_documents")
        ordered = sorted(scope)
        self._admit_quiz(session, user, course.id, ordered, count)
        quiz = Quiz(owner_id=user.id, course_id=course.id, title=(title or "Practice quiz").strip()[:200] or
                    "Practice quiz", status=QuizStatus.GENERATING.value, requested_count=count,
                    question_types=list(dict.fromkeys(types)), created_at=self._clock.now(),
                    updated_at=self._clock.now())
        session.add(quiz)
        session.flush()
        session.add_all(QuizSource(quiz_id=quiz.id, owner_id=user.id, document_id=d) for d in ordered)
        session.add(GenerationJob(owner_id=user.id, course_id=course.id, kind=GenerationKind.QUIZ.value,
                                  quiz_id=quiz.id, status=JobStatus.QUEUED.value))
        session.commit()
        self._runner.notify()
        return quiz

    def regenerate_quiz(self, session: Session, user: User, quiz_id: str) -> Quiz:
        quiz = get_owned(session, Quiz, quiz_id, user.id, resource="quiz")
        if self._active_job(session, user, quiz_id=quiz.id) is not None:
            return quiz
        sources = self._source_ids(session, quiz)
        if not sources or ready_document_ids(session, user.id, quiz.course_id, within=set(sources)) != set(sources):
            raise ApiError(409, "A source document of this quiz is not ready.", code="document_not_ready")
        self._admit_quiz(session, user, quiz.course_id, sources, quiz.requested_count)
        expire_attempts(session, quiz.id, "quiz_regenerated")  # M5 D5-3; submitted attempts untouched (D5-11)
        quiz.generation += 1
        clear_questions(session, quiz.id)
        quiz.status, quiz.invalid_reason, quiz.error_code, quiz.notice = QuizStatus.GENERATING.value, None, None, None
        quiz.question_count = 0
        session.add(GenerationJob(owner_id=user.id, course_id=quiz.course_id, kind=GenerationKind.QUIZ.value,
                                  quiz_id=quiz.id, status=JobStatus.QUEUED.value))
        session.commit()
        self._runner.notify()
        return quiz

    def _admit_quiz(self, session: Session, user: User, course_id: str, document_ids: Sequence[str], count: int
                    ) -> None:
        self._admit(session, user, LIMITS["quiz:user"])
        sections = quizgen.interleave([load_sections(session, self._ai, user.id, course_id, d) for d in document_ids])
        settings = self._settings
        self._ledger.check(session, user.id, estimated=quizgen.estimate_tokens(
            sections, count, batch_questions=settings.quiz_batch_questions, context_tokens=settings.quiz_context_tokens,
            max_tokens=settings.quiz_max_tokens))

    def _admit(self, session: Session, user: User, limit: Any) -> None:
        if self._ai.provider is None:
            raise _llm_unavailable()
        enforce(self._limiter, limit, user.id, actor=user.id)

    def list_quizzes(self, session: Session, user: User, course_id: str, *, limit: int, offset: int) -> list[Quiz]:
        course, _ = self._scoped.resolve_scope(session, user, course_id)
        return list(session.scalars(select(Quiz).where(Quiz.owner_id == user.id, Quiz.course_id == course.id)
                                    .order_by(Quiz.created_at.desc(), Quiz.id).limit(limit).offset(offset)))

    def get_quiz(self, session: Session, user: User, quiz_id: str) -> tuple[Quiz, list[QuizQuestion], list[str]]:
        quiz = get_owned(session, Quiz, quiz_id, user.id, resource="quiz")
        questions: list[QuizQuestion] = []
        if quiz.status == QuizStatus.READY.value:  # an invalid quiz shows no questions (KEY-06)
            questions = list(session.scalars(select(QuizQuestion).where(
                QuizQuestion.quiz_id == quiz.id, QuizQuestion.owner_id == user.id).order_by(QuizQuestion.position)))
        return quiz, questions, self._source_ids(session, quiz)

    def source_ids(self, session: Session, quiz: Quiz) -> list[str]:
        return self._source_ids(session, quiz)

    def _source_ids(self, session: Session, quiz: Quiz) -> list[str]:
        return list(session.scalars(select(QuizSource.document_id).where(
            QuizSource.quiz_id == quiz.id, QuizSource.owner_id == quiz.owner_id).order_by(QuizSource.document_id)))

    def delete_quiz(self, session: Session, user: User, quiz_id: str) -> None:
        quiz = get_owned(session, Quiz, quiz_id, user.id, resource="quiz")
        delete_attempts(session, quiz.id)  # M5 D5-5
        session.delete(quiz)  # questions, answer keys, sources and jobs cascade
        session.commit()


# ============================================================================================ runner
class _Discard(Exception):
    """The target was deleted or changed while the job ran: drop the result silently."""


class GenerationRunner:
    def __init__(self, settings: Settings, session_factory: sessionmaker[Session], ai: AIContainer, clock: Clock,
                 ledger: UsageLedger) -> None:
        self._settings = settings
        self._sessions = session_factory
        self._ai = ai
        self._clock = clock
        self._ledger = ledger
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self.recover()
        self._thread = threading.Thread(target=self._loop, name="intellistudy-generation", daemon=True)
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
                logger.exception("generation loop error")
            self._wake.wait(timeout=2.0)
            self._wake.clear()

    def recover(self) -> int:
        """Requeue jobs left ``running`` by a crash or restart (PRV-07); their targets were never half-written."""
        with self._sessions() as session:
            count = session.execute(update(GenerationJob).where(GenerationJob.status == JobStatus.RUNNING.value)
                                    .values(status=JobStatus.QUEUED.value)
                                    .execution_options(synchronize_session=False)).rowcount  # type: ignore[attr-defined]
            session.commit()
            return int(count or 0)

    def run_pending(self) -> int:
        count = 0
        while self.run_next():
            count += 1
        return count

    def run_next(self) -> bool:
        with self._sessions() as session:
            job_id = session.scalar(select(GenerationJob.id).where(GenerationJob.status == JobStatus.QUEUED.value)
                                    .order_by(GenerationJob.created_at, GenerationJob.id).limit(1))
            if job_id is None:
                return False
            claimed: Any = session.execute(
                update(GenerationJob).where(GenerationJob.id == job_id, GenerationJob.status == JobStatus.QUEUED.value)
                .values(status=JobStatus.RUNNING.value, attempts=GenerationJob.attempts + 1,
                        started_at=self._clock.now()).execution_options(synchronize_session=False))
            session.commit()
            if claimed.rowcount != 1:
                return True
        self._run(job_id)
        return True

    def _run(self, job_id: str) -> None:
        with self._sessions() as session:
            job = session.scalars(select(GenerationJob).where(GenerationJob.id == job_id)).one_or_none()
            if job is None:
                return
            owner_id, course_id, kind = job.owner_id, job.course_id, job.kind
            document_id, quiz_id = job.document_id, job.quiz_id
        code = ""
        try:
            if kind == GenerationKind.SUMMARY.value and document_id:
                self._summary(job_id, owner_id, course_id, document_id)
            elif kind == GenerationKind.QUIZ.value and quiz_id:
                code = self._quiz(job_id, owner_id, course_id, quiz_id)
            else:
                raise _Discard
        except _Discard:
            self._finish(job_id, JobStatus.CANCELLED)
            return
        except BudgetExhausted:
            code = "token_budget"
        except LLMError as exc:
            logger.warning("generation job %s: model unavailable (%s)", job_id, type(exc).__name__)
            code = "llm_unavailable"
        except summaries.GenerationFailed as exc:
            code = exc.code
        except Exception as exc:
            logger.error("generation job %s failed: %s", job_id, type(exc).__name__)
            code = "internal_error"
        if code:
            self._fail(job_id, quiz_id, code)
        else:
            self._finish(job_id, JobStatus.DONE)

    def _llm(self, session: Session, owner_id: str, feature: UsageFeature) -> MeteredLLM:
        provider = self._ai.provider
        if provider is None:
            raise LLMError("no model provider is configured")
        return MeteredLLM(SafeLLM(provider), self._ledger, session, owner_id, feature, check_each_call=True)

    # ---------------------------------------------------------------------------------------- summary job
    def _summary(self, job_id: str, owner_id: str, course_id: str, document_id: str) -> None:
        settings = self._settings
        with self._sessions() as session:
            try:
                sections = load_sections(session, self._ai, owner_id, course_id, document_id)
            except SourceUnavailable:
                raise _Discard from None
            result = summaries.summarize(sections, self._llm(session, owner_id, UsageFeature.SUMMARY),
                                         batch_tokens=settings.summary_batch_tokens,
                                         max_tokens=settings.summary_max_tokens)
            session.expire_all()
            if not _still_ready(session, owner_id, course_id, [document_id]):
                raise _Discard  # deleted or no longer ready meanwhile (DEL-04): nothing is stored
            stored = session.scalars(select(Summary).where(Summary.document_id == document_id,
                                                           Summary.owner_id == owner_id)).one_or_none()
            if stored is None:
                stored = Summary(owner_id=owner_id, course_id=course_id, document_id=document_id)
                session.add(stored)
            stored.sections, stored.citations, stored.warnings = result.sections, result.citations, result.warnings
            stored.grounding, stored.chunk_count, stored.model = result.grounding, result.chunk_count, result.model
            stored.generated_at = self._clock.now()
            session.execute(update(GenerationJob).where(GenerationJob.id == job_id).values(
                status=JobStatus.DONE.value, finished_at=self._clock.now()))
            session.commit()  # the old summary is replaced in this one transaction (CAC-03)

    # ------------------------------------------------------------------------------------------- quiz job
    def _quiz(self, job_id: str, owner_id: str, course_id: str, quiz_id: str) -> str:
        settings = self._settings
        with self._sessions() as session:
            quiz = session.scalars(select(Quiz).where(Quiz.id == quiz_id, Quiz.owner_id == owner_id)).one_or_none()
            if quiz is None or quiz.status != QuizStatus.GENERATING.value:
                raise _Discard
            sources = list(session.scalars(select(QuizSource.document_id).where(
                QuizSource.quiz_id == quiz_id, QuizSource.owner_id == owner_id).order_by(QuizSource.document_id)))
            requested, types = quiz.requested_count, list(quiz.question_types)
            try:
                per_document: list[list[Section]] = [load_sections(session, self._ai, owner_id, course_id, d)
                                                     for d in sources]
            except SourceUnavailable:
                raise _Discard from None  # the deletion rules (T-2 / T-3) own the quiz's state
            result = quizgen.generate(quizgen.interleave(per_document), self._llm(session, owner_id, UsageFeature.QUIZ),
                                      requested=requested, types=types, batch_questions=settings.quiz_batch_questions,
                                      context_tokens=settings.quiz_context_tokens, max_tokens=settings.quiz_max_tokens)
            if result.dropped or result.discarded_batches:
                logger.info("quiz job %s: %d questions kept, dropped %s, %d batches discarded", job_id,
                            len(result.questions), dict(result.dropped), result.discarded_batches)
            session.expire_all()
            quiz = session.scalars(select(Quiz).where(Quiz.id == quiz_id, Quiz.owner_id == owner_id)).one_or_none()
            if quiz is None or quiz.status != QuizStatus.GENERATING.value:
                raise _Discard
            current = set(session.scalars(select(QuizSource.document_id).where(QuizSource.quiz_id == quiz_id)))
            if current != set(sources) or not _still_ready(session, owner_id, course_id, sources):
                raise _Discard
            if len(result.questions) < quizgen.MIN_QUESTIONS:
                return "insufficient_material"
            for position, candidate in enumerate(result.questions, start=1):
                if not set(candidate.document_ids) <= set(sources):  # by construction; kept as a tripwire
                    raise _Discard
                question = QuizQuestion(quiz_id=quiz_id, owner_id=owner_id, position=position, type=candidate.type,
                                        stem=candidate.stem, options=candidate.options, topic=candidate.topic,
                                        difficulty=candidate.difficulty, cognitive_level=candidate.cognitive_level)
                session.add(question)
                session.flush()
                session.add(QuizAnswerKey(question_id=question.id, quiz_id=quiz_id, owner_id=owner_id,
                                          correct_index=candidate.correct_index, correct_bool=candidate.correct_bool,
                                          rationales=candidate.rationales, evidence=candidate.evidence,
                                          source_chunk_ids=candidate.source_keys,
                                          source_document_ids=candidate.document_ids))
            count = len(result.questions)
            quiz.status, quiz.question_count, quiz.model = QuizStatus.READY.value, count, result.model
            quiz.generated_at, quiz.error_code = self._clock.now(), None
            quiz.notice = QUIZ_NOTICE.format(count=count, requested=requested) if count < requested else None
            session.execute(update(GenerationJob).where(GenerationJob.id == job_id).values(
                status=JobStatus.DONE.value, finished_at=self._clock.now()))
            session.commit()
            return ""

    # ------------------------------------------------------------------------------------------- helpers
    def _fail(self, job_id: str, quiz_id: str | None, code: str) -> None:
        with self._sessions() as session:
            session.execute(update(GenerationJob).where(GenerationJob.id == job_id).values(
                status=JobStatus.FAILED.value, error_code=code, finished_at=self._clock.now()))
            if quiz_id:
                session.execute(update(Quiz).where(Quiz.id == quiz_id, Quiz.status == QuizStatus.GENERATING.value)
                                .values(status=QuizStatus.FAILED.value, error_code=code))
            session.commit()

    def _finish(self, job_id: str, status: JobStatus) -> None:
        with self._sessions() as session:
            session.execute(update(GenerationJob).where(GenerationJob.id == job_id, GenerationJob.status.in_(ACTIVE))
                            .values(status=status.value, finished_at=self._clock.now()))
            session.commit()


def _still_ready(session: Session, owner_id: str, course_id: str, document_ids: Sequence[str]) -> bool:
    return ready_document_ids(session, owner_id, course_id, within=set(document_ids)) == set(document_ids)
