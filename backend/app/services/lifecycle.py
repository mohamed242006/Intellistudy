"""Deletion rules for generated content (M4 gate T-1..T-3, contract ISO-03). Imports models only, so the document
deletion path can call it without pulling in the generation stack."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.app.db.models import (
    Document,
    GenerationJob,
    JobStatus,
    Quiz,
    QuizAnswerKey,
    QuizQuestion,
    QuizSource,
    QuizStatus,
    Summary,
)


def clear_questions(session: Session, quiz_id: str) -> None:
    session.execute(delete(QuizAnswerKey).where(QuizAnswerKey.quiz_id == quiz_id))
    session.execute(delete(QuizQuestion).where(QuizQuestion.quiz_id == quiz_id))


def on_document_purged(session: Session, document: Document) -> None:
    """Team decisions T-1..T-3, applied before the document row is deleted (same transaction as the caller's)."""
    session.execute(delete(Summary).where(Summary.document_id == document.id))  # T-1
    session.execute(delete(GenerationJob).where(GenerationJob.document_id == document.id))
    quiz_ids = set(session.scalars(select(QuizSource.quiz_id).where(QuizSource.document_id == document.id,
                                                                    QuizSource.owner_id == document.owner_id)))
    for quiz_id in quiz_ids:
        others = session.scalar(select(QuizSource.id).where(QuizSource.quiz_id == quiz_id,
                                                            QuizSource.document_id != document.id).limit(1))
        quiz = session.scalars(select(Quiz).where(Quiz.id == quiz_id)).one_or_none()
        if quiz is None:
            continue
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
