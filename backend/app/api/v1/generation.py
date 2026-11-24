"""Summaries and quizzes (M4; docs/M4_RELEASE_GATE.md).

The quiz schemas below are the only serialisers of quiz content. They have no field for the correct answer, rationales,
evidence or sources, and this module never imports the answer-key model (contract ISO-04, G4-KEY-01..03).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, Path, Query, Request, Response, status
from pydantic import BaseModel, Field, StringConstraints

from backend.app.api.deps import CurrentUser, DbSession
from backend.app.api.v1.schemas import RequestModel
from backend.app.db.models import Quiz, QuizQuestion
from backend.app.services.generation import MAX_QUIZ_DOCUMENTS, GenerationService
from backend.app.services.quizgen import MAX_QUESTIONS, MIN_QUESTIONS

router = APIRouter(tags=["summaries", "quizzes"])

Id = Annotated[str, Path()]


def get_generation(request: Request) -> GenerationService:
    service: GenerationService = request.app.state.generation
    return service


Generation = Annotated[GenerationService, Depends(get_generation)]


# ------------------------------------------------------------------------------------------------ summaries
class SummaryRequest(RequestModel):
    regenerate: bool = False


class SourceRange(BaseModel):
    kind: Literal["page", "slide"]
    start: int
    end: int


class SummarySection(BaseModel):
    heading: str
    text: str
    citations: list[int]
    source_range: SourceRange | None


class SummaryCitation(BaseModel):
    number: int
    document_id: str
    file_name: str
    citation_label: str
    page: int | None
    slide: int | None
    passage: str


class SummaryOut(BaseModel):
    document_id: str
    status: Literal["generating", "ready", "failed"]
    pending: bool
    error_code: str | None
    sections: list[SummarySection]
    citations: list[SummaryCitation]
    warnings: list[str]
    grounding: dict[str, int] | None
    chunk_count: int | None
    model: str | None
    generated_at: datetime | None


@router.get("/documents/{document_id}/summary", response_model=SummaryOut)
def get_summary(document_id: Id, user: CurrentUser, session: DbSession, service: Generation) -> SummaryOut:
    return SummaryOut(**service.get_summary(session, user, document_id))


@router.post("/documents/{document_id}/summary", response_model=SummaryOut,
             responses={202: {"model": SummaryOut, "description": "generation queued"}})
def request_summary(document_id: Id, user: CurrentUser, session: DbSession, service: Generation, response: Response,
                    body: Annotated[SummaryRequest, Body(default_factory=SummaryRequest)]) -> SummaryOut:
    code, view = service.request_summary(session, user, document_id, regenerate=body.regenerate)
    response.status_code = code
    return SummaryOut(**view)


# -------------------------------------------------------------------------------------------------- quizzes
QuestionType = Literal["mcq", "true_false"]


class QuizCreate(RequestModel):
    """Scope fields, answer keys and other question types are rejected (OWN-08, RET-07, T-6)."""

    document_ids: Annotated[list[str], Field(min_length=1, max_length=MAX_QUIZ_DOCUMENTS)] | None = None
    question_count: Annotated[int, Field(ge=MIN_QUESTIONS, le=MAX_QUESTIONS)] = 10
    question_types: Annotated[list[QuestionType], Field(min_length=1, max_length=2,
                                                        default_factory=lambda: ["mcq", "true_false"])]
    title: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None


class QuestionOut(BaseModel):
    """Exactly what a student may see before submitting an attempt (ISO-04): no answer, rationale or evidence."""

    id: str
    position: int
    type: QuestionType
    stem: str
    options: list[str] | None
    topic: str
    difficulty: str
    cognitive_level: str


class QuizOut(BaseModel):
    id: str
    course_id: str
    title: str
    status: Literal["generating", "ready", "failed", "invalid"]
    invalid_reason: str | None
    error_code: str | None
    notice: str | None
    requested_count: int
    question_count: int
    question_types: list[str]
    source_document_ids: list[str]
    model: str | None
    generated_at: datetime | None
    created_at: datetime


class QuizDetail(QuizOut):
    questions: list[QuestionOut]


class QuizList(BaseModel):
    items: list[QuizOut]
    limit: int
    offset: int


def _quiz(quiz: Quiz, sources: list[str]) -> dict[str, Any]:
    return {"id": quiz.id, "course_id": quiz.course_id, "title": quiz.title, "status": quiz.status,
            "invalid_reason": quiz.invalid_reason, "error_code": quiz.error_code, "notice": quiz.notice,
            "requested_count": quiz.requested_count, "question_count": quiz.question_count,
            "question_types": list(quiz.question_types), "source_document_ids": sources, "model": quiz.model,
            "generated_at": quiz.generated_at, "created_at": quiz.created_at}


def _question(q: QuizQuestion) -> QuestionOut:
    return QuestionOut(id=q.id, position=q.position, type=q.type, stem=q.stem,
                       options=list(q.options) if q.options is not None else None, topic=q.topic,
                       difficulty=q.difficulty, cognitive_level=q.cognitive_level)


@router.post("/courses/{course_id}/quizzes", status_code=status.HTTP_202_ACCEPTED, response_model=QuizOut)
def create_quiz(course_id: Id, body: QuizCreate, user: CurrentUser, session: DbSession,
                service: Generation) -> QuizOut:
    quiz = service.create_quiz(session, user, course_id, document_ids=body.document_ids, count=body.question_count,
                               types=body.question_types, title=body.title)
    return QuizOut(**_quiz(quiz, service.source_ids(session, quiz)))


@router.get("/courses/{course_id}/quizzes", response_model=QuizList)
def list_quizzes(course_id: Id, user: CurrentUser, session: DbSession, service: Generation,
                 limit: Annotated[int, Query(ge=1, le=100)] = 50,
                 offset: Annotated[int, Query(ge=0, le=100_000)] = 0) -> QuizList:
    items = service.list_quizzes(session, user, course_id, limit=limit, offset=offset)
    return QuizList(items=[QuizOut(**_quiz(q, service.source_ids(session, q))) for q in items], limit=limit,
                    offset=offset)


@router.get("/quizzes/{quiz_id}", response_model=QuizDetail)
def get_quiz(quiz_id: Id, user: CurrentUser, session: DbSession, service: Generation) -> QuizDetail:
    quiz, questions, sources = service.get_quiz(session, user, quiz_id)
    return QuizDetail(**_quiz(quiz, sources), questions=[_question(q) for q in questions])


@router.delete("/quizzes/{quiz_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_quiz(quiz_id: Id, user: CurrentUser, session: DbSession, service: Generation) -> Response:
    service.delete_quiz(session, user, quiz_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/quizzes/{quiz_id}/regenerate", status_code=status.HTTP_202_ACCEPTED, response_model=QuizOut)
def regenerate_quiz(quiz_id: Id, user: CurrentUser, session: DbSession, service: Generation) -> QuizOut:
    quiz = service.regenerate_quiz(session, user, quiz_id)
    return QuizOut(**_quiz(quiz, service.source_ids(session, quiz)))
