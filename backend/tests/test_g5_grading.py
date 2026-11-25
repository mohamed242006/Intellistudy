"""M5 gate 2.4-2.5: grading and results, retry of missed questions."""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import update

from backend.app.db.models import LlmUsage, QuizAttempt, QuizQuestion
from backend.tests.m5_base import M5Case

SYLLABLES = ("ka", "lo", "mi", "ne", "ru", "ta", "vo", "zi", "pe", "su", "do", "fa")


def word(n: int) -> str:
    return "".join(SYLLABLES[(n // 12 ** i) % 12] for i in range(3)) + "x"


def many_sentences(count: int) -> list[str]:
    """``count`` sentences with disjoint vocabulary, so no two generated questions are near-duplicates."""
    return [f"The {word(3 * i)} regulates {word(3 * i + 1)} within {word(3 * i + 2)} tissue." for i in range(count)]


class GradingCase(M5Case):
    def setUp(self) -> None:
        super().setUp()
        self.quiz = self.ready_quiz([self.doc_cells, self.doc_nerves])
        self.qid = self.quiz["id"]

    def answer_with(self, attempt: dict[str, Any], choose: Any) -> None:
        for question in attempt["questions"]:
            body = choose(question)
            if body is not None:
                self.assertEqual(self.put_answer(attempt["id"], question["id"], **body).status_code, 200)


# ============================================================================================ 2.4 grading
class GradingTests(GradingCase):
    def test_g5_grd_01_multiple_choice_at_every_position(self) -> None:
        keys = self.key_map(self.qid)
        mcqs = [q for q in self.quiz["questions"] if q["type"] == "mcq"]
        self.assertEqual({keys[q["id"]].correct_index for q in mcqs}, {0, 1, 2, 3})
        for choice in range(4):
            attempt = self.start_ok(self.qid)
            self.answer_with(attempt, lambda q, c=choice: {"choice": c} if q["type"] == "mcq" else None)
            results = {r["question_id"]: r for r in self.submit_ok(attempt["id"])["questions"]}
            for question in mcqs:
                with self.subTest(choice=choice, key=keys[question["id"]].correct_index):
                    result = results[question["id"]]
                    self.assertEqual(result["correct"], keys[question["id"]].correct_index == choice)
                    self.assertEqual(result["correct_answer"]["choice"], keys[question["id"]].correct_index)
                    self.assertEqual(result["answer"]["choice"], choice)

    def test_g5_grd_02_true_false_both_keys(self) -> None:
        keys = self.key_map(self.qid)
        tfs = [q for q in self.quiz["questions"] if q["type"] == "true_false"]
        self.assertEqual({keys[q["id"]].correct_bool for q in tfs}, {True, False})
        for value in (True, False):
            attempt = self.start_ok(self.qid)
            self.answer_with(attempt, lambda q, v=value: {"value": v} if q["type"] == "true_false" else None)
            results = {r["question_id"]: r for r in self.submit_ok(attempt["id"])["questions"]}
            for question in tfs:
                with self.subTest(value=value, key=keys[question["id"]].correct_bool):
                    self.assertEqual(results[question["id"]]["correct"], keys[question["id"]].correct_bool is value)
                    self.assertEqual(results[question["id"]]["correct_answer"]["value"],
                                     keys[question["id"]].correct_bool)

    def test_g5_grd_03_unanswered_questions(self) -> None:
        attempt, results = self.take(self.qid, skip={1, 2})
        keys = self.key_map(self.qid)
        skipped = [r for r in results["questions"] if r["position"] in (1, 2)]
        for result in skipped:
            key = keys[result["question_id"]]
            with self.subTest(position=result["position"]):
                self.assertEqual((result["answered"], result["answer"], result["correct"]), (False, None, False))
                expected = (key.correct_index if result["type"] == "mcq" else key.correct_bool)
                self.assertEqual(result["correct_answer"]["choice" if result["type"] == "mcq" else "value"], expected)
                self.assertEqual(result["evidence"], key.evidence)
                self.assertIsNotNone(result["citation"])
        self.assertEqual((results["score"], results["max_score"]), (len(attempt["questions"]) - 2,
                                                                     len(attempt["questions"])))

    def test_g5_grd_04_totals_topics_and_time(self) -> None:
        ids = [q["id"] for q in self.quiz["questions"]]
        with self.db() as session:
            session.execute(update(QuizQuestion).where(QuizQuestion.id.in_(ids[:2])).values(topic="Cell biology"))
            session.execute(update(QuizQuestion).where(QuizQuestion.id == ids[2]).values(topic="  cell   BIOLOGY "))
            session.execute(update(QuizQuestion).where(QuizQuestion.id.in_(ids[3:])).values(topic="Neurons"))
            session.commit()
        attempt = self.start_ok(self.qid)
        self.clock.advance(seconds=125)
        self.answer_all(attempt, self.qid, wrong={1, 4})
        results = self.submit_ok(attempt["id"])
        self.assertEqual((results["score"], results["max_score"], results["percent"]), (6, 8, 75.0))
        self.assertEqual(results["topics"], [{"topic": "Cell biology", "score": 2, "max_score": 3},
                                             {"topic": "Neurons", "score": 4, "max_score": 5}])
        self.assertEqual(results["time_spent_seconds"], 125)

    def test_g5_grd_05_cited_explanations_for_missed_questions(self) -> None:
        _, results = self.take(self.qid, wrong={1, 2, 3}, skip={4})
        keys = self.key_map(self.qid)
        names = {self.doc_cells: "cells.pptx", self.doc_nerves: "nerves.pptx"}
        missed = [r for r in results["questions"] if not r["correct"]]
        self.assertEqual(len(missed), 4)
        for result in missed:
            key = keys[result["question_id"]]
            with self.subTest(position=result["position"]):
                self.assertEqual(result["evidence"], key.evidence)
                citation = result["citation"]
                parent = self.parents.get_many([key.source_chunk_ids[0]], user_id=self.a_id,
                                               course_id=self.a_course)[key.source_chunk_ids[0]]
                self.assertEqual(citation["document_id"], parent.document_uid)
                self.assertIn(citation["document_id"], key.source_document_ids)
                self.assertEqual(citation["file_name"], names[citation["document_id"]])
                self.assertEqual((citation["citation_label"], citation["slide"]),
                                 (parent.citation_label, parent.slide_number))
                if result["type"] == "mcq" and key.correct_index is not None:
                    self.assertEqual(result["rationale"], key.rationales[key.correct_index])
                self.assertEqual(result["explanation_source"], "generated")

    def test_g5_grd_06_no_model_call_and_no_token_use(self) -> None:
        calls: list[int] = []
        real = self.app.state.ai._provider

        class Spy:
            model_name = "spy"

            def generate(self, *args: Any, **kwargs: Any) -> Any:
                calls.append(1)
                return real.generate(*args, **kwargs)

        usage_before = self.count(LlmUsage)

        def full_cycle() -> None:
            attempt, _ = self.take(self.qid, wrong={1})
            self.assertEqual(self.results(attempt["id"]).status_code, 200)
            self.assertEqual(self.get_attempt(attempt["id"]).status_code, 200)
            retry = self.retry(attempt["id"])
            self.assertEqual(retry.status_code, 201, retry.text)
            self.answer_all(retry.json(), self.qid)
            self.submit_ok(retry.json()["id"])

        self.app.state.ai._provider = Spy()
        full_cycle()
        self.assertEqual((calls, self.count(LlmUsage)), ([], usage_before))
        self.app.state.ai._provider = None  # no provider configured
        full_cycle()
        self.app.state.ai._provider = Spy()
        with self.db() as session:  # the day's token budget used up
            session.add(LlmUsage(owner_id=self.a_id, feature="chat", model="x", prompt_tokens=10_000_000,
                                 completion_tokens=0, created_at=self.clock.now()))
            session.commit()
        full_cycle()
        self.assertEqual((calls, self.count(LlmUsage)), ([], usage_before + 1))

    def test_g5_grd_07_save_and_grade_timing(self) -> None:
        deck = self.deck(self.a, self.a_token, self.a_course, "large.pptx",
                         [" ".join(many_sentences(40)[i:i + 5]) for i in range(0, 40, 5)])
        quiz = self.ready_quiz([deck], count=30)
        self.assertEqual(len(quiz["questions"]), 30)
        attempt = self.start_ok(quiz["id"])
        keys = self.key_map(quiz["id"])
        timings: list[float] = []
        for n in range(100):
            question = attempt["questions"][n % 30]
            body = self.right(question, keys[question["id"]])
            started = time.perf_counter()
            response = self.put_answer(attempt["id"], question["id"], **body)
            timings.append(time.perf_counter() - started)
            self.assertEqual(response.status_code, 200)
        p95 = sorted(timings)[94]
        started = time.perf_counter()
        submitted = self.submit(attempt["id"])
        submit_time = time.perf_counter() - started
        started = time.perf_counter()
        results = self.results(attempt["id"])
        results_time = time.perf_counter() - started
        self.assertEqual((submitted.status_code, results.status_code), (200, 200))
        self.assertEqual(results.json()["score"], 30)
        self.assertLess(p95, 0.3, f"answer save p95 {p95:.3f} s")
        self.assertLess(submit_time, 1.0, f"submit {submit_time:.3f} s")
        self.assertLess(results_time, 1.0, f"results {results_time:.3f} s")

    def test_g5_grd_08_results_survive_regeneration_unchanged(self) -> None:
        attempt, results = self.take(self.qid, wrong={2, 6})
        before = self.stored_state(attempt["id"])
        old_keys = {k.question_id for k in self.keys(self.qid)}
        self.regenerate(self.qid)
        self.generate()
        self.assertTrue(old_keys.isdisjoint({k.question_id for k in self.keys(self.qid)}))
        self.assertEqual(self.results(attempt["id"]).json(), results)
        self.assertEqual(self.stored_state(attempt["id"]), before)


# ============================================================================================== 2.5 retry
class RetryTests(GradingCase):
    def test_g5_rty_01_retry_takes_exactly_the_missed_questions(self) -> None:
        attempt, results = self.take(self.qid, wrong={2, 5}, skip={7})
        before = self.stored_state(attempt["id"])
        response = self.retry(attempt["id"])
        self.assertEqual(response.status_code, 201, response.text)
        retry = response.json()
        expected = [q["id"] for n, q in enumerate(attempt["questions"], start=1) if n in (2, 5, 7)]
        self.assertEqual([q["id"] for q in retry["questions"]], expected)
        self.assertEqual((retry["parent_attempt_id"], retry["status"], retry["max_score"]),
                         (attempt["id"], "in_progress", 3))
        self.assertEqual(self.stored_state(attempt["id"]), before)
        self.assertEqual(self.results(attempt["id"]).json(), results)

    def test_g5_rty_02_nothing_to_retry(self) -> None:
        attempt, _ = self.take(self.qid)
        response = self.retry(attempt["id"])
        self.assertEqual((response.status_code, response.json()["type"]), (409, "about:blank#nothing_to_retry"))
        self.assertEqual(self.count(QuizAttempt), 1)

    def test_g5_rty_03_only_submitted_attempts_can_be_retried(self) -> None:
        current = self.start_ok(self.qid)
        response = self.retry(current["id"])
        self.assertEqual((response.status_code, response.json()["type"]), (409, "about:blank#attempt_not_submitted"))
        self.regenerate(self.qid)
        self.generate()
        response = self.retry(current["id"])
        self.assertEqual((response.status_code, response.json()["type"]), (409, "about:blank#attempt_expired"))
        self.assertEqual(self.count(QuizAttempt), 1)

    def test_g5_rty_04_quiz_regenerated_since_the_attempt(self) -> None:
        attempt, _ = self.take(self.qid, wrong={1})
        self.regenerate(self.qid)
        self.generate()
        response = self.retry(attempt["id"])
        self.assertEqual((response.status_code, response.json()["type"]), (409, "about:blank#quiz_changed"))
        self.assertEqual(self.count(QuizAttempt), 1)

    def test_g5_rty_05_retry_while_an_attempt_is_in_progress(self) -> None:
        attempt, _ = self.take(self.qid, wrong={1})
        current = self.start_ok(self.qid)
        response = self.retry(attempt["id"])
        self.assertEqual((response.status_code, response.json()["type"]), (409, "about:blank#attempt_in_progress"))
        self.assertEqual(response.json()["attempt_id"], current["id"])
        self.assertEqual(self.count(QuizAttempt), 2)

    def test_g5_rty_06_a_retry_is_graded_on_its_own_questions(self) -> None:
        attempt, _ = self.take(self.qid, wrong={1, 3, 8})
        retry = self.retry(attempt["id"]).json()
        self.answer_all(retry, self.qid, wrong={2})
        results = self.submit_ok(retry["id"])
        retried = [q["id"] for q in retry["questions"]]
        self.assertEqual([q["question_id"] for q in results["questions"]], retried)
        self.assertEqual((results["score"], results["max_score"], results["parent_attempt_id"]), (2, 3, attempt["id"]))
        self.assertEqual([q["position"] for q in results["questions"]], [1, 2, 3])
