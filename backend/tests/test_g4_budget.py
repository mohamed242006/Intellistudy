"""M4 release gate 2.3 shared token budget (G4-BUD-*) and 2.4 provider failure handling (G4-PRV-*).

The real ``DeepSeekProvider`` runs over a mocked HTTP transport (no network). The transport builds valid summary, quiz
or chat replies from the prompt it receives and reports a configurable token usage, or fails on request.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

import httpx
from pydantic import SecretStr
from sqlalchemy import select, update

from ai.answering.models import Message
from backend.app.db.models import (
    GenerationJob,
    JobStatus,
    LlmUsage,
    Quiz,
    QuizAnswerKey,
    QuizQuestion,
    Summary,
)
from backend.app.providers import DeepSeekProvider
from backend.app.services import quizgen
from backend.tests.helpers import DEEPSEEK_KEY
from backend.tests.m4_base import FACTS, M4Case, QuizModel, sentences, sources_of, summary_reply

CHAT_Q = "How do mitochondria produce cellular energy?"


def chat_reply(messages: list[Message]) -> str:
    tag, text = sources_of(messages)[0]
    return f"{sentences(text)[0].rstrip('.')} [{tag}]."


class MockDeepSeek:
    """Replies by prompt kind; ``fail`` (a response or exception, or a callable returning one) overrides."""

    def __init__(self, usage: tuple[int, int] = (40, 20)) -> None:
        self.usage = usage
        self.requests: list[httpx.Request] = []
        self.quiz = QuizModel()
        self.fail: Any = None
        self.before: Callable[[int], None] | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.before is not None:
            self.before(len(self.requests))
        failure = self.fail(len(self.requests)) if callable(self.fail) else self.fail
        if isinstance(failure, Exception):
            raise failure
        if isinstance(failure, httpx.Response):
            return failure
        body = json.loads(request.content)
        messages = [Message(m["role"], m["content"]) for m in body["messages"]]
        system = messages[0].content
        if system == quizgen.SYSTEM_PROMPT:
            content = self.quiz(messages)
        elif "study summary" in system:
            content = summary_reply(messages)
        else:
            content = chat_reply(messages)
        return reply(content, self.usage)


def reply(content: Any, usage: tuple[int, int] = (40, 20)) -> httpx.Response:
    return httpx.Response(200, json={"model": "deepseek-flash", "usage": {"prompt_tokens": usage[0],
                                                                          "completion_tokens": usage[1]},
                                     "choices": [{"message": {"content": content}, "finish_reason": "stop"}]})


class ProviderCase(M4Case):
    call_usage: tuple[int, int] = (40, 20)

    def setUp(self) -> None:
        super().setUp()
        self.mock = MockDeepSeek(self.call_usage)
        self.app.state.ai._provider = DeepSeekProvider(api_key=SecretStr(DEEPSEEK_KEY),
                                                       transport=httpx.MockTransport(self.mock),
                                                       sleep=lambda _: None, max_retries=2, timeout=5.0)
        self.doc_a = self.deck(self.a, self.a_token, self.a_course, "cells.pptx")

    def chat(self, client: Any, token: str, course: str) -> Any:
        conversation = self.conversation(client, token, course)
        return self.ask(client, token, conversation, CHAT_Q)

    def assert_budget_429(self, response: Any) -> None:
        self.assertEqual(response.status_code, 429, response.text)
        self.assertEqual(response.json()["type"], "about:blank#token_budget")
        self.assertRegex(response.headers["retry-after"], r"^\d+$")


# =============================================================================================== budget
class SharedBudgetTests(ProviderCase):
    call_usage = (8000, 1000)  # 9,000 tokens per call

    def settings_overrides(self) -> dict[str, Any]:
        return {**super().settings_overrides(), "llm_daily_token_budget": 20_000}

    def test_g4_bud_01_one_budget_for_chat_summaries_and_quizzes(self) -> None:
        for _ in range(3):
            self.assertEqual(self.chat(self.a, self.a_token, self.a_course).status_code, 201)
        calls, jobs = len(self.mock.requests), self.jobs()
        with self.assertLogs("intellistudy.security", level="WARNING"):
            self.assert_budget_429(self.post_summary(self.a, self.a_token, self.doc_a))
            self.assert_budget_429(self.post_quiz(self.a, self.a_token, self.a_course, question_count=5))
        self.assertEqual((len(self.mock.requests), self.jobs()), (calls, jobs))
        doc_b = self.deck(self.b, self.b_token, self.b_course, "cells.pptx")  # the reverse order, for B
        for regenerate in (False, True, True):
            self.assertEqual(self.post_summary(self.b, self.b_token, doc_b, regenerate=regenerate).status_code, 202)
            self.generate()
        calls = len(self.mock.requests)
        with self.assertLogs("intellistudy.security", level="WARNING"):
            self.assert_budget_429(self.chat(self.b, self.b_token, self.b_course))
            self.assert_budget_429(self.post_quiz(self.b, self.b_token, self.b_course, question_count=5))
        self.assertEqual(len(self.mock.requests), calls)

    def test_g4_bud_05_per_user_and_reset_at_the_next_utc_day(self) -> None:
        for _ in range(3):
            self.chat(self.a, self.a_token, self.a_course)
        with self.assertLogs("intellistudy.security", level="WARNING"):
            self.assert_budget_429(self.post_summary(self.a, self.a_token, self.doc_a))
        doc_b = self.deck(self.b, self.b_token, self.b_course, "cells.pptx")
        self.assertEqual(self.post_summary(self.b, self.b_token, doc_b).status_code, 202)
        self.assertEqual(self.post_quiz(self.b, self.b_token, self.b_course, question_count=5).status_code, 202)
        self.assertEqual(self.chat(self.b, self.b_token, self.b_course).status_code, 201)
        self.clock.advance(days=1)
        fresh = self.login(self.client("10.90.0.1"), "a@example.org")
        self.assertEqual(self.post_summary(self.a, fresh, self.doc_a).status_code, 202)


class EstimateTests(ProviderCase):
    def settings_overrides(self) -> dict[str, Any]:
        return {**super().settings_overrides(), "llm_daily_token_budget": 5_000}

    def test_g4_bud_02_estimated_cost_above_the_remaining_budget(self) -> None:
        big = self.pdf(self.a, self.a_token, self.a_course, "big.pdf", [(f + " ") * 20 for f in FACTS])
        with self.assertLogs("intellistudy.security", level="WARNING"):
            self.assert_budget_429(self.post_summary(self.a, self.a_token, big))
        self.assertEqual((len(self.mock.requests), self.jobs(), self.count(Summary)), (0, 0, 0))
        self.assertEqual(self.post_summary(self.a, self.a_token, self.doc_a).status_code, 202)  # a small one fits


class MidJobBudgetTests(ProviderCase):
    def settings_overrides(self) -> dict[str, Any]:
        return {**super().settings_overrides(), "llm_daily_token_budget": 50_000, "summary_batch_tokens": 200}

    def test_g4_bud_03_budget_spent_elsewhere_stops_a_running_job(self) -> None:
        doc = self.deck(self.a, self.a_token, self.a_course, "long.pptx", [f"{f} {f}" for f in FACTS])
        old = self.summary_ok(self.a, self.a_token, doc)
        first_calls = len(self.mock.requests)
        self.assertGreaterEqual(first_calls, 2)

        def spend_elsewhere(n: int) -> None:
            if n == first_calls + 1:  # during the first map call of the regeneration, chat spends the rest
                with self.db() as session:
                    session.add(LlmUsage(owner_id=self.a_id, feature="chat", model="x", prompt_tokens=60_000,
                                         completion_tokens=0, created_at=self.clock.now()))
                    session.commit()

        self.mock.before = spend_elsewhere
        self.post_summary(self.a, self.a_token, doc, regenerate=True)
        with self.assertLogs("intellistudy.security", level="WARNING"):
            self.generate()
        self.assertEqual(len(self.mock.requests), first_calls + 1)  # stopped before the next call
        kept = self.get_summary(self.a, self.a_token, doc).json()
        self.assertEqual((kept["status"], kept["error_code"], kept["sections"]),
                         ("ready", "token_budget", old["sections"]))
        with self.db() as session:
            summary_rows = list(session.scalars(select(LlmUsage).where(LlmUsage.feature == "summary")))
        self.assertEqual(len(summary_rows), first_calls + 1)  # the call that ran is recorded


class NoRefundTests(ProviderCase):
    def test_g4_bud_04_deleting_content_never_refunds(self) -> None:
        conversation = self.conversation(self.a, self.a_token, self.a_course)
        self.ask_ok(self.a, self.a_token, conversation, CHAT_Q)
        self.summary_ok(self.a, self.a_token, self.doc_a)
        quiz = self.quiz_ok(self.a, self.a_token, self.a_course, question_count=5)
        spent = self.usage(self.a_id)
        self.assertGreater(spent, 0)
        steps = [
            lambda: self.a.delete(f"/api/v1/conversations/{conversation}", headers=self.bearer(self.a_token)),
            lambda: self.a.delete(f"/api/v1/quizzes/{quiz['id']}", headers=self.bearer(self.a_token)),
            lambda: self.a.delete(f"/api/v1/documents/{self.doc_a}", headers=self.bearer(self.a_token)),  # + summary
            lambda: self.a.delete(f"/api/v1/courses/{self.a_course}", headers=self.bearer(self.a_token)),
        ]
        for step in steps:
            self.assertEqual(step().status_code, 204)
            self.assertEqual(self.usage(self.a_id), spent)
        with self.db() as session:
            self.assertEqual(self.app.state.ledger.used_today(session, self.a_id), spent)
        self.assertEqual(self.count(Summary), 0)


class RateLimitTests(ProviderCase):
    real_rate_limits = True

    def test_g4_bud_06_generation_rate_limits(self) -> None:
        self.assertEqual(self.post_summary(self.a, self.a_token, self.doc_a).status_code, 202)
        self.generate()
        for _ in range(9):
            self.assertEqual(self.post_summary(self.a, self.a_token, self.doc_a, regenerate=True).status_code, 202)
            self.generate()
        self.assertEqual(self.post_summary(self.a, self.a_token, self.doc_a).status_code, 200)  # stored: not counted
        with self.assertLogs("intellistudy.security", level="WARNING"):
            limited = self.post_summary(self.a, self.a_token, self.doc_a, regenerate=True)
        self.assertEqual(limited.status_code, 429)
        self.assertRegex(limited.headers["retry-after"], r"^\d+$")
        for _ in range(5):
            self.assertEqual(self.post_quiz(self.a, self.a_token, self.a_course, question_count=5).status_code, 202)
        with self.assertLogs("intellistudy.security", level="WARNING"):
            limited = self.post_quiz(self.a, self.a_token, self.a_course, question_count=5)
        self.assertEqual(limited.status_code, 429)
        self.assertRegex(limited.headers["retry-after"], r"^\d+$")


class LedgerTests(ProviderCase):
    def test_g4_bud_07_one_row_per_call_without_content(self) -> None:
        self.ask_ok(self.a, self.a_token, self.conversation(self.a, self.a_token, self.a_course), CHAT_Q)
        self.summary_ok(self.a, self.a_token, self.doc_a)
        self.quiz_ok(self.a, self.a_token, self.a_course, question_count=5)
        self.mock.fail = reply("not json at all")  # answered by the provider, unusable for us: still counted
        self.quiz_ok(self.a, self.a_token, self.a_course, question_count=5)
        with self.db() as session:
            rows = list(session.scalars(select(LlmUsage).where(LlmUsage.owner_id == self.a_id)))
            keys = [(k.evidence, *k.rationales) for k in session.scalars(select(QuizAnswerKey))]
        self.assertEqual(len(rows), len(self.mock.requests))
        self.assertEqual({r.feature for r in rows}, {"chat", "summary", "quiz"})
        self.assertTrue(all((r.prompt_tokens, r.completion_tokens) == (40, 20) for r in rows))
        dump = " ".join(f"{r.feature} {r.model} {r.owner_id}" for r in rows)
        for text in ("Mitochondria", "Photosynthesis", *[t for k in keys for t in k if t]):
            self.assertNotIn(text, dump)


# =============================================================================================== provider
FAILURES: dict[str, Any] = {
    "timeout": httpx.ReadTimeout("timed out"),
    "503": httpx.Response(503),
    "400": httpx.Response(400, json={"error": "bad"}),
    "401": httpx.Response(401, json={"error": "no"}),
    "403": httpx.Response(403, json={"error": "no"}),
}


class ProviderFailureTests(ProviderCase):
    def test_g4_prv_01_summary_job_failures(self) -> None:
        old = self.summary_ok(self.a, self.a_token, self.doc_a)
        for name, failure in FAILURES.items():
            with self.subTest(failure=name):
                self.mock.fail = failure
                response = self.post_summary(self.a, self.a_token, self.doc_a, regenerate=True)
                self.assertEqual(response.status_code, 202)
                with self.assertLogs(level="WARNING"):
                    self.generate()
                view = self.get_summary(self.a, self.a_token, self.doc_a)
                self.assertEqual(view.status_code, 200)
                self.assertEqual((view.json()["status"], view.json()["error_code"], view.json()["sections"]),
                                 ("ready", "llm_unavailable", old["sections"]))
        self.mock.fail = None
        fresh = self.deck(self.a, self.a_token, self.a_course, "fresh.pptx", [FACTS[1]])
        self.mock.fail = httpx.Response(503)
        self.post_summary(self.a, self.a_token, fresh)
        with self.assertLogs(level="WARNING"):
            self.generate()
        failed = self.get_summary(self.a, self.a_token, fresh).json()
        self.assertEqual((failed["status"], failed["sections"]), ("failed", []))
        self.assertEqual(self.count(Summary, Summary.document_id == fresh), 0)

    def test_g4_prv_02_quiz_job_failures(self) -> None:
        for name, failure in FAILURES.items():
            with self.subTest(failure=name):
                self.mock.fail = failure
                with self.assertLogs(level="WARNING"):
                    quiz = self.quiz_ok(self.a, self.a_token, self.a_course, question_count=5)
                self.assertEqual((quiz["status"], quiz["error_code"], quiz["questions"]),
                                 ("failed", "llm_unavailable", []))
                self.assertEqual(self.keys(quiz["id"]), [])
                self.assertEqual(self.questions(quiz["id"]), [])

    def test_g4_prv_03_a_failed_map_call_fails_the_whole_summary(self) -> None:
        self.app.state.settings.summary_batch_tokens = 200
        doc = self.deck(self.a, self.a_token, self.a_course, "long.pptx", [f"{f} {f}" for f in FACTS])
        self.mock.fail = lambda n: httpx.Response(503) if n >= 2 else None  # first map call works, then failure
        self.post_summary(self.a, self.a_token, doc)
        with self.assertLogs(level="WARNING"):
            self.generate()
        view = self.get_summary(self.a, self.a_token, doc).json()
        self.assertEqual((view["status"], view["error_code"], view["sections"]), ("failed", "llm_unavailable", []))
        self.assertEqual(self.count(Summary, Summary.document_id == doc), 0)
        self.assertEqual(self.count(LlmUsage, LlmUsage.feature == "summary"), 1)  # the successful call is recorded

    def test_g4_prv_04_malformed_quiz_output(self) -> None:
        good = json.loads(QuizModel()([Message("system", ""), Message("user", "Write 2 questions. <source id=\"S1\" "
                                                                                 f"file=\"x\">\n{FACTS[0]}\n</source>")]))
        cases = {"not-json": "Here are your questions!", "wrong-schema": json.dumps({"items": good["questions"]}),
                 "extra-field": json.dumps({**good, "answers": "B"}), "list": json.dumps(good["questions"])}
        planned, _ = quizgen.plan(5, self.app.state.settings.quiz_batch_questions)
        for name, content in cases.items():
            with self.subTest(case=name):
                before = len(self.mock.requests)
                self.mock.fail = reply(content)
                quiz = self.quiz_ok(self.a, self.a_token, self.a_course, question_count=5)
                self.assertEqual((quiz["status"], quiz["error_code"]), ("failed", "insufficient_material"))
                self.assertLessEqual(len(self.mock.requests) - before, planned + 1)  # at most one top-up
                self.assertEqual(self.keys(quiz["id"]), [])
        for blank in (None, "", "  "):  # thinking-only / blank: a provider failure (F-M3-04)
            with self.subTest(content=blank):
                self.mock.fail = httpx.Response(200, json={"choices": [{"message": {
                    "content": blank, "reasoning_content": "secret chain of thought"}}]})
                with self.assertLogs(level="WARNING"):
                    quiz = self.quiz_ok(self.a, self.a_token, self.a_course, question_count=5)
                self.assertEqual((quiz["status"], quiz["error_code"], quiz["questions"]),
                                 ("failed", "llm_unavailable", []))

    def test_g4_prv_05_no_provider_configured(self) -> None:
        self.summary_ok(self.a, self.a_token, self.doc_a)
        quiz = self.quiz_ok(self.a, self.a_token, self.a_course, question_count=5)
        conversation = self.conversation(self.a, self.a_token, self.a_course)
        self.ask_ok(self.a, self.a_token, conversation, CHAT_Q)
        self.app.state.ai._provider = None
        jobs = self.jobs()
        for response in (self.post_summary(self.a, self.a_token, self.doc_a, regenerate=True),
                         self.post_quiz(self.a, self.a_token, self.a_course, question_count=5),
                         self.a.post(f"/api/v1/quizzes/{quiz['id']}/regenerate", headers=self.bearer(self.a_token))):
            self.assertEqual(response.status_code, 503, response.text)
            self.assertEqual(response.json()["type"], "about:blank#llm_unavailable")
        self.assertEqual(self.jobs(), jobs)
        h = self.bearer(self.a_token)
        self.assertEqual(self.get_summary(self.a, self.a_token, self.doc_a).json()["status"], "ready")
        self.assertEqual(self.get_quiz(self.a, self.a_token, quiz["id"]).json()["status"], "ready")
        self.assertEqual(self.a.get(f"/api/v1/courses/{self.a_course}/documents", headers=h).status_code, 200)
        self.assertEqual(len(self.a.get(f"/api/v1/conversations/{conversation}", headers=h).json()["messages"]), 1)
        self.assertEqual(self.client().get("/api/v1/health").status_code, 200)

    def test_g4_prv_06_provider_error_bodies_never_leak(self) -> None:
        body = {"error": {"message": f"Invalid key {DEEPSEEK_KEY}; trace at /srv/deepseek/gw.py:42"}}
        self.mock.fail = httpx.Response(401, json=body)
        with self.assertLogs(level="DEBUG") as logs:
            responses = [self.post_summary(self.a, self.a_token, self.doc_a),
                         self.post_quiz(self.a, self.a_token, self.a_course, question_count=5)]
            self.generate()
            responses += [self.get_summary(self.a, self.a_token, self.doc_a),
                          self.get_quiz(self.a, self.a_token, responses[1].json()["id"])]
        stored = []
        with self.db() as session:
            stored += [f"{j.error_code}" for j in session.scalars(select(GenerationJob))]
            stored += [f"{q.error_code} {q.notice}" for q in session.scalars(select(Quiz))]
        for leak in (DEEPSEEK_KEY, "/srv/deepseek", "Invalid key"):
            for response in responses:
                self.assertNotIn(leak, response.text)
            self.assertNotIn(leak, " ".join(stored))
        self.assertNotIn(DEEPSEEK_KEY, "\n".join(logs.output))

    def test_g4_prv_07_interrupted_jobs_recover_cleanly(self) -> None:
        self.post_summary(self.a, self.a_token, self.doc_a)
        quiz_id = self.post_quiz(self.a, self.a_token, self.a_course, question_count=5).json()["id"]
        with self.db() as session:  # a crash left both jobs "running"
            session.execute(update(GenerationJob).values(status=JobStatus.RUNNING.value))
            session.commit()
        self.assertEqual(self.generate(), 0)  # nothing is queued, nothing half-written is visible
        during = self.get_summary(self.a, self.a_token, self.doc_a).json()
        self.assertEqual((during["status"], during["sections"]), ("generating", []))
        self.assertEqual(self.get_quiz(self.a, self.a_token, quiz_id).json()["questions"], [])
        self.assertEqual(self.app.state.generation_runner.recover(), 2)
        self.assertEqual(self.generate(), 2)
        self.assertEqual(self.get_summary(self.a, self.a_token, self.doc_a).json()["status"], "ready")
        self.assertEqual(self.get_quiz(self.a, self.a_token, quiz_id).json()["status"], "ready")
        with self.db() as session:
            states = {j.status for j in session.scalars(select(GenerationJob))}
        self.assertEqual(states, {JobStatus.DONE.value})
        self.assertTrue(self.count(QuizQuestion, QuizQuestion.quiz_id == quiz_id))


_ = re


if __name__ == "__main__":
    import unittest

    unittest.main()
