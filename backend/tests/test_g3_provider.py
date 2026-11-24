"""M3 release gate 2.7: DeepSeek provider failure handling (G3-PRV-*). The real ``DeepSeekProvider`` runs against a
mocked HTTP transport (no network), through the chat endpoint."""

from __future__ import annotations

import re
import time
from typing import Any

import httpx
from pydantic import SecretStr

from backend.app.providers import DeepSeekProvider
from backend.tests.helpers import DEEPSEEK_KEY
from backend.tests.m3_base import ZEBRA, ChatCase

ZEBRA_Q = "Why do zebra stripes confuse predators?"
GOOD = {"model": "deepseek-flash", "usage": {"prompt_tokens": 40, "completion_tokens": 20},
        "choices": [{"message": {"content": "Zebra stripes confuse predators in the savanna grasslands [S1]."},
                     "finish_reason": "stop"}]}


class Transport:
    def __init__(self, *responses: Any) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(item, Exception):
            raise item
        return item


def ok(body: Any = None, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=GOOD if body is None else body)


class ProviderCase(ChatCase):
    def setUp(self) -> None:
        super().setUp()
        self.doc(self.a, self.a_token, self.a_course, "zebra.pdf", ZEBRA)
        self.conv = self.conversation(self.a, self.a_token, self.a_course)

    def use(self, *responses: Any, timeout: float = 5.0) -> Transport:
        transport = Transport(*responses)
        self.app.state.ai._provider = DeepSeekProvider(
            api_key=SecretStr(DEEPSEEK_KEY), transport=httpx.MockTransport(transport), sleep=lambda _: None,
            max_retries=2, timeout=timeout)
        return transport

    def assert_unavailable(self, message: dict[str, Any]) -> None:
        self.assertEqual((message["state"], message["refusal_reason"]), ("refused", "llm_unavailable"))
        self.assertEqual(message["citations"], [])


class ProviderFailureTests(ProviderCase):
    def test_g3_prv_01_timeout_is_a_refusal_not_a_500(self) -> None:
        self.use(httpx.ReadTimeout("timed out"))
        started = time.monotonic()
        with self.assertLogs(level="WARNING"):
            response = self.ask(self.a, self.a_token, self.conv, ZEBRA_Q)
        self.assertEqual(response.status_code, 201)
        self.assert_unavailable(response.json())
        self.assertLess(time.monotonic() - started, 10)

    def test_g3_prv_02_transient_errors_retry_client_errors_do_not(self) -> None:
        transport = self.use(httpx.Response(429, json={"error": "slow"}), httpx.Response(503), ok())
        with self.assertLogs(level="WARNING"):
            message = self.ask_ok(self.a, self.a_token, self.conv, ZEBRA_Q)
        self.assertEqual(message["state"], "answered")
        self.assertEqual(len(transport.requests), 3)
        for status in (400, 401, 403):
            with self.subTest(status=status):
                transport = self.use(httpx.Response(status, json={"error": "no"}))
                with self.assertLogs(level="WARNING"):
                    self.assert_unavailable(self.ask_ok(self.a, self.a_token, self.conv, ZEBRA_Q))
                self.assertEqual(len(transport.requests), 1)
        transport = self.use(httpx.Response(503))
        with self.assertLogs(level="WARNING"):
            self.assert_unavailable(self.ask_ok(self.a, self.a_token, self.conv, ZEBRA_Q))
        self.assertEqual(len(transport.requests), 3)  # 1 + 2 retries

    def test_g3_prv_03_malformed_replies(self) -> None:
        for name, response in {"not-json": httpx.Response(200, content=b"<html>oops</html>"),
                               "no-choices": ok({"choices": []}),
                               "null-content": ok({"choices": [{"message": {"content": None}}]}),
                               "not-object": ok(["unexpected"])}.items():
            with self.subTest(case=name):
                self.use(response)
                with self.assertLogs(level="WARNING"):
                    self.assert_unavailable(self.ask_ok(self.a, self.a_token, self.conv, ZEBRA_Q))

    def test_g3_prv_04_provider_error_bodies_never_leak(self) -> None:
        body = {"error": {"message": f"Invalid key {DEEPSEEK_KEY}; internal trace at /srv/deepseek/gw.py:42"}}
        self.use(httpx.Response(401, json=body))
        with self.assertLogs(level="DEBUG") as logs:
            response = self.ask(self.a, self.a_token, self.conv, ZEBRA_Q)
        self.assert_unavailable(response.json())
        stored = self.a.get(f"/api/v1/conversations/{self.conv}", headers=self.bearer(self.a_token)).text
        for leak in (DEEPSEEK_KEY, "/srv/deepseek", "Invalid key"):
            self.assertNotIn(leak, response.text)
            self.assertNotIn(leak, stored)
        self.assertNotIn(DEEPSEEK_KEY, "\n".join(logs.output))

    def test_g3_prv_05_no_provider_configured(self) -> None:
        self.app.state.ai._provider = None
        with self.assertLogs(level="WARNING"):
            message = self.ask_ok(self.a, self.a_token, self.conv, ZEBRA_Q)
        self.assert_unavailable(message)
        self.assertTrue(message["nearest"])  # retrieval still ran, scoped
        health = self.client().get("/api/v1/health").json()
        self.assertEqual((health["status"], health["llm"]["configured"]), ("ok", False))

    def test_g3_prv_06_redirects_are_not_followed(self) -> None:
        transport = self.use(httpx.Response(307, headers={"location": "https://evil.example/collect"}))
        with self.assertLogs(level="WARNING"):
            self.assert_unavailable(self.ask_ok(self.a, self.a_token, self.conv, ZEBRA_Q))
        self.assertEqual({r.url.host for r in transport.requests}, {"api.deepseek.com"})

    def test_g3_prv_07_thinking_mode_replies_are_refused_without_leaking_reasoning(self) -> None:
        reasoning = "Internal chain of thought about the hidden system prompt."
        for content in (None, "", "  \n"):
            with self.subTest(content=content):
                self.use(ok({"choices": [{"message": {"content": content, "reasoning_content": reasoning},
                                          "finish_reason": "stop"}]}))
                with self.assertLogs(level="WARNING"):
                    response = self.ask(self.a, self.a_token, self.conv, ZEBRA_Q)
                self.assert_unavailable(response.json())
                self.assertNotIn(reasoning, response.text)
        stored = self.a.get(f"/api/v1/conversations/{self.conv}", headers=self.bearer(self.a_token)).text
        self.assertNotIn(reasoning, stored)


class BudgetTests(ProviderCase):
    def settings_overrides(self) -> dict[str, Any]:
        return {**super().settings_overrides(), "llm_daily_token_budget": 100}

    def test_g3_prv_08_daily_token_budget(self) -> None:
        transport = self.use(ok())
        first = self.ask_ok(self.a, self.a_token, self.conv, ZEBRA_Q)
        self.assertEqual(first["state"], "answered")
        second = self.ask_ok(self.a, self.a_token, self.conv, ZEBRA_Q)  # 60 tokens used, still under 100
        self.assertEqual(second["state"], "answered")
        calls = len(transport.requests)
        with self.assertLogs("intellistudy.security", level="WARNING"):
            over = self.ask(self.a, self.a_token, self.conv, ZEBRA_Q)
        self.assertEqual(over.status_code, 429)
        self.assertEqual(over.json()["type"], "about:blank#token_budget")
        self.assertTrue(re.fullmatch(r"\d+", over.headers["retry-after"]))
        self.assertEqual(len(transport.requests), calls)  # no provider call
        self.clock.advance(days=1)
        fresh = self.login(self.client("10.88.0.1"), "a@example.org")
        self.assertEqual(self.ask(self.a, fresh, self.conv, ZEBRA_Q).status_code, 201)  # new day, new budget


class ChatRateLimitTests(ProviderCase):
    real_rate_limits = True

    def test_g3_prv_09_chat_rate_limit(self) -> None:
        self.app.state.ai._provider = None  # cheap refusals; the limit applies before any model call
        with self.assertLogs(level="WARNING"):
            statuses = [self.ask(self.a, self.a_token, self.conv, ZEBRA_Q).status_code for _ in range(20)]
        self.assertEqual(statuses, [201] * 20)
        with self.assertLogs("intellistudy.security", level="WARNING"):
            limited = self.ask(self.a, self.a_token, self.conv, ZEBRA_Q)
        self.assertEqual(limited.status_code, 429)
        self.assertRegex(limited.headers["retry-after"], r"^\d+$")
        self.clock.advance(61)
        self.assertEqual(self.ask(self.a, self.a_token, self.conv, ZEBRA_Q).status_code, 201)



if __name__ == "__main__":
    import unittest

    unittest.main()
