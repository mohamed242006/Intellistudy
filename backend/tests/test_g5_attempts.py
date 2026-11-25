"""M5 gate 2.1-2.3: attempt isolation, answer-key confidentiality before submission, attempt lifecycle."""

from __future__ import annotations

import ast
import json
import re
import threading
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select

from backend.app.db.models import AttemptAnswer, AttemptResult, QuizAttempt, User
from backend.app.main import create_app
from backend.tests.m1_base import NoLimiter, _quiet_json_handler
from backend.tests.m4_base import QuizModel
from backend.tests.m5_base import M5Case

ROOT = Path(__file__).resolve().parents[2]
KEY_FIELD = re.compile(r"^(correct.*|answer_key|rationale.*|evidence|is_correct)$")  # G5-SEC-07
#: in-progress attempt views also carry no source of any kind (G5-KEY-01); the quiz view's ``source_document_ids``
#: (which documents a quiz covers) is approved public quiz metadata (M4 G4-KEY-01)
ATTEMPT_FIELD = re.compile(r"^(correct.*|answer_key|rationale.*|evidence|source.*|is_correct)$")
RANDOM = "00000000-0000-4000-8000-000000000000"
MALFORMED = ("not-a-uuid", "0" * 36, "00000000-0000-4000-8000-00000000000Z")


def field_names(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {n for v in value.values() for n in field_names(v)}
    if isinstance(value, list):
        return {n for v in value for n in field_names(v)}
    return set()


class AttemptCase(M5Case):
    def setUp(self) -> None:
        super().setUp()
        self.quiz = self.ready_quiz([self.doc_cells, self.doc_nerves])
        self.qid = self.quiz["id"]

    def secrets(self, quiz_id: str) -> list[str]:
        out: list[str] = []
        for key in self.keys(quiz_id):
            out.append(key.evidence)
            out.extend(r for r in key.rationales if r)
        return out

    def assert_no_key_data(self, response: Any, quiz_id: str, pattern: re.Pattern[str] = ATTEMPT_FIELD) -> None:
        body = response.json()
        leaked = {n for n in field_names(body) if pattern.match(n)}
        self.assertEqual(leaked, set(), response.text)
        for question in body.get("questions") or []:
            self.assertNotIn("score", question)
        for secret in self.secrets(quiz_id):
            self.assertNotIn(secret, response.text)

    def every_route(self, quiz_id: str, attempt_id: str, submitted_id: str, question_id: str
                    ) -> list[tuple[str, str, dict[str, Any] | None]]:
        return [("post", f"/api/v1/quizzes/{quiz_id}/attempts", None),
                ("get", f"/api/v1/quizzes/{quiz_id}/attempts", None),
                ("get", f"/api/v1/attempts/{attempt_id}", None),
                ("put", f"/api/v1/attempts/{attempt_id}/answers/{question_id}", {"choice": 0}),
                ("post", f"/api/v1/attempts/{attempt_id}/submit", None),
                ("get", f"/api/v1/attempts/{submitted_id}/results", None),
                ("post", f"/api/v1/attempts/{submitted_id}/retry-missed", None)]

    @staticmethod
    def call(client: Any, method: str, url: str, body: Any, headers: dict[str, str]) -> Any:
        if method == "put":
            return client.put(url, json=body, headers=headers)
        return getattr(client, method)(url, headers=headers)

    def a_attempts(self) -> tuple[dict[str, Any], dict[str, Any]]:
        """A's submitted attempt (two wrong answers) and A's in-progress attempt with one saved answer."""
        submitted, _ = self.take(self.qid, wrong={1, 2})
        current = self.start_ok(self.qid)
        question = current["questions"][0]
        self.assertEqual(self.put_answer(current["id"], question["id"], **self.right(
            question, self.key_map(self.qid)[question["id"]])).status_code, 200)
        return submitted, current


# =========================================================================================== 2.1 isolation
class AttemptIsolationTests(AttemptCase):
    def check_foreign_caller(self, client: Any, token: str, owner_id: str) -> None:
        submitted, current = self.a_attempts()
        before = (self.stored_state(submitted["id"]), self.stored_state(current["id"]))
        question = current["questions"][0]["id"]
        for method, url, body in self.every_route(self.qid, current["id"], submitted["id"], question):
            with self.subTest(route=f"{method} {url}"), self.assertLogs("intellistudy.security", level="WARNING"):
                self.assert_same_404(self.call(client, method, url, body, self.bearer(token)), token)
        self.assertEqual((self.stored_state(submitted["id"]), self.stored_state(current["id"])), before)
        self.assertEqual(self.count(QuizAttempt, QuizAttempt.owner_id == owner_id), 0)

    def test_g5_ati_01_another_student_gets_the_same_404_on_every_route(self) -> None:
        self.check_foreign_caller(self.b, self.b_token, self.b_id)

    def test_g5_ati_02_an_administrator_gets_the_same_404(self) -> None:
        self.check_foreign_caller(self.c, self.c_token, self.c_id)

    def test_g5_ati_03_random_and_malformed_ids(self) -> None:
        submitted, current = self.a_attempts()
        question = current["questions"][0]["id"]
        for bad in (RANDOM, *MALFORMED):
            routes = (self.every_route(bad, current["id"], submitted["id"], question)[:2]
                      + self.every_route(self.qid, bad, bad, question)[2:]
                      + [("put", f"/api/v1/attempts/{current['id']}/answers/{bad}", {"choice": 0})])
            for method, url, body in routes:
                with self.subTest(route=f"{method} {url}"):
                    self.assert_same_404(self.call(self.a, method, url, body, self.bearer(self.a_token)),
                                         self.a_token)

    def test_g5_ati_04_question_ids_of_other_quizzes_are_rejected(self) -> None:
        b_deck = self.deck(self.b, self.b_token, self.b_course, "b.pptx")
        b_quiz = self.ready_quiz([b_deck], client=self.b, token=self.b_token, course=self.b_course)
        b_other = self.ready_quiz([b_deck], client=self.b, token=self.b_token, course=self.b_course)
        attempt = self.start_ok(b_quiz["id"], self.b_token, self.b)
        for foreign in (self.quiz["questions"][0]["id"], b_other["questions"][0]["id"]):
            with self.subTest(question=foreign):
                response = self.put_answer(attempt["id"], foreign, self.b_token, self.b, choice=0)
                self.assert_same_404(response, self.b_token)
        self.assertEqual(self.count(AttemptAnswer, AttemptAnswer.attempt_id == attempt["id"]), 0)

    def test_g5_ati_05_lists_and_views_hold_only_the_callers_attempts(self) -> None:
        b_deck = self.deck(self.b, self.b_token, self.b_course, "b.pptx")
        b_quiz = self.ready_quiz([b_deck], client=self.b, token=self.b_token, course=self.b_course)
        a_attempt, _ = self.take(self.qid)
        b_attempt = self.start_ok(b_quiz["id"], self.b_token, self.b)
        a_list = self.a.get(f"/api/v1/quizzes/{self.qid}/attempts", headers=self.bearer(self.a_token)).json()
        b_list = self.b.get(f"/api/v1/quizzes/{b_quiz['id']}/attempts", headers=self.bearer(self.b_token)).json()
        self.assertEqual([i["id"] for i in a_list["items"]], [a_attempt["id"]])
        self.assertEqual([i["id"] for i in b_list["items"]], [b_attempt["id"]])
        self.assertEqual(self.get_attempt(b_attempt["id"], self.b_token, self.b).json()["id"], b_attempt["id"])
        self.assert_same_404(self.get_attempt(b_attempt["id"]), self.a_token)

    def test_g5_ati_06_missing_expired_and_revoked_tokens(self) -> None:
        submitted, current = self.a_attempts()
        before = (self.stored_state(submitted["id"]), self.stored_state(current["id"]))
        routes = self.every_route(self.qid, current["id"], submitted["id"], current["questions"][1]["id"])
        for method, url, body in routes:
            with self.subTest(case="no token", route=url):
                self.assert_generic_401(self.call(self.a, method, url, body, {}))
        self.clock.advance(minutes=16)
        for method, url, body in routes:
            with self.subTest(case="expired", route=url):
                self.assert_generic_401(self.call(self.a, method, url, body, self.bearer(self.a_token)))
        token = self.login(self.a, "a@example.org")
        self.clock.advance(seconds=1)  # revocation compares issue times exactly (JWT-05), as in G1-JWT-13
        self.assertEqual(self.a.post("/api/v1/auth/logout-all", headers=self.bearer(token)).status_code, 204)
        for method, url, body in routes:
            with self.subTest(case="revoked", route=url):
                self.assert_generic_401(self.call(self.a, method, url, body, self.bearer(token)))
        self.assertEqual((self.stored_state(submitted["id"]), self.stored_state(current["id"])), before)


# ================================================================================ 2.2 key confidentiality
class KeyConfidentialityTests(AttemptCase):
    def test_g5_key_01_in_progress_views_carry_no_key_data(self) -> None:
        start = self.start(self.qid)
        self.assertEqual(start.status_code, 201)
        attempt = start.json()
        for n, question in enumerate(attempt["questions"]):
            key = self.key_map(self.qid)[question["id"]]
            body = self.right(question, key) if n % 2 else self.wrong(question, key)
            self.assert_no_key_data(self.put_answer(attempt["id"], question["id"], **body), self.qid)
        responses = [start, self.start(self.qid), self.get_attempt(attempt["id"]),
                     self.a.get(f"/api/v1/quizzes/{self.qid}/attempts", headers=self.bearer(self.a_token))]
        for response in responses:
            with self.subTest(url=str(response.url)):
                self.assertIn(response.status_code, (200, 201), response.text)
                self.assert_no_key_data(response, self.qid)
        self.assertIsNone(self.get_attempt(attempt["id"]).json()["score"])

    def test_g5_key_02_saving_reveals_nothing_about_correctness(self) -> None:
        attempt = self.start_ok(self.qid)
        keys = self.key_map(self.qid)
        for question in attempt["questions"][:2]:  # one multiple choice, one true/false
            key = keys[question["id"]]
            right = self.put_answer(attempt["id"], question["id"], **self.right(question, key))
            view_right = self.get_attempt(attempt["id"]).json()
            wrong = self.put_answer(attempt["id"], question["id"], **self.wrong(question, key))
            view_wrong = self.get_attempt(attempt["id"]).json()
            with self.subTest(type=question["type"]):
                self.assertEqual((right.status_code, wrong.status_code), (200, 200))
                self.assertEqual(set(right.json()), {"question_id", "answer", "saved_at"})
                self.assertEqual(set(right.json()), set(wrong.json()))
                self.assertEqual(right.headers.get("content-type"), wrong.headers.get("content-type"))
                for view in (view_right, view_wrong):
                    self.assertIsNone(view["score"])
                self.assertEqual({k: v for k, v in view_right.items() if k != "answers"},
                                 {k: v for k, v in view_wrong.items() if k != "answers"})

    def test_g5_key_03_results_of_unsubmitted_attempts_are_refused(self) -> None:
        attempt = self.start_ok(self.qid)
        response = self.results(attempt["id"])
        self.assertEqual((response.status_code, response.json()["type"]), (409, "about:blank#attempt_not_submitted"))
        self.assert_no_key_data(response, self.qid)
        self.regenerate(self.qid)
        self.generate()
        response = self.results(attempt["id"])
        self.assertEqual((response.status_code, response.json()["type"]), (409, "about:blank#attempt_expired"))
        self.assertNotIn("evidence", response.text)

    def test_g5_key_04_keys_appear_only_in_that_attempts_results(self) -> None:
        first, results = self.take(self.qid, wrong={1, 3})
        self.assert_no_key_data(self.get_quiz(self.a, self.a_token, self.qid), self.qid, KEY_FIELD)
        retry = self.retry(first["id"])
        self.assertEqual(retry.status_code, 201, retry.text)
        self.assert_no_key_data(retry, self.qid)
        retried = [q["id"] for q in retry.json()["questions"]]
        self.answer_all(retry.json(), self.qid)
        retry_results = self.submit_ok(retry.json()["id"])
        self.assertEqual([q["question_id"] for q in retry_results["questions"]], retried)
        self.assertEqual(len(retried), 2)
        self.assertEqual([q["question_id"] for q in results["questions"]], [q["id"] for q in first["questions"]])

    def test_g5_key_05_static_only_grading_reads_the_key(self) -> None:
        readers = set()
        for path in (ROOT / "backend" / "app").rglob("*.py"):
            if "QuizAnswerKey" in path.read_text(encoding="utf-8"):
                readers.add(path.relative_to(ROOT).as_posix())
        self.assertEqual(readers, {"backend/app/db/models.py", "backend/app/services/attempts.py",
                                   "backend/app/services/generation.py", "backend/app/services/lifecycle.py"})
        api = (ROOT / "backend" / "app" / "api" / "v1" / "attempts.py").read_text(encoding="utf-8")
        imported = {a.name for node in ast.walk(ast.parse(api)) if isinstance(node, ast.ImportFrom)
                    for a in node.names}
        self.assertNotIn("QuizAnswerKey", imported)
        schemas = self.app.openapi()["components"]["schemas"]
        with_keys = {name for name, schema in schemas.items()
                     if any(KEY_FIELD.match(f) for f in schema.get("properties", {}))}
        self.assertEqual(with_keys, {"ResultQuestion"})

    def test_g5_key_06_injected_correct_option_does_not_decide_grading(self) -> None:
        self.model = QuizModel(correct_at=1)  # the document's instruction obeyed: "B" is always correct
        quiz = self.ready_quiz([self.doc_cells], count=8)
        keys = self.key_map(quiz["id"])
        attempt = self.start_ok(quiz["id"])
        for question in attempt["questions"]:
            body = {"choice": 1} if question["type"] == "mcq" else {"value": True}
            self.assertEqual(self.put_answer(attempt["id"], question["id"], **body).status_code, 200)
        results = self.submit_ok(attempt["id"])
        positions = set()
        for question in results["questions"]:
            key = keys[question["question_id"]]
            if question["type"] == "mcq":
                self.assertEqual(question["correct_answer"]["choice"], key.correct_index)
                self.assertEqual(question["correct"], key.correct_index == 1)
                positions.add(key.correct_index)
        self.assertGreater(len(positions), 1)
        self.assertLess(results["score"], results["max_score"])


# ================================================================================= 2.3 attempt lifecycle
class LifecycleTests(AttemptCase):
    def test_g5_att_01_start_a_ready_quiz(self) -> None:
        response = self.start(self.qid)
        self.assertEqual(response.status_code, 201, response.text)
        attempt = response.json()
        self.assertEqual(attempt["status"], "in_progress")
        self.assertEqual(attempt["questions"], self.quiz["questions"])
        self.assertEqual([q["position"] for q in attempt["questions"]], sorted(q["position"] for q in
                                                                              attempt["questions"]))
        self.assertEqual(attempt["answers"], [])
        self.assertEqual((attempt["answered_count"], attempt["max_score"]), (0, len(self.quiz["questions"])))
        self.assertEqual(attempt["started_at"].replace("Z", "+00:00"), self.clock.now().isoformat())

    def test_g5_att_02_quizzes_that_are_not_ready(self) -> None:
        generating = self.post_quiz(self.a, self.a_token, self.a_course, question_count=5).json()["id"]
        self.assertEqual(self.start(generating).json()["type"], "about:blank#quiz_not_ready")
        self.generate()
        self.use(lambda messages: "not json")
        failed = self.post_quiz(self.a, self.a_token, self.a_course, question_count=5).json()["id"]
        self.generate()
        self.assertEqual(self.get_quiz(self.a, self.a_token, failed).json()["status"], "failed")
        self.assertEqual(self.a.delete(f"/api/v1/documents/{self.doc_nerves}",
                                       headers=self.bearer(self.a_token)).status_code, 204)
        self.assertEqual(self.get_quiz(self.a, self.a_token, self.qid).json()["status"], "invalid")
        for quiz_id in (failed, self.qid):
            response = self.start(quiz_id)
            with self.subTest(quiz=quiz_id):
                self.assertEqual((response.status_code, response.json()["type"]),
                                 (409, "about:blank#quiz_not_ready"))
        self.assertEqual(self.count(QuizAttempt), 0)

    def test_g5_att_03_starting_again_resumes(self) -> None:
        first = self.start(self.qid)
        self.assertEqual(first.status_code, 201)
        attempt = first.json()
        question = attempt["questions"][0]
        self.put_answer(attempt["id"], question["id"], **self.right(question, self.key_map(self.qid)[question["id"]]))
        again = self.start(self.qid)
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.json()["id"], attempt["id"])
        self.assertEqual([a["question_id"] for a in again.json()["answers"]], [question["id"]])
        self.submit_ok(attempt["id"])
        fresh = self.start(self.qid)
        self.assertEqual(fresh.status_code, 201)
        self.assertNotEqual(fresh.json()["id"], attempt["id"])

    def test_g5_att_04_answers_are_saved_at_once_and_survive_a_restart(self) -> None:
        attempt = self.start_ok(self.qid)
        keys = self.key_map(self.qid)
        q1, q2 = attempt["questions"][:2]
        self.put_answer(attempt["id"], q1["id"], **self.wrong(q1, keys[q1["id"]]))
        self.put_answer(attempt["id"], q2["id"], **self.right(q2, keys[q2["id"]]))
        self.put_answer(attempt["id"], q1["id"], **self.right(q1, keys[q1["id"]]))  # overwrite
        with self.db() as session:
            stored = {a.question_id: (a.choice, a.value) for a in session.scalars(
                select(AttemptAnswer).where(AttemptAnswer.attempt_id == attempt["id"]))}
        self.assertEqual(stored[q1["id"]], tuple(self.right(q1, keys[q1["id"]]).get(k) for k in ("choice", "value")))
        restarted = create_app(self.settings, rate_limiter=NoLimiter(), clock=self.clock, ai=self.app.state.ai)
        _quiet_json_handler()
        self.app = restarted
        view = self.get_attempt(attempt["id"], client=self.client()).json()
        answers = {a["question_id"]: a["answer"] for a in view["answers"]}
        self.assertEqual(set(answers), {q1["id"], q2["id"]})
        expected = self.right(q1, keys[q1["id"]])
        self.assertEqual({k: v for k, v in answers[q1["id"]].items() if v is not None}, expected)

    def test_g5_att_05_malformed_answers(self) -> None:
        attempt = self.start_ok(self.qid)
        mcq = next(q for q in attempt["questions"] if q["type"] == "mcq")
        tf = next(q for q in attempt["questions"] if q["type"] == "true_false")
        cases: list[tuple[dict[str, Any], dict[str, Any]]] = [(mcq, {"choice": -1}), (mcq, {"choice": 4}), (mcq, {"choice": True}), (mcq, {"choice": "1"}),
                 (mcq, {"choice": 1.0}), (mcq, {"value": True}), (mcq, {"choice": 1, "value": True}), (mcq, {}),
                 (mcq, {"choice": 1, "owner_id": self.a_id}), (tf, {"choice": 0}), (tf, {"value": "true"}),
                 (tf, {"value": 1}), (tf, {"choice": 0, "value": False}), (tf, {"value": None})]
        for question, body in cases:
            with self.subTest(type=question["type"], body=json.dumps(body)):
                self.assertEqual(self.put_answer(attempt["id"], question["id"], **body).status_code, 422)
        self.assertEqual(self.count(AttemptAnswer, AttemptAnswer.attempt_id == attempt["id"]), 0)

    def test_g5_att_06_questions_outside_the_attempt(self) -> None:
        first, _ = self.take(self.qid, wrong={1})
        retry = self.retry(first["id"]).json()
        outside = next(q["id"] for q in self.quiz["questions"] if q["id"] not in {r["id"] for r in retry["questions"]})
        other = self.ready_quiz([self.doc_cells])
        for question_id in (outside, other["questions"][0]["id"]):
            with self.subTest(question=question_id):
                self.assert_same_404(self.put_answer(retry["id"], question_id, choice=0), self.a_token)
        self.assertEqual(self.count(AttemptAnswer, AttemptAnswer.attempt_id == retry["id"]), 0)

    def test_g5_att_07_submitted_attempts_are_immutable(self) -> None:
        attempt, results = self.take(self.qid, wrong={1, 2}, skip={3})
        before = self.stored_state(attempt["id"])
        question = attempt["questions"][0]
        saved = self.put_answer(attempt["id"], question["id"], **self.right(
            question, self.key_map(self.qid)[question["id"]]))
        self.assertEqual((saved.status_code, saved.json()["type"]), (409, "about:blank#attempt_submitted"))
        self.assertEqual(self.submit(attempt["id"]).json(), results)
        retry = self.retry(attempt["id"])
        self.assertEqual(retry.status_code, 201, retry.text)
        self.assertNotEqual(retry.json()["id"], attempt["id"])
        self.answer_all(retry.json(), self.qid)
        self.submit_ok(retry.json()["id"])
        racing = self.start_ok(self.qid)  # a save that passed its status check while the submission commits
        self.answer_all(racing, self.qid)
        service, case = self.app.state.attempts, self

        class SubmitDuringSave:
            fired = False

            def hit(self, limit: Any, key: str) -> float:
                if limit.scope == "attempt:answer" and not self.fired:
                    self.fired = True
                    with case.db() as session:
                        user = session.scalars(select(User).where(User.id == case.a_id)).one()
                        service.submit(session, user, racing["id"])
                return 0.0

        service._limiter = SubmitDuringSave()
        late = self.put_answer(racing["id"], racing["questions"][0]["id"], **self.wrong(
            racing["questions"][0], self.key_map(self.qid)[racing["questions"][0]["id"]]))
        self.assertEqual((late.status_code, late.json()["type"]), (409, "about:blank#attempt_submitted"))
        submitted_racing = self.stored_state(racing["id"])
        self.assertEqual(submitted_racing["status"], "submitted")
        self.assertEqual(self.results(racing["id"]).json()["score"], len(racing["questions"]))
        self.regenerate(self.qid)
        self.generate()
        self.assertEqual(self.stored_state(attempt["id"]), before)
        self.assertEqual(self.stored_state(racing["id"]), submitted_racing)
        self.assertEqual(self.results(attempt["id"]).json(), results)

    def test_g5_att_08_double_and_racing_submissions_grade_once(self) -> None:
        attempt, results = self.take(self.qid, wrong={2})
        self.assertEqual(self.submit_ok(attempt["id"]), results)
        self.assertEqual(self.count(AttemptResult, AttemptResult.attempt_id == attempt["id"]), len(results["questions"]))
        racing = self.start_ok(self.qid)
        self.answer_all(racing, self.qid, wrong={1})
        clients = [self.client("10.0.0.21"), self.client("10.0.0.22")]
        outcomes: list[Any] = [None, None]
        barrier = threading.Barrier(2)

        def run(i: int) -> None:
            barrier.wait()
            outcomes[i] = self.submit(racing["id"], client=clients[i])

        threads = [threading.Thread(target=run, args=(i,)) for i in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        self.assertEqual([o.status_code for o in outcomes], [200, 200], [o.text for o in outcomes])
        self.assertEqual(outcomes[0].json(), outcomes[1].json())
        self.assertEqual(self.count(AttemptResult, AttemptResult.attempt_id == racing["id"]),
                         len(racing["questions"]))

    def test_g5_att_09_list_own_attempts(self) -> None:
        submitted, _ = self.take(self.qid, wrong={1})
        self.clock.advance(seconds=60)
        expiring = self.start_ok(self.qid)
        self.regenerate(self.qid)
        self.generate()
        self.clock.advance(seconds=60)
        current = self.start_ok(self.qid)
        url = f"/api/v1/quizzes/{self.qid}/attempts"
        items = self.a.get(url, headers=self.bearer(self.a_token)).json()["items"]
        self.assertEqual([(i["id"], i["status"]) for i in items], [(current["id"], "in_progress"),
                                                                    (expiring["id"], "expired"),
                                                                    (submitted["id"], "submitted")])
        self.assertEqual([i["score"] is not None for i in items], [False, False, True])
        page = self.a.get(url, params={"limit": 1, "offset": 1}, headers=self.bearer(self.a_token)).json()
        self.assertEqual(([i["id"] for i in page["items"]], page["limit"], page["offset"]), ([expiring["id"]], 1, 1))

    def test_g5_att_10_attempt_view_by_status(self) -> None:
        submitted, results = self.take(self.qid, wrong={1})
        expiring = self.start_ok(self.qid)
        self.regenerate(self.qid)
        self.generate()
        current = self.start_ok(self.qid)
        q = current["questions"][0]
        self.put_answer(current["id"], q["id"], **self.right(q, self.key_map(self.qid)[q["id"]]))
        views = {name: self.get_attempt(a["id"]).json() for name, a in
                 (("in_progress", current), ("submitted", submitted), ("expired", expiring))}
        self.assertEqual(len(views["in_progress"]["questions"]), len(current["questions"]))
        self.assertEqual([a["question_id"] for a in views["in_progress"]["answers"]], [q["id"]])
        self.assertEqual((views["submitted"]["questions"], views["submitted"]["answers"]), (None, None))
        self.assertEqual((views["submitted"]["score"], views["submitted"]["submitted_at"] is not None),
                         (results["score"], True))
        self.assertEqual((views["expired"]["status"], views["expired"]["expired_reason"]),
                         ("expired", "quiz_regenerated"))
        self.assertEqual((views["expired"]["questions"], views["expired"]["score"]), (None, None))
        self.assertTrue(all(uuid.UUID(v["id"]) for v in views.values()))
