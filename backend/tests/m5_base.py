"""Shared fixture for the M5 gate tests (docs/M5_RELEASE_GATE.md).

M4's users, courses and pipeline, plus: two processed decks in A's course, a ready quiz over both and a ready quiz
over one, questions of both types with correct options at varied positions and both true/false keys, and helpers
to take, answer and submit attempts. No model call happens after the quizzes are generated (gate rule 4).
"""

from __future__ import annotations

import itertools
from typing import Any

from sqlalchemy import select

from backend.app.db.models import AttemptAnswer, AttemptResult, QuizAnswerKey, QuizAttempt
from backend.tests.m4_base import FACTS, M4Case, QuizModel, summary_reply

NERVES = [FACTS[2], FACTS[3]]


def varied() -> Any:
    """Transform for :class:`QuizModel`: true/false stems differ from their evidence (so a leaked evidence string is
    detectable) and alternate between true and false keys."""
    flip = itertools.cycle([True, False])

    def transform(item: dict[str, Any]) -> dict[str, Any]:
        if item["type"] == "true_false":
            words = item["stem"].rstrip(".").split()
            item = {**item, "stem": " ".join(words[:-1]) + ".", "answer": next(flip)}
        return item

    return transform


class M5Case(M4Case):
    def setUp(self) -> None:
        super().setUp()
        self.doc_cells = self.deck(self.a, self.a_token, self.a_course, "cells.pptx", [FACTS[0], FACTS[1]])
        self.doc_nerves = self.deck(self.a, self.a_token, self.a_course, "nerves.pptx", NERVES)
        self.model = QuizModel(correct_at=None, transform=varied())
        self.use(lambda messages: summary_reply(messages) if "study summary" in messages[0].content
                 else self.model(messages))

    # -------------------------------------------------------------------------------------------- quizzes
    def ready_quiz(self, documents: list[str] | None = None, count: int = 8, *, client: Any = None,
                   token: str | None = None, course: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"question_count": count}
        if documents is not None:
            body["document_ids"] = documents
        quiz = self.quiz_ok(client or self.a, token or self.a_token, course or self.a_course, **body)
        self.assertEqual(quiz["status"], "ready", quiz)
        return quiz

    def regenerate(self, quiz_id: str, token: str | None = None) -> None:
        response = self.a.post(f"/api/v1/quizzes/{quiz_id}/regenerate", headers=self.bearer(token or self.a_token))
        self.assertEqual(response.status_code, 202, response.text)

    # ------------------------------------------------------------------------------------------- attempts
    def start(self, quiz_id: str, token: str | None = None, client: Any = None) -> Any:
        return (client or self.a).post(f"/api/v1/quizzes/{quiz_id}/attempts", headers=self.bearer(token or self.a_token))

    def start_ok(self, quiz_id: str, token: str | None = None, client: Any = None) -> dict[str, Any]:
        response = self.start(quiz_id, token, client)
        self.assertIn(response.status_code, (200, 201), response.text)
        return dict(response.json())

    def put_answer(self, attempt_id: str, question_id: str, token: str | None = None, client: Any = None,
                   **body: Any) -> Any:
        return (client or self.a).put(f"/api/v1/attempts/{attempt_id}/answers/{question_id}", json=body,
                                      headers=self.bearer(token or self.a_token))

    def submit(self, attempt_id: str, token: str | None = None, client: Any = None) -> Any:
        return (client or self.a).post(f"/api/v1/attempts/{attempt_id}/submit", headers=self.bearer(token or self.a_token))

    def submit_ok(self, attempt_id: str, token: str | None = None) -> dict[str, Any]:
        response = self.submit(attempt_id, token)
        self.assertEqual(response.status_code, 200, response.text)
        return dict(response.json())

    def results(self, attempt_id: str, token: str | None = None, client: Any = None) -> Any:
        return (client or self.a).get(f"/api/v1/attempts/{attempt_id}/results", headers=self.bearer(token or self.a_token))

    def retry(self, attempt_id: str, token: str | None = None, client: Any = None) -> Any:
        return (client or self.a).post(f"/api/v1/attempts/{attempt_id}/retry-missed",
                                       headers=self.bearer(token or self.a_token))

    def get_attempt(self, attempt_id: str, token: str | None = None, client: Any = None) -> Any:
        return (client or self.a).get(f"/api/v1/attempts/{attempt_id}", headers=self.bearer(token or self.a_token))

    # --------------------------------------------------------------------------------------------- keys
    def key_map(self, quiz_id: str) -> dict[str, QuizAnswerKey]:
        return {k.question_id: k for k in self.keys(quiz_id)}

    def right(self, question: dict[str, Any], key: QuizAnswerKey) -> dict[str, Any]:
        return {"choice": key.correct_index} if question["type"] == "mcq" else {"value": key.correct_bool}

    def wrong(self, question: dict[str, Any], key: QuizAnswerKey) -> dict[str, Any]:
        if question["type"] == "mcq":
            assert key.correct_index is not None
            return {"choice": (key.correct_index + 1) % 4}
        return {"value": not key.correct_bool}

    def answer_all(self, attempt: dict[str, Any], quiz_id: str, *, wrong: set[int] = frozenset(),  # type: ignore[assignment]
                   skip: set[int] = frozenset(), token: str | None = None) -> None:  # type: ignore[assignment]
        """Answer every question (by 1-based position in the attempt): right unless in ``wrong``, none if in ``skip``."""
        keys = self.key_map(quiz_id)
        for n, question in enumerate(attempt["questions"], start=1):
            if n in skip:
                continue
            key = keys[question["id"]]
            body = self.wrong(question, key) if n in wrong else self.right(question, key)
            response = self.put_answer(attempt["id"], question["id"], token, **body)
            self.assertEqual(response.status_code, 200, response.text)

    def take(self, quiz_id: str, *, wrong: set[int] = frozenset(), skip: set[int] = frozenset()  # type: ignore[assignment]
             ) -> tuple[dict[str, Any], dict[str, Any]]:
        attempt = self.start_ok(quiz_id)
        self.answer_all(attempt, quiz_id, wrong=wrong, skip=skip)
        return attempt, self.submit_ok(attempt["id"])

    # ---------------------------------------------------------------------------------------- inspection
    def attempt_row(self, attempt_id: str) -> QuizAttempt | None:
        with self.db() as session:
            return session.scalars(select(QuizAttempt).where(QuizAttempt.id == attempt_id)).one_or_none()

    def stored_state(self, attempt_id: str) -> dict[str, Any]:
        """Everything stored about an attempt: row, answers, result snapshot (for immutability checks, D5-11)."""
        with self.db() as session:
            row = session.scalars(select(QuizAttempt).where(QuizAttempt.id == attempt_id)).one()
            answers = sorted(((a.question_id, a.choice, a.value, a.saved_at) for a in session.scalars(
                select(AttemptAnswer).where(AttemptAnswer.attempt_id == attempt_id))), key=repr)
            results = sorted((tuple((c.key, getattr(r, c.key)) for c in AttemptResult.__table__.columns)
                              for r in session.scalars(select(AttemptResult).where(
                                  AttemptResult.attempt_id == attempt_id))), key=repr)
            return {"status": row.status, "score": row.score, "submitted_at": row.submitted_at,
                    "question_ids": list(row.question_ids), "answers": answers, "results": results}

