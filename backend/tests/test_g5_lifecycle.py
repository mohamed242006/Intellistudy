"""M5 gate 2.6-2.7: quiz changes and deletion (F-M4-04, T-1..T-3, D5-3, D5-5), limits and input validation."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select, update

from backend.app.db.models import AttemptAnswer, AttemptResult, Document, LlmUsage, Quiz, QuizAttempt
from backend.tests.m4_base import FACTS
from backend.tests.m5_base import M5Case


class LifeCase(M5Case):
    def attempts_of(self, quiz_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        """A submitted attempt (with misses) and an in-progress attempt with a saved answer."""
        submitted, _ = self.take(quiz_id, wrong={1}, skip={2})
        current = self.start_ok(quiz_id)
        question = current["questions"][0]
        self.put_answer(current["id"], question["id"], **self.right(question, self.key_map(quiz_id)[question["id"]]))
        return submitted, current

    def gone(self, *attempt_ids: str) -> None:
        for attempt_id in attempt_ids:
            self.assertEqual(self.count(QuizAttempt, QuizAttempt.id == attempt_id), 0)
            self.assertEqual(self.count(AttemptAnswer, AttemptAnswer.attempt_id == attempt_id), 0)
            self.assertEqual(self.count(AttemptResult, AttemptResult.attempt_id == attempt_id), 0)
            self.assert_same_404(self.get_attempt(attempt_id), self.a_token)

    def delete_doc(self, document_id: str) -> None:
        self.assertEqual(self.a.delete(f"/api/v1/documents/{document_id}",
                                       headers=self.bearer(self.a_token)).status_code, 204)

    def ledger(self) -> tuple[int, int]:
        with self.db() as session:
            return (int(session.scalar(select(func.count()).select_from(LlmUsage)) or 0),
                    int(session.scalar(select(func.coalesce(func.sum(LlmUsage.prompt_tokens
                                                                       + LlmUsage.completion_tokens), 0))) or 0))


# ================================================================================== 2.6 changes, deletion
class QuizChangeTests(LifeCase):
    def test_g5_lif_01_regeneration_expires_attempts_in_progress(self) -> None:
        quiz = self.ready_quiz([self.doc_cells, self.doc_nerves])
        current = self.start_ok(quiz["id"])
        question = current["questions"][0]
        self.put_answer(current["id"], question["id"], **self.right(question, self.key_map(quiz["id"])[question["id"]]))
        self.regenerate(quiz["id"])
        self.generate()
        view = self.get_attempt(current["id"]).json()
        self.assertEqual((view["status"], view["expired_reason"]), ("expired", "quiz_regenerated"))
        for response in (self.put_answer(current["id"], question["id"], choice=0), self.submit(current["id"])):
            self.assertEqual((response.status_code, response.json()["type"]), (409, "about:blank#attempt_expired"))
        self.assertEqual(self.count(AttemptAnswer, AttemptAnswer.attempt_id == current["id"]), 1)
        self.assertEqual(self.count(AttemptResult, AttemptResult.attempt_id == current["id"]), 0)

    def test_g5_lif_02_no_attempt_while_regenerating(self) -> None:
        quiz = self.ready_quiz([self.doc_cells])
        self.regenerate(quiz["id"])
        response = self.start(quiz["id"])
        self.assertEqual((response.status_code, response.json()["type"]), (409, "about:blank#quiz_not_ready"))
        self.assertEqual(self.count(QuizAttempt), 0)

    def test_g5_lif_03_deleting_the_only_source_deletes_every_attempt(self) -> None:
        quiz = self.ready_quiz([self.doc_cells])
        submitted, current = self.attempts_of(quiz["id"])
        self.delete_doc(self.doc_cells)
        self.assertEqual(self.count(Quiz, Quiz.id == quiz["id"]), 0)
        self.gone(submitted["id"], current["id"])

    def test_g5_lif_04_invalidation_deletes_every_attempt(self) -> None:
        quiz = self.ready_quiz([self.doc_cells, self.doc_nerves])
        other = self.ready_quiz([self.doc_cells])
        submitted, current = self.attempts_of(quiz["id"])
        kept, _ = self.take(other["id"], wrong={1})
        self.delete_doc(self.doc_nerves)
        self.assertEqual(self.get_quiz(self.a, self.a_token, quiz["id"]).json()["status"], "invalid")
        self.gone(submitted["id"], current["id"])
        nerves = {w.strip(".,") for sentence in FACTS[2:] for w in sentence.split() if len(w.strip(".,")) > 8}
        with self.db() as session:
            stored = [f"{r.stem} {r.evidence} {r.options} {r.rationale}" for r in session.scalars(select(AttemptResult))]
        self.assertTrue(stored)  # the other quiz's snapshot remains ...
        self.assertEqual({w for w in nerves if any(w in text for text in stored)}, set())
        self.assertEqual(self.count(QuizAttempt, QuizAttempt.id == kept["id"]), 1)  # ... untouched

    def test_g5_lif_05_deleting_a_quiz_or_course_deletes_its_attempts(self) -> None:
        quiz = self.ready_quiz([self.doc_cells])
        kept_quiz = self.ready_quiz([self.doc_nerves])
        submitted, current = self.attempts_of(quiz["id"])
        kept, _ = self.take(kept_quiz["id"], wrong={1})
        self.assertEqual(self.a.delete(f"/api/v1/quizzes/{quiz['id']}", headers=self.bearer(self.a_token)).status_code,
                         204)
        self.gone(submitted["id"], current["id"])
        course = self.create_course(self.a_token, "Second course")
        deck = self.deck(self.a, self.a_token, course, "more.pptx")
        course_quiz = self.ready_quiz([deck], course=course)
        in_course, in_course_current = self.attempts_of(course_quiz["id"])
        self.assertEqual(self.a.delete(f"/api/v1/courses/{course}", headers=self.bearer(self.a_token)).status_code,
                         204)
        self.gone(in_course["id"], in_course_current["id"])
        self.assertEqual(self.results(kept["id"]).status_code, 200)
        self.assertEqual(self.count(AttemptResult, AttemptResult.attempt_id == kept["id"]),
                         len(kept_quiz["questions"]))

    def test_g5_lif_06_submitting_while_a_source_is_being_deleted(self) -> None:
        quiz = self.ready_quiz([self.doc_cells, self.doc_nerves])
        current = self.start_ok(quiz["id"])
        self.answer_all(current, quiz["id"])
        with self.db() as session:
            session.execute(update(Document).where(Document.id == self.doc_nerves).values(status="deleting"))
            session.commit()
        response = self.submit(current["id"])
        self.assertEqual((response.status_code, response.json()["type"]), (409, "about:blank#quiz_not_ready"))
        self.assertEqual(self.count(AttemptResult, AttemptResult.attempt_id == current["id"]), 0)
        self.assertEqual(self.attempt_row(current["id"]).status, "in_progress")  # type: ignore[union-attr]
        with self.db() as session:
            self.app.state.documents.finish_deletions(session, [self.doc_nerves])
        self.gone(current["id"])

    def test_g5_lif_07_deletions_never_touch_the_ledger(self) -> None:
        quiz = self.ready_quiz([self.doc_cells])
        both = self.ready_quiz([self.doc_cells, self.doc_nerves])
        nerves_only = self.ready_quiz([self.doc_nerves])
        for quiz_id in (quiz["id"], both["id"], nerves_only["id"]):
            self.attempts_of(quiz_id)
        before = self.ledger()
        self.assertEqual(self.a.delete(f"/api/v1/quizzes/{quiz['id']}", headers=self.bearer(self.a_token)).status_code,
                         204)
        self.delete_doc(self.doc_cells)  # T-3 for "both"
        self.delete_doc(self.doc_nerves)  # T-2 for "nerves_only"
        self.assertEqual(self.a.delete(f"/api/v1/courses/{self.a_course}",
                                       headers=self.bearer(self.a_token)).status_code, 204)
        self.assertEqual(self.count(QuizAttempt), 0)
        self.assertEqual(self.ledger(), before)


# ======================================================================================= 2.7 limits, input
class LimitTests(LifeCase):
    real_rate_limits = True

    def test_g5_abu_01_attempt_limits(self) -> None:
        quiz = self.ready_quiz([self.doc_cells, self.doc_nerves])
        b_deck = self.deck(self.b, self.b_token, self.b_course, "b.pptx")
        b_quiz = self.ready_quiz([b_deck], client=self.b, token=self.b_token, course=self.b_course)
        for _ in range(30):
            self.assertIn(self.start(quiz["id"]).status_code, (200, 201))
        with self.assertLogs("intellistudy.security", level="WARNING"):
            limited = self.start(quiz["id"])
        self.assertEqual(limited.status_code, 429)
        self.assertIn("retry-after", limited.headers)
        self.assertEqual(self.start(b_quiz["id"], self.b_token, self.b).status_code, 201)  # B unaffected
        attempt = self.a.get(f"/api/v1/quizzes/{quiz['id']}/attempts",
                             headers=self.bearer(self.a_token)).json()["items"][0]
        question_id = quiz["questions"][0]["id"]
        for n in range(600):
            self.assertEqual(self.put_answer(attempt["id"], question_id, choice=n % 4).status_code, 200)
        self.assertEqual(self.put_answer(attempt["id"], question_id, choice=0).status_code, 429)
        for _ in range(30):
            self.assertEqual(self.submit(attempt["id"]).status_code, 200)
        limited = self.submit(attempt["id"])
        self.assertEqual(limited.status_code, 429)
        self.assertIn("retry-after", limited.headers)
        self.assertEqual(self.retry(attempt["id"]).status_code, 429)  # retry shares the start limit

    def test_g5_abu_02_scope_score_and_time_fields_are_rejected(self) -> None:
        quiz = self.ready_quiz([self.doc_cells])
        attempt = self.start_ok(quiz["id"])
        question = next(q for q in attempt["questions"] if q["type"] == "mcq")
        before = self.stored_state(attempt["id"])
        forged = {"owner_id": self.b_id, "user_id": self.b_id, "quiz_id": quiz["id"], "course_id": self.b_course,
                  "score": 99, "correct": True, "started_at": "2020-01-01T00:00:00Z", "status": "submitted"}
        for field, value in forged.items():
            with self.subTest(field=field):
                self.assertEqual(self.put_answer(attempt["id"], question["id"], choice=0, **{field: value})
                                 .status_code, 422)
                for url in (f"/api/v1/quizzes/{quiz['id']}/attempts", f"/api/v1/attempts/{attempt['id']}/submit"):
                    self.assertEqual(self.a.post(url, json={field: value}, headers=self.bearer(self.a_token))
                                     .status_code, 422)
        self.assertEqual(self.stored_state(attempt["id"]), before)

    def test_g5_abu_03_submit_and_retry_take_no_body(self) -> None:
        quiz = self.ready_quiz([self.doc_cells])
        submitted, _ = self.take(quiz["id"], wrong={1})
        current = self.start_ok(quiz["id"])
        self.answer_all(current, quiz["id"])
        bodies: list[Any] = [{}, {"answers": [{"choice": 0}]}, [], "x"]
        for body in bodies:
            with self.subTest(body=body):
                headers = self.bearer(self.a_token)
                submit = (self.a.post(f"/api/v1/attempts/{current['id']}/submit", json=body, headers=headers)
                          if body != "x" else self.a.post(f"/api/v1/attempts/{current['id']}/submit", content="x",
                                                          headers=headers))
                self.assertEqual(submit.status_code, 422)
                retry = self.a.post(f"/api/v1/attempts/{submitted['id']}/retry-missed", json=body, headers=headers)
                self.assertEqual(retry.status_code, 422)
        self.assertEqual(self.attempt_row(current["id"]).status, "in_progress")  # type: ignore[union-attr]
        self.assertEqual(self.count(QuizAttempt), 2)

    def test_g5_abu_04_oversized_answer_body(self) -> None:
        quiz = self.ready_quiz([self.doc_cells])
        attempt = self.start_ok(quiz["id"])
        question = attempt["questions"][0]
        response = self.a.put(f"/api/v1/attempts/{attempt['id']}/answers/{question['id']}",
                              content=b'{"choice": 0, "pad": "' + b"x" * (70 * 1024) + b'"}',
                              headers={**self.bearer(self.a_token), "content-type": "application/json"})
        self.assertIn(response.status_code, (413, 422))
        self.assertEqual(self.count(AttemptAnswer), 0)

    def test_g5_abu_05_list_bounds(self) -> None:
        quiz = self.ready_quiz([self.doc_cells])
        url = f"/api/v1/quizzes/{quiz['id']}/attempts"
        for params in ({"limit": 0}, {"limit": 101}, {"offset": -1}):
            with self.subTest(params=params):
                self.assertEqual(self.a.get(url, params=params, headers=self.bearer(self.a_token)).status_code, 422)
