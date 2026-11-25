"""Quiz attempts and deterministic grading (M5; docs/M5_RELEASE_GATE.md).

* Ownership first (same 404, OWN-03/04), then the per-user rate limit (D5-9), then state checks (409).
* An attempt belongs to one generation of its quiz (D5-3); ``regenerate`` expires in-progress attempts
  (``lifecycle.expire_attempts``). At most one in-progress attempt per user and quiz (D5-2; partial unique index).
* Saving an answer never reveals whether it is correct (ISO-04, G5-KEY-02).
* Submission writes one result snapshot per question in the same transaction that flips the attempt to
  ``submitted``; nothing changes it afterwards (D5-4, D5-11, ISO-11). Submitting again returns the snapshot.
* This module is the only reader of the answer key outside generation (G5-KEY-05). No model call, no ledger row
  (T-6, G5-GRD-06).

State-changing statements start a fresh transaction with the conditional ``UPDATE`` that claims the attempt row, so
concurrent saves and submissions serialise on that row (SQLite: the write lock; PostgreSQL: the row lock).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.clock import Clock
from backend.app.core.config import Settings
from backend.app.core.errors import ApiError, not_found
from backend.app.core.logging import security_event
from backend.app.core.ratelimit import LIMITS, RateLimiter, enforce
from backend.app.db.models import (
    AttemptAnswer,
    AttemptResult,
    AttemptStatus,
    Document,
    Quiz,
    QuizAnswerKey,
    QuizAttempt,
    QuizQuestion,
    QuizSource,
    QuizStatus,
    User,
)
from backend.app.services.ai_container import AIContainer
from backend.app.services.ownership import get_owned, is_canonical_id
from backend.app.services.retrieval import ready_document_ids

logger = logging.getLogger(__name__)

IN_PROGRESS, SUBMITTED, EXPIRED = (AttemptStatus.IN_PROGRESS.value, AttemptStatus.SUBMITTED.value,
                                   AttemptStatus.EXPIRED.value)


def _conflict(code: str, detail: str, **extra: Any) -> ApiError:
    return ApiError(409, detail, code=code, extra=extra or None)


def _state_error(attempt: QuizAttempt) -> ApiError:
    if attempt.status == SUBMITTED:
        return _conflict("attempt_submitted", "This attempt was already submitted.")
    if attempt.status == EXPIRED:
        return _conflict("attempt_expired", "This attempt expired because the quiz was regenerated.")
    return _conflict("attempt_not_submitted", "This attempt has not been submitted yet.")


def topic_key(topic: str) -> str:
    return " ".join(topic.split()).casefold()


class AttemptService:
    def __init__(self, settings: Settings, ai: AIContainer, limiter: RateLimiter, clock: Clock) -> None:
        self._settings = settings
        self._ai = ai
        self._limiter = limiter
        self._clock = clock

    # ---------------------------------------------------------------------------------------- reading
    def owned_attempt(self, session: Session, user: User, attempt_id: str) -> QuizAttempt:
        return get_owned(session, QuizAttempt, attempt_id, user.id, resource="attempt")

    def list_attempts(self, session: Session, user: User, quiz_id: str, *, limit: int, offset: int
                      ) -> list[QuizAttempt]:
        quiz = get_owned(session, Quiz, quiz_id, user.id, resource="quiz")
        return list(session.scalars(select(QuizAttempt).where(
            QuizAttempt.owner_id == user.id, QuizAttempt.quiz_id == quiz.id)
            .order_by(QuizAttempt.started_at.desc(), QuizAttempt.created_at.desc(), QuizAttempt.id)
            .limit(limit).offset(offset)))

    def questions(self, session: Session, attempt: QuizAttempt) -> list[QuizQuestion]:
        """The public questions of an in-progress attempt, in its order (never the key)."""
        rows = session.scalars(select(QuizQuestion).where(
            QuizQuestion.id.in_(attempt.question_ids), QuizQuestion.quiz_id == attempt.quiz_id,
            QuizQuestion.owner_id == attempt.owner_id))
        by_id = {q.id: q for q in rows}
        return [by_id[i] for i in attempt.question_ids if i in by_id]

    def answers(self, session: Session, attempt: QuizAttempt) -> list[AttemptAnswer]:
        rows = session.scalars(select(AttemptAnswer).where(
            AttemptAnswer.attempt_id == attempt.id, AttemptAnswer.owner_id == attempt.owner_id))
        by_id = {a.question_id: a for a in rows}
        return [by_id[i] for i in attempt.question_ids if i in by_id]

    def answered_count(self, session: Session, attempt: QuizAttempt) -> int:
        return int(session.scalar(select(func.count()).select_from(AttemptAnswer).where(
            AttemptAnswer.attempt_id == attempt.id, AttemptAnswer.owner_id == attempt.owner_id)) or 0)

    def results(self, session: Session, user: User, attempt_id: str) -> tuple[QuizAttempt, list[AttemptResult]]:
        attempt = self.owned_attempt(session, user, attempt_id)
        if attempt.status != SUBMITTED:
            raise _state_error(attempt)
        return attempt, self._snapshot(session, attempt)

    @staticmethod
    def _snapshot(session: Session, attempt: QuizAttempt) -> list[AttemptResult]:
        return list(session.scalars(select(AttemptResult).where(
            AttemptResult.attempt_id == attempt.id, AttemptResult.owner_id == attempt.owner_id)
            .order_by(AttemptResult.position)))

    # ---------------------------------------------------------------------------------------- starting
    def start(self, session: Session, user: User, quiz_id: str) -> tuple[int, QuizAttempt]:
        """201 with a new attempt, or 200 with the in-progress one (resume, D5-2)."""
        quiz = get_owned(session, Quiz, quiz_id, user.id, resource="quiz")
        enforce(self._limiter, LIMITS["attempt:start"], user.id, actor=user.id)
        current = self._in_progress(session, user, quiz.id)
        if current is not None:
            return 200, current
        self._require_ready(session, user, quiz)
        question_ids = list(session.scalars(select(QuizQuestion.id).where(
            QuizQuestion.quiz_id == quiz.id, QuizQuestion.owner_id == user.id).order_by(QuizQuestion.position)))
        if not question_ids:
            raise _conflict("quiz_not_ready", "This quiz is not ready.")
        return self._create(session, user, quiz, question_ids, parent=None)

    def retry_missed(self, session: Session, user: User, attempt_id: str) -> QuizAttempt:
        parent = self.owned_attempt(session, user, attempt_id)
        enforce(self._limiter, LIMITS["attempt:start"], user.id, actor=user.id)
        if parent.status != SUBMITTED:
            raise _state_error(parent)
        quiz = get_owned(session, Quiz, parent.quiz_id, user.id, resource="quiz")
        if quiz.generation != parent.quiz_generation or quiz.status != QuizStatus.READY.value:
            raise _conflict("quiz_changed", "The quiz was regenerated after this attempt.")
        missed = [r.question_id for r in self._snapshot(session, parent) if not r.correct]
        if not missed:
            raise _conflict("nothing_to_retry", "Every question of this attempt was answered correctly.")
        current = self._in_progress(session, user, quiz.id)
        if current is not None:
            raise _conflict("attempt_in_progress", "Finish the attempt in progress first.", attempt_id=current.id)
        self._require_ready(session, user, quiz)
        code, attempt = self._create(session, user, quiz, missed, parent=parent.id)
        if code != 201:
            raise _conflict("attempt_in_progress", "Finish the attempt in progress first.", attempt_id=attempt.id)
        return attempt

    def _in_progress(self, session: Session, user: User, quiz_id: str) -> QuizAttempt | None:
        return session.scalars(select(QuizAttempt).where(
            QuizAttempt.owner_id == user.id, QuizAttempt.quiz_id == quiz_id,
            QuizAttempt.status == IN_PROGRESS)).one_or_none()

    def _require_ready(self, session: Session, user: User, quiz: Quiz) -> None:
        """The quiz is ``ready`` and every source document is still ``ready`` (not ``deleting``: G5-LIF-06)."""
        if quiz.status != QuizStatus.READY.value:
            raise _conflict("quiz_not_ready", "This quiz is not ready.")
        sources = set(session.scalars(select(QuizSource.document_id).where(
            QuizSource.quiz_id == quiz.id, QuizSource.owner_id == user.id)))
        if not sources or ready_document_ids(session, user.id, quiz.course_id, within=sources) != sources:
            raise _conflict("quiz_not_ready", "A source document of this quiz is not ready.")

    def _create(self, session: Session, user: User, quiz: Quiz, question_ids: list[str], *, parent: str | None
                ) -> tuple[int, QuizAttempt]:
        now = self._clock.now()
        attempt = QuizAttempt(owner_id=user.id, course_id=quiz.course_id, quiz_id=quiz.id,
                              quiz_generation=quiz.generation, parent_attempt_id=parent, status=IN_PROGRESS,
                              question_ids=question_ids, started_at=now, max_score=len(question_ids),
                              created_at=now, updated_at=now)
        session.add(attempt)
        try:
            session.commit()
        except IntegrityError:  # a concurrent start won the partial unique index (D5-2)
            session.rollback()
            current = self._in_progress(session, user, quiz.id)
            if current is None:
                raise
            return 200, current
        return 201, attempt

    # ------------------------------------------------------------------------------------------ answers
    def save_answer(self, session: Session, user: User, attempt_id: str, question_id: str, *,
                    choice: int | None, value: bool | None) -> AttemptAnswer:
        attempt = self.owned_attempt(session, user, attempt_id)
        enforce(self._limiter, LIMITS["attempt:answer"], user.id, actor=user.id)
        if not is_canonical_id(question_id) or question_id not in attempt.question_ids:
            raise not_found()
        if attempt.status != IN_PROGRESS:
            raise _state_error(attempt)
        question = session.scalars(select(QuizQuestion).where(
            QuizQuestion.id == question_id, QuizQuestion.quiz_id == attempt.quiz_id,
            QuizQuestion.owner_id == user.id)).one_or_none()
        if question is None:
            raise not_found()
        if (question.type == "mcq") != (choice is not None):
            raise ApiError(422, "Answer multiple-choice questions with 'choice' and true/false questions with "
                                "'value'.", code="invalid_answer")
        session.rollback()  # start the write transaction with the claim (module docstring)
        now = self._clock.now()
        claimed: Any = session.execute(update(QuizAttempt).where(
            QuizAttempt.id == attempt.id, QuizAttempt.owner_id == user.id, QuizAttempt.status == IN_PROGRESS)
            .values(updated_at=now).execution_options(synchronize_session=False))
        if claimed.rowcount != 1:  # submitted or expired meanwhile: never write (ISO-11)
            session.rollback()
            raise _state_error(self.owned_attempt(session, user, attempt.id))
        saved = session.scalars(select(AttemptAnswer).where(
            AttemptAnswer.attempt_id == attempt.id, AttemptAnswer.question_id == question_id)).one_or_none()
        if saved is None:
            saved = AttemptAnswer(attempt_id=attempt.id, owner_id=user.id, question_id=question_id)
            session.add(saved)
        saved.choice, saved.value, saved.saved_at = choice, value, now
        session.commit()
        return saved

    # ------------------------------------------------------------------------------------------- grading
    def submit(self, session: Session, user: User, attempt_id: str) -> tuple[QuizAttempt, list[AttemptResult]]:
        attempt = self.owned_attempt(session, user, attempt_id)
        enforce(self._limiter, LIMITS["attempt:submit"], user.id, actor=user.id)
        if attempt.status == SUBMITTED:  # idempotent: the stored snapshot, never graded again (D5-11)
            return attempt, self._snapshot(session, attempt)
        if attempt.status != IN_PROGRESS:
            raise _state_error(attempt)
        session.rollback()
        now = self._clock.now()
        claimed: Any = session.execute(update(QuizAttempt).where(
            QuizAttempt.id == attempt.id, QuizAttempt.owner_id == user.id, QuizAttempt.status == IN_PROGRESS)
            .values(status=SUBMITTED, submitted_at=now, updated_at=now).execution_options(synchronize_session=False))
        if claimed.rowcount != 1:
            session.rollback()
            current = self.owned_attempt(session, user, attempt.id)
            if current.status == SUBMITTED:  # a concurrent submission graded it (G5-ATT-08)
                return current, self._snapshot(session, current)
            raise _state_error(current)
        session.expire_all()  # identity-map rows were read before the claim (building the UPDATE reloads them)
        try:
            attempt = self.owned_attempt(session, user, attempt.id)
            quiz = get_owned(session, Quiz, attempt.quiz_id, user.id, resource="quiz")
            if quiz.generation != attempt.quiz_generation:
                raise _conflict("attempt_expired", "This attempt expired because the quiz was regenerated.")
            self._require_ready(session, user, quiz)
            results = self._grade(session, user, attempt)
        except Exception:
            session.rollback()  # the claim is undone; the attempt stays in progress
            raise
        attempt.score = sum(1 for r in results if r.correct)
        session.commit()
        logger.info("attempt %s submitted: %d/%d", attempt.id, attempt.score, attempt.max_score)
        return attempt, results

    def _grade(self, session: Session, user: User, attempt: QuizAttempt) -> list[AttemptResult]:
        ids = attempt.question_ids
        questions = {q.id: q for q in session.scalars(select(QuizQuestion).where(
            QuizQuestion.id.in_(ids), QuizQuestion.quiz_id == attempt.quiz_id, QuizQuestion.owner_id == user.id))}
        keys = {k.question_id: k for k in session.scalars(select(QuizAnswerKey).where(
            QuizAnswerKey.question_id.in_(ids), QuizAnswerKey.quiz_id == attempt.quiz_id,
            QuizAnswerKey.owner_id == user.id))}
        answers = {a.question_id: a for a in session.scalars(select(AttemptAnswer).where(
            AttemptAnswer.attempt_id == attempt.id, AttemptAnswer.owner_id == user.id))}
        if set(questions) != set(ids) or set(keys) != set(ids):
            raise _conflict("quiz_not_ready", "This quiz changed; start a new attempt.")
        citations = self._citations(session, user, attempt.course_id, [keys[i] for i in ids])
        results: list[AttemptResult] = []
        for question_id in ids:
            question, key, answer = questions[question_id], keys[question_id], answers.get(question_id)
            results.append(_result(attempt, question, key, answer, citations.get(question_id)))
        session.add_all(results)
        session.flush()
        return results

    def _citations(self, session: Session, user: User, course_id: str, keys: Sequence[QuizAnswerKey]
                   ) -> dict[str, dict[str, Any]]:
        """Each question's first source chunk, read through the scoped parent path (RET-09) with the tripwire."""
        wanted = {k.question_id: k.source_chunk_ids[0] for k in keys if k.source_chunk_ids}
        if not wanted:
            return {}
        documents = {d.id: d for d in session.scalars(select(Document).where(
            Document.owner_id == user.id, Document.course_id == course_id,
            Document.id.in_({d for k in keys for d in k.source_document_ids})))}
        parents = self._ai.parent_store().get_many(sorted(set(wanted.values())), user_id=user.id, course_id=course_id)
        out: dict[str, dict[str, Any]] = {}
        for question_id, chunk_key in wanted.items():
            parent = parents.get(chunk_key)
            if parent is None:
                continue
            document = documents.get(parent.document_uid)
            if document is None or (parent.user_id, parent.course_id) != (user.id, course_id):
                security_event("source_scope_violation", level=logging.ERROR, user_id=user.id, course_id=course_id)
                continue
            out[question_id] = {"document_id": document.id, "file_name": document.file_name,
                                "citation_label": parent.citation_label,
                                "page": None if parent.slide_number is not None else parent.page_start,
                                "slide": parent.slide_number}
        return out


def _result(attempt: QuizAttempt, question: QuizQuestion, key: QuizAnswerKey, answer: AttemptAnswer | None,
            citation: dict[str, Any] | None) -> AttemptResult:
    position = attempt.question_ids.index(question.id) + 1
    rationales = list(key.rationales or [])
    if question.type == "mcq":
        chosen = answer.choice if answer is not None else None
        correct = chosen is not None and chosen == key.correct_index
        rationale = rationales[key.correct_index] if key.correct_index is not None and len(rationales) == 4 else None
        rationale_chosen = (rationales[chosen] if chosen is not None and not correct and len(rationales) == 4
                            else None)
    else:
        chosen_value = answer.value if answer is not None else None
        correct = chosen_value is not None and chosen_value == key.correct_bool
        rationale, rationale_chosen = (rationales[0] if rationales else None), None
    return AttemptResult(
        attempt_id=attempt.id, owner_id=attempt.owner_id, question_id=question.id, position=position,
        type=question.type, stem=question.stem, options=list(question.options) if question.options else None,
        topic=question.topic, difficulty=question.difficulty, cognitive_level=question.cognitive_level,
        answer_choice=answer.choice if answer is not None else None,
        answer_value=answer.value if answer is not None else None, answered=answer is not None,
        correct_choice=key.correct_index, correct_value=key.correct_bool, correct=correct, evidence=key.evidence,
        rationale=rationale or None, rationale_chosen=rationale_chosen or None, citation=citation)


def time_spent(attempt: QuizAttempt) -> int | None:
    if attempt.submitted_at is None:
        return None
    started: datetime = attempt.started_at
    return max(int((attempt.submitted_at - started).total_seconds()), 0)
