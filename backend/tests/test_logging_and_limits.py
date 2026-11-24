"""Log redaction and the security event log (SEC-06, SEC-09); rate limiting (UPL-16, section 9a)."""

from __future__ import annotations

import io
import json
import logging
import unittest

from backend.app.core.errors import ApiError
from backend.app.core.logging import REDACTED, RedactingFilter, _JsonFormatter, redact, security_event
from backend.app.core.ratelimit import LIMITS, InMemoryRateLimiter, Limit, enforce
from backend.tests.helpers import DEEPSEEK_KEY, JWT_SECRET


class RedactionTests(unittest.TestCase):
    def test_known_secret_values_are_masked(self) -> None:
        self.assertEqual(redact(f"key={JWT_SECRET}!", [JWT_SECRET]).count(JWT_SECRET), 0)

    def test_credential_shapes_are_masked_without_knowing_the_value(self) -> None:
        samples = {
            "Authorization: Bearer abcdefghijklmnop.qrs": "abcdefghijklmnop",
            "key sk-abcdefghij1234567890 used": "sk-abcdefghij",
            "jwt eyJhbGciOi.eyJzdWIiOiIx.c2lnbmF0dXJl here": "eyJzdWIiOiIx",
            'api_key="supersecretvalue123"': "supersecretvalue123",
            "password=hunter2hunter2": "hunter2hunter2",
        }
        for text, secret in samples.items():
            with self.subTest(text=text[:20]):
                clean = redact(text)
                self.assertNotIn(secret, clean)
                self.assertIn(REDACTED, clean)

    def test_ordinary_text_is_untouched(self) -> None:
        text = "uploaded lecture 4 (48 pages) in 3.1 s; token count 512"
        self.assertEqual(redact(text), text)


class RedactingHandlerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.stream = io.StringIO()
        handler = logging.StreamHandler(self.stream)
        handler.addFilter(RedactingFilter([JWT_SECRET, DEEPSEEK_KEY]))
        handler.setFormatter(_JsonFormatter())
        self.logger = logging.getLogger(f"test.redaction.{id(self)}")
        self.logger.addHandler(handler)
        self.logger.setLevel(logging.DEBUG)
        self.logger.propagate = False

    def lines(self) -> list[dict]:
        return [json.loads(line) for line in self.stream.getvalue().splitlines()]

    def test_message_arguments_are_redacted(self) -> None:
        self.logger.warning("provider said %s with %s", DEEPSEEK_KEY, JWT_SECRET)
        message = self.lines()[0]["message"]
        self.assertNotIn(DEEPSEEK_KEY, message)
        self.assertNotIn(JWT_SECRET, message)

    def test_exception_text_is_redacted(self) -> None:
        try:
            raise RuntimeError(f"failed with {DEEPSEEK_KEY}")
        except RuntimeError:
            self.logger.exception("call failed")
        record = self.lines()[0]
        self.assertNotIn(DEEPSEEK_KEY, record["exception"])
        self.assertIn("RuntimeError", record["exception"])


class SecurityEventTests(unittest.TestCase):
    def test_forbidden_fields_are_dropped(self) -> None:
        with self.assertLogs("intellistudy.security", level="WARNING") as logs:
            security_event("login_failed", email="a@example.org", password="hunter2hunter2", token="abc", text="doc")
        record = logs.records[0]
        event = record.security_event  # type: ignore[attr-defined]
        self.assertEqual(event, {"event": "login_failed", "email": "a@example.org"})


class RateLimitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = 1000.0
        self.limiter = InMemoryRateLimiter(clock=lambda: self.now)
        self.limit = Limit("t", 3, 60)

    def test_allows_up_to_the_limit_then_reports_the_wait(self) -> None:
        self.assertEqual([self.limiter.hit(self.limit, "ip") for _ in range(3)], [0.0, 0.0, 0.0])
        self.assertAlmostEqual(self.limiter.hit(self.limit, "ip"), 60.0)

    def test_window_slides(self) -> None:
        for _ in range(3):
            self.limiter.hit(self.limit, "ip")
        self.now += 60.0
        self.assertEqual(self.limiter.hit(self.limit, "ip"), 0.0)

    def test_keys_and_scopes_are_independent(self) -> None:
        for _ in range(3):
            self.limiter.hit(self.limit, "ip-a")
        self.assertEqual(self.limiter.hit(self.limit, "ip-b"), 0.0)
        self.assertEqual(self.limiter.hit(Limit("other", 3, 60), "ip-a"), 0.0)

    def test_enforce_raises_429_with_retry_after_and_logs(self) -> None:
        for _ in range(3):
            enforce(self.limiter, self.limit, "ip")
        with self.assertRaises(ApiError) as ctx, self.assertLogs("intellistudy.security", level="WARNING"):
            enforce(self.limiter, self.limit, "ip")
        self.assertEqual(ctx.exception.status, 429)
        self.assertEqual(ctx.exception.headers["Retry-After"], "60")

    def test_contract_limits_exist_for_every_protected_action(self) -> None:
        for scope in ("login:ip", "login:account", "register:ip", "upload:user", "chat:user", "quiz:user", "summary:user"):
            self.assertIn(scope, LIMITS)
        self.assertEqual((LIMITS["login:ip"].max_events, LIMITS["login:ip"].window_seconds), (5, 60))


if __name__ == "__main__":
    unittest.main()
