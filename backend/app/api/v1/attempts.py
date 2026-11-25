"""Quiz attempts (M5; docs/M5_RELEASE_GATE.md).

Two kinds of serialiser, kept apart on purpose (ISO-04, G5-KEY-05):

* in-progress views (:class:`AttemptDetail`, :class:`SavedAnswer`) reuse M4's public ``QuestionOut`` and never see a
  key, a rationale, evidence or per-answer correctness; this module does not import the answer-key model at all;
* :class:`AttemptResults` is built only from the result snapshot of a **submitted** attempt (D5-4).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Path, Query, Request, Response, status
from pydantic import BaseModel, Field, StrictBool, StrictInt, model_validator

from backend.app.api.deps import CurrentUser, DbSession
from backend.app.api.v1.generation import QuestionOut
from backend.app.api.v1.schemas import RequestModel
from backend.app.core.errors import ApiError
from backend.app.db.models import AttemptAnswer, AttemptResult, AttemptStatus, QuizAttempt
from backend.app.services.attempts import AttemptService, time_spent, topic_key

router = APIRouter(tags=["attempts"])

Id = Annotated[str, Path()]


def get_attempts(request: Request) -> AttemptService:
    service: AttemptService = request.app.state.attempts
    return service


Attempts = Annotated[AttemptService, Depends(get_attempts)]


async def no_body(request: Request) -> None:
    """Start, submit and retry take no input: grading never reads anything from the client (G5-ABU-03)."""
    if (await request.body()).strip():
        raise ApiError(422, "This request takes no body.", code="unexpected_body")


NoBody = Depends(no_body)


# -------------------------------------------------------------------------------------------------- schemas
class AnswerIn(RequestModel):
    """``choice`` (0-3) for multiple choice, ``value`` for true/false; exactly one (G5-ATT-05)."""

    choice: Annotated[StrictInt, Field(ge=0, le=3)] | None = None
    value: StrictBool | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> AnswerIn:
        if (self.choice is None) == (self.value is None):
            raise ValueError("give exactly one of 'choice' or 'value'")
        return self


class AnswerOut(BaseModel):
    choice: int | None = None
    value: bool | None = None


class SavedAnswer(BaseModel):
    """The same fields whether the answer is right or wrong (G5-KEY-02)."""

    question_id: str
    answer: AnswerOut
    saved_at: datetime


class AttemptOut(BaseModel):
    id: str
    quiz_id: str
    course_id: str
    status: Literal["in_progress", "submitted", "expired"]
    expired_reason: str | None
    parent_attempt_id: str | None
    question_count: int
    answered_count: int
    score: int | None  # submitted attempts only
    max_score: int
    started_at: datetime
    submitted_at: datetime | None


class AttemptDetail(AttemptOut):
    questions: list[QuestionOut] | None  # in-progress attempts only
    answers: list[SavedAnswer] | None


class AttemptList(BaseModel):
    items: list[AttemptOut]
    limit: int
    offset: int


class TopicScore(BaseModel):
    topic: str
    score: int
    max_score: int


class Citation(BaseModel):
    document_id: str
    file_name: str
    citation_label: str
    page: int | None
    slide: int | None


class ResultQuestion(BaseModel):
    question_id: str
    position: int
    type: Literal["mcq", "true_false"]
    stem: str
    options: list[str] | None
    topic: str
    difficulty: str
    cognitive_level: str
    answered: bool
    answer: AnswerOut | None
    correct: bool
    correct_answer: AnswerOut
    evidence: str
    citation: Citation | None
    rationale: str | None
    rationale_chosen: str | None
    explanation_source: Literal["generated"] = "generated"


class AttemptResults(BaseModel):
    attempt_id: str
    quiz_id: str
    parent_attempt_id: str | None
    score: int
    max_score: int
    percent: float
    time_spent_seconds: int
    started_at: datetime
    submitted_at: datetime
    topics: list[TopicScore]
    questions: list[ResultQuestion]


# ------------------------------------------------------------------------------------------------- builders
def _answer(row: AttemptAnswer) -> SavedAnswer:
    return SavedAnswer(question_id=row.question_id, answer=AnswerOut(choice=row.choice, value=row.value),
                       saved_at=row.saved_at)


def _attempt(session: Any, service: AttemptService, attempt: QuizAttempt) -> dict[str, Any]:
    submitted = attempt.status == AttemptStatus.SUBMITTED.value
    return {"id": attempt.id, "quiz_id": attempt.quiz_id, "course_id": attempt.course_id, "status": attempt.status,
            "expired_reason": attempt.expired_reason, "parent_attempt_id": attempt.parent_attempt_id,
            "question_count": len(attempt.question_ids), "answered_count": service.answered_count(session, attempt),
            "score": attempt.score if submitted else None, "max_score": attempt.max_score,
            "started_at": attempt.started_at, "submitted_at": attempt.submitted_at}


def _detail(session: Any, service: AttemptService, attempt: QuizAttempt) -> AttemptDetail:
    questions: list[QuestionOut] | None = None
    answers: list[SavedAnswer] | None = None
    if attempt.status == AttemptStatus.IN_PROGRESS.value:
        questions = [QuestionOut(id=q.id, position=q.position, type=q.type, stem=q.stem,
                                 options=list(q.options) if q.options is not None else None, topic=q.topic,
                                 difficulty=q.difficulty, cognitive_level=q.cognitive_level)
                     for q in service.questions(session, attempt)]
        answers = [_answer(a) for a in service.answers(session, attempt)]
    return AttemptDetail(**_attempt(session, service, attempt), questions=questions, answers=answers)


def _results(attempt: QuizAttempt, rows: list[AttemptResult]) -> AttemptResults:
    topics: dict[str, TopicScore] = {}
    for row in rows:
        entry = topics.setdefault(topic_key(row.topic), TopicScore(topic=" ".join(row.topic.split()), score=0,
                                                                   max_score=0))
        entry.max_score += 1
        entry.score += 1 if row.correct else 0
    score = sum(1 for r in rows if r.correct)
    assert attempt.submitted_at is not None
    return AttemptResults(
        attempt_id=attempt.id, quiz_id=attempt.quiz_id, parent_attempt_id=attempt.parent_attempt_id, score=score,
        max_score=len(rows), percent=round(100.0 * score / len(rows), 1) if rows else 0.0,
        time_spent_seconds=time_spent(attempt) or 0, started_at=attempt.started_at,
        submitted_at=attempt.submitted_at, topics=list(topics.values()),
        questions=[ResultQuestion(
            question_id=r.question_id, position=r.position, type=r.type, stem=r.stem, options=r.options,
            topic=r.topic, difficulty=r.difficulty, cognitive_level=r.cognitive_level, answered=r.answered,
            answer=AnswerOut(choice=r.answer_choice, value=r.answer_value) if r.answered else None,
            correct=r.correct, correct_answer=AnswerOut(choice=r.correct_choice, value=r.correct_value),
            evidence=r.evidence, citation=Citation(**r.citation) if r.citation else None, rationale=r.rationale,
            rationale_chosen=r.rationale_chosen) for r in rows])


# --------------------------------------------------------------------------------------------------- routes
@router.post("/quizzes/{quiz_id}/attempts", status_code=status.HTTP_201_CREATED, response_model=AttemptDetail,
             responses={200: {"model": AttemptDetail, "description": "the attempt in progress, resumed"}},
             dependencies=[NoBody])
def start_attempt(quiz_id: Id, user: CurrentUser, session: DbSession, service: Attempts,
                  response: Response) -> AttemptDetail:
    code, attempt = service.start(session, user, quiz_id)
    response.status_code = code
    return _detail(session, service, attempt)


@router.get("/quizzes/{quiz_id}/attempts", response_model=AttemptList)
def list_attempts(quiz_id: Id, user: CurrentUser, session: DbSession, service: Attempts,
                  limit: Annotated[int, Query(ge=1, le=100)] = 50,
                  offset: Annotated[int, Query(ge=0, le=100_000)] = 0) -> AttemptList:
    items = service.list_attempts(session, user, quiz_id, limit=limit, offset=offset)
    return AttemptList(items=[AttemptOut(**_attempt(session, service, a)) for a in items], limit=limit, offset=offset)


@router.get("/attempts/{attempt_id}", response_model=AttemptDetail)
def get_attempt(attempt_id: Id, user: CurrentUser, session: DbSession, service: Attempts) -> AttemptDetail:
    return _detail(session, service, service.owned_attempt(session, user, attempt_id))


@router.put("/attempts/{attempt_id}/answers/{question_id}", response_model=SavedAnswer)
def save_answer(attempt_id: Id, question_id: Id, body: AnswerIn, user: CurrentUser, session: DbSession,
                service: Attempts) -> SavedAnswer:
    saved = service.save_answer(session, user, attempt_id, question_id, choice=body.choice, value=body.value)
    return _answer(saved)


@router.post("/attempts/{attempt_id}/submit", response_model=AttemptResults, dependencies=[NoBody])
def submit_attempt(attempt_id: Id, user: CurrentUser, session: DbSession, service: Attempts) -> AttemptResults:
    attempt, rows = service.submit(session, user, attempt_id)
    return _results(attempt, rows)


@router.get("/attempts/{attempt_id}/results", response_model=AttemptResults)
def attempt_results(attempt_id: Id, user: CurrentUser, session: DbSession, service: Attempts) -> AttemptResults:
    attempt, rows = service.results(session, user, attempt_id)
    return _results(attempt, rows)


@router.post("/attempts/{attempt_id}/retry-missed", status_code=status.HTTP_201_CREATED,
             response_model=AttemptDetail, dependencies=[NoBody])
def retry_missed(attempt_id: Id, user: CurrentUser, session: DbSession, service: Attempts) -> AttemptDetail:
    return _detail(session, service, service.retry_missed(session, user, attempt_id))
