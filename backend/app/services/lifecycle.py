"""Deletion rules for generated content (M4 gate T-1..T-3, M5 gate D5-3 / D5-5, contract ISO-03, ISO-11). Imports
models only, so the document deletion path can call it without pulling in the generation stack."""

from __future__ import annotations

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from backend.app.db.models import (
    AttemptAnswer,
    AttemptResult,
    AttemptStatus,
    CourseSummary,
    CourseSummarySource,
    Document,
    GenerationJob,
    JobStatus,
    Quiz,
    QuizAnswerKey,
    QuizAttempt,
    QuizQuestion,
    QuizSource,
    QuizStatus,
    Summary,
)


def clear_questions(session: Session, quiz_id: str) -> None:
    session.execute(delete(QuizAnswerKey).where(QuizAnswerKey.quiz_id == quiz_id))
    session.execute(delete(QuizQuestion).where(QuizQuestion.quiz_id == quiz_id))


def delete_attempts(session: Session, quiz_id: str) -> None:
    """Every attempt of a quiz with its answers and result snapshots, submitted ones included (D5-5, ISO-03). Explicit
    rather than left to the foreign-key cascade, so the rule holds whatever the database enforces."""
    attempt_ids = select(QuizAttempt.id).where(QuizAttempt.quiz_id == quiz_id).scalar_subquery()
    session.execute(delete(AttemptResult).where(AttemptResult.attempt_id.in_(attempt_ids)))
    session.execute(delete(AttemptAnswer).where(AttemptAnswer.attempt_id.in_(attempt_ids)))
    session.execute(delete(QuizAttempt).where(QuizAttempt.quiz_id == quiz_id))


def expire_attempts(session: Session, quiz_id: str, reason: str) -> None:
    """In-progress attempts of a quiz that is being regenerated can no longer be answered or graded (D5-3). Submitted
    attempts are not touched (D5-11, ISO-11); their snapshots stay readable."""
    session.execute(update(QuizAttempt).where(
        QuizAttempt.quiz_id == quiz_id, QuizAttempt.status == AttemptStatus.IN_PROGRESS.value)
        .values(status=AttemptStatus.EXPIRED.value, expired_reason=reason)
        .execution_options(synchronize_session=False))


def on_document_purged(session: Session, document: Document) -> None:
    """Team decisions T-1..T-3, applied before the document row is deleted (same transaction as the caller's)."""
    session.execute(delete(Summary).where(Summary.document_id == document.id))  # T-1
    session.execute(delete(GenerationJob).where(GenerationJob.document_id == document.id))
    # T-1 for combined summaries: they contain this document's text, so they are deleted with it (jobs, sources first,
    # explicitly, whatever the database's cascade does).
    combined = select(CourseSummarySource.summary_id).where(CourseSummarySource.document_id == document.id,
                                                             CourseSummarySource.owner_id == document.owner_id)
    summary_ids = set(session.scalars(combined))
    if summary_ids:
        session.execute(delete(GenerationJob).where(GenerationJob.course_summary_id.in_(summary_ids)))
        session.execute(delete(CourseSummarySource).where(CourseSummarySource.summary_id.in_(summary_ids)))
        session.execute(delete(CourseSummary).where(CourseSummary.id.in_(summary_ids)))
    quiz_ids = set(session.scalars(select(QuizSource.quiz_id).where(QuizSource.document_id == document.id,
                                                                    QuizSource.owner_id == document.owner_id)))
    for quiz_id in quiz_ids:
        others = session.scalar(select(QuizSource.id).where(QuizSource.quiz_id == quiz_id,
                                                            QuizSource.document_id != document.id).limit(1))
        quiz = session.scalars(select(Quiz).where(Quiz.id == quiz_id)).one_or_none()
        if quiz is None:
            continue
        delete_attempts(session, quiz_id)  # D5-5: snapshots may hold the deleted document's text
        if others is None:  # T-2: the quiz depended only on this document
            session.delete(quiz)
            continue
        clear_questions(session, quiz_id)  # T-3: the questions may contain the deleted document's text
        session.execute(delete(QuizSource).where(QuizSource.quiz_id == quiz_id, QuizSource.document_id == document.id))
        session.execute(delete(GenerationJob).where(GenerationJob.quiz_id == quiz_id,
                                                    GenerationJob.status == JobStatus.QUEUED.value))
        quiz.status, quiz.invalid_reason, quiz.question_count = QuizStatus.INVALID.value, "source_deleted", 0
        quiz.notice = "A source document was deleted. Regenerate this quiz to use it again."
    session.flush()
