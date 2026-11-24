"""Provider contract tests (no network): request shape per provider, retries, error handling and key redaction
(contract SEC-01, SEC-06, SEC-07; matrix S-04)."""

from __future__ import annotations

import json
import logging
import os
import unittest
from unittest import mock

import httpx
from pydantic import SecretStr

from ai.answering.llm import LLMClient, LLMError
from ai.answering.models import Message
from backend.app.providers import (
    DeepSeekProvider,
    FutureLocalProvider,
    LLMProvider,
    LocalProvider,
    OpenAIProvider,
    build_provider,
)
from backend.tests.helpers import DEEPSEEK_KEY, make_settings

MESSAGES = [Message("system", "Answer from the sources."), Message("user", "What is a join point?")]
OK_REPLY = {
    "model": "deepseek-flash",
    "choices": [{"message": {"content": "A join point is ... [S1]"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 120, "completion_tokens": 12},
}


class Recorder:
    """httpx transport that records requests and replays scripted responses."""

    def __init__(self, *responses: httpx.Response | Exception) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(item, Exception):
            raise item
        return item

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)

    def body(self, index: int = -1) -> dict:
        return json.loads(self.requests[index].content)


def ok(data: dict | None = None) -> httpx.Response:
    return httpx.Response(200, json=data or OK_REPLY)


def deepseek(rec: Recorder, **kw) -> DeepSeekProvider:
    return DeepSeekProvider(api_key=SecretStr(DEEPSEEK_KEY), transport=rec.transport(), sleep=lambda _: None, **kw)


class RequestShapeTests(unittest.TestCase):
    def test_deepseek_default_is_the_validated_configuration(self) -> None:
        rec = Recorder(ok())
        reply = deepseek(rec).generate(MESSAGES, temperature=0.0, max_tokens=700)
        request = rec.requests[0]
        self.assertEqual(str(request.url), "https://api.deepseek.com/chat/completions")
        self.assertEqual(request.headers["authorization"], f"Bearer {DEEPSEEK_KEY}")
        body = rec.body()
        self.assertEqual(body["model"], "deepseek-chat")
        self.assertEqual((body["temperature"], body["max_tokens"]), (0.0, 700))
        self.assertNotIn("thinking", body)  # legacy name is already non-thinking
        self.assertEqual(body["messages"][1], {"role": "user", "content": "What is a join point?"})
        self.assertEqual((reply.text, reply.model, reply.prompt_tokens, reply.completion_tokens, reply.finish_reason),
                         ("A join point is ... [S1]", "deepseek-flash", 120, 12, "stop"))

    def test_deepseek_current_models_get_thinking_disabled(self) -> None:
        rec = Recorder(ok())
        deepseek(rec, model="deepseek-flash").generate(MESSAGES)
        self.assertEqual(rec.body()["thinking"], {"type": "disabled"})

    def test_openai_classic_model_uses_max_tokens_and_temperature(self) -> None:
        rec = Recorder(ok())
        OpenAIProvider(api_key=SecretStr("sk-test-openai-000000"), transport=rec.transport()).generate(MESSAGES)
        body = rec.body()
        self.assertEqual(str(rec.requests[0].url), "https://api.openai.com/v1/chat/completions")
        self.assertIn("max_tokens", body)
        self.assertIn("temperature", body)

    def test_openai_reasoning_models_use_max_completion_tokens_without_temperature(self) -> None:
        for model in ("gpt-6-luna", "o4-mini", "gpt-5"):
            rec = Recorder(ok())
            provider = OpenAIProvider(api_key=SecretStr("sk-test-openai-000000"), model=model, transport=rec.transport())
            provider.generate(MESSAGES, max_tokens=500)
            body = rec.body()
            self.assertEqual(body["max_completion_tokens"], 500, model)
            self.assertNotIn("max_tokens", body)
            self.assertNotIn("temperature", body)

    def test_local_provider_sends_no_authorization(self) -> None:
        rec = Recorder(ok())
        LocalProvider(api_key=None, transport=rec.transport()).generate(MESSAGES)
        self.assertNotIn("authorization", rec.requests[0].headers)
        self.assertEqual(str(rec.requests[0].url), "http://localhost:11434/v1/chat/completions")
        self.assertIs(FutureLocalProvider, LocalProvider)

    def test_base_url_must_be_absolute_http(self) -> None:
        for bad in ("api.deepseek.com", "file:///etc/passwd", "ftp://x"):
            with self.subTest(url=bad), self.assertRaises(ValueError):
                DeepSeekProvider(api_key=SecretStr(DEEPSEEK_KEY), base_url=bad)

    def test_redirects_are_not_followed(self) -> None:  # a redirect could carry the Authorization header elsewhere
        rec = Recorder(httpx.Response(302, headers={"location": "https://evil.example/collect"}))
        with self.assertRaises(LLMError), self.assertLogs(level="WARNING"):
            deepseek(rec).generate(MESSAGES)
        self.assertEqual(len(rec.requests), 1)

    def test_providers_satisfy_both_protocols(self) -> None:
        for provider in (deepseek(Recorder(ok())), LocalProvider(api_key=None)):
            self.assertIsInstance(provider, LLMProvider)
            self.assertTrue(callable(provider.generate))
            _client: LLMClient = provider  # the protocol AnswerService uses


class ErrorHandlingTests(unittest.TestCase):
    def test_transient_errors_are_retried_then_succeed(self) -> None:
        rec = Recorder(httpx.Response(429, json={"error": "slow down"}), httpx.Response(503), ok())
        with self.assertLogs("backend.app.providers.openai_compatible", level="WARNING"):
            reply = deepseek(rec, max_retries=2).generate(MESSAGES)
        self.assertEqual(len(rec.requests), 3)
        self.assertEqual(reply.text, "A join point is ... [S1]")

    def test_client_errors_are_not_retried(self) -> None:
        rec = Recorder(httpx.Response(400, json={"error": "bad request"}))
        with self.assertRaises(LLMError) as ctx, self.assertLogs(level="WARNING"):
            deepseek(rec, max_retries=2).generate(MESSAGES)
        self.assertEqual(len(rec.requests), 1)
        self.assertFalse(ctx.exception.retryable)

    def test_network_errors_are_retried_and_then_raised(self) -> None:
        rec = Recorder(httpx.ConnectError("refused"))
        with self.assertRaises(LLMError) as ctx, self.assertLogs(level="WARNING"):
            deepseek(rec, max_retries=2).generate(MESSAGES)
        self.assertEqual(len(rec.requests), 3)
        self.assertTrue(ctx.exception.retryable)

    def test_null_content_is_a_malformed_reply(self) -> None:
        rec = Recorder(ok({"choices": [{"message": {"content": None}, "finish_reason": "length"}]}))
        with self.assertRaises(LLMError):
            deepseek(rec).generate(MESSAGES)

    def test_provider_error_body_with_the_key_is_redacted_and_never_raised(self) -> None:  # S-04 / SEC-06
        body = {"error": {"message": f"Invalid key {DEEPSEEK_KEY} for Authorization: Bearer {DEEPSEEK_KEY}"}}
        rec = Recorder(httpx.Response(401, json=body))
        with self.assertRaises(LLMError) as ctx, self.assertLogs(level="WARNING") as logs:
            deepseek(rec).generate(MESSAGES)
        self.assertNotIn(DEEPSEEK_KEY, str(ctx.exception))
        self.assertNotIn("Invalid key", str(ctx.exception))  # the body never reaches callers
        joined = "\n".join(logs.output)
        self.assertNotIn(DEEPSEEK_KEY, joined)
        self.assertIn("[REDACTED]", joined)


CLEAN_ENV = {k: v for k, v in os.environ.items() if not k.startswith("INTELLISTUDY_")}


@mock.patch.dict(os.environ, CLEAN_ENV, clear=True)
class FactoryTests(unittest.TestCase):
    def test_none_provider(self) -> None:
        self.assertIsNone(build_provider(make_settings(llm_provider="none")))

    def test_hosted_provider_without_a_key_is_not_built(self) -> None:
        self.assertIsNone(build_provider(make_settings(llm_provider="deepseek")))
        self.assertIsNone(build_provider(make_settings(llm_provider="openai", openai_api_key="your-api-key-here")))

    def test_deepseek_with_key_and_overrides(self) -> None:
        provider = build_provider(make_settings(llm_provider="deepseek", deepseek_api_key=DEEPSEEK_KEY,
                                                llm_model="deepseek-flash"))
        assert isinstance(provider, DeepSeekProvider)
        self.assertEqual(provider.model_name, "deepseek-flash")
        self.assertEqual(provider.name, "deepseek")

    def test_local_provider_needs_no_key(self) -> None:
        provider = build_provider(make_settings(llm_provider="local", llm_base_url="http://127.0.0.1:8001/v1"))
        self.assertIsInstance(provider, LocalProvider)


if __name__ == "__main__":
    logging.disable(logging.NOTSET)
    unittest.main()
