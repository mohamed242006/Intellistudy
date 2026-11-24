"""Settings and secret rules: contract JWT-02, SEC-02, SEC-04, SEC-05, HTTP-02, HTTP-05 (matrix S-02, S-03)."""

from __future__ import annotations

import os
import secrets
import unittest
from unittest import mock

from pydantic import ValidationError

from backend.app.core.config import (
    DEFAULT_CORS_ORIGINS,
    ConfigurationError,
    Settings,
    jwt_secret_problem,
)
from backend.tests.helpers import DEEPSEEK_KEY, JWT_SECRET, make_settings

CLEAN_ENV = {k: v for k, v in os.environ.items() if not k.startswith("INTELLISTUDY_")}


@mock.patch.dict(os.environ, CLEAN_ENV, clear=True)
class SecretRuleTests(unittest.TestCase):
    def build(self, **kw):
        return Settings(_env_file=None, **kw)

    def test_prod_refuses_to_start_without_a_jwt_secret(self) -> None:
        with self.assertRaises(ConfigurationError) as ctx:
            self.build(profile="prod", llm_provider="none")
        self.assertIn("not set", str(ctx.exception))

    def test_demo_also_requires_a_jwt_secret(self) -> None:
        with self.assertRaises(ConfigurationError):
            self.build(profile="demo", llm_provider="none")

    def test_short_placeholder_and_low_variety_secrets_are_rejected(self) -> None:
        for bad in ("short-secret", "change-me", "replace-with-output-of-secrets.token_urlsafe-32", "a" * 64, "ab" * 32):
            with self.subTest(bad=bad[:12]), self.assertRaises(ConfigurationError) as ctx:
                self.build(profile="prod", llm_provider="none", jwt_secret=bad)
            self.assertNotIn(bad, str(ctx.exception))  # the value itself is never echoed

    def test_a_32_byte_random_secret_is_accepted(self) -> None:
        settings = self.build(profile="prod", llm_provider="none", jwt_secret=secrets.token_urlsafe(32))
        self.assertEqual(jwt_secret_problem(settings.jwt_secret), "")

    def test_exactly_32_bytes_is_the_minimum(self) -> None:
        self.assertEqual(jwt_secret_problem(make_settings(jwt_secret=secrets.token_hex(16)).jwt_secret), "")  # 32 chars
        self.assertIn("shorter", jwt_secret_problem(make_settings(jwt_secret=secrets.token_hex(15) + "x").jwt_secret))

    def test_prod_with_deepseek_requires_a_real_key(self) -> None:
        with self.assertRaises(ConfigurationError) as ctx:
            self.build(profile="prod", jwt_secret=JWT_SECRET, llm_provider="deepseek")
        self.assertIn("deepseek", str(ctx.exception))
        with self.assertRaises(ConfigurationError):
            self.build(profile="prod", jwt_secret=JWT_SECRET, llm_provider="deepseek", deepseek_api_key="your-api-key-here")
        ok = self.build(profile="prod", jwt_secret=JWT_SECRET, llm_provider="deepseek", deepseek_api_key=DEEPSEEK_KEY)
        self.assertEqual(ok.provider_api_key.get_secret_value(), DEEPSEEK_KEY)

    def test_demo_runs_without_an_llm_key(self) -> None:
        settings = self.build(profile="demo", jwt_secret=JWT_SECRET, llm_provider="deepseek")
        self.assertIsNone(settings.provider_api_key)

    def test_secrets_come_from_the_environment(self) -> None:
        with mock.patch.dict(os.environ, {"INTELLISTUDY_JWT_SECRET": JWT_SECRET,
                                          "INTELLISTUDY_DEEPSEEK_API_KEY": DEEPSEEK_KEY}):
            settings = self.build(profile="prod", llm_provider="deepseek")
        self.assertEqual(settings.jwt_secret.get_secret_value(), JWT_SECRET)


@mock.patch.dict(os.environ, CLEAN_ENV, clear=True)
class MaskingTests(unittest.TestCase):
    def test_repr_str_and_dump_never_show_secrets(self) -> None:  # S-03 / SEC-04
        settings = make_settings(llm_provider="deepseek", deepseek_api_key=DEEPSEEK_KEY)
        for rendered in (repr(settings), str(settings), str(settings.model_dump()), settings.model_dump_json()):
            self.assertNotIn(JWT_SECRET, rendered)
            self.assertNotIn(DEEPSEEK_KEY, rendered)

    def test_secret_values_lists_every_configured_secret_for_redaction(self) -> None:
        settings = make_settings(llm_provider="deepseek", deepseek_api_key=DEEPSEEK_KEY)
        self.assertEqual(set(settings.secret_values()), {JWT_SECRET, DEEPSEEK_KEY})


@mock.patch.dict(os.environ, CLEAN_ENV, clear=True)
class HttpSettingsTests(unittest.TestCase):
    def test_default_cors_origins_are_the_approved_list(self) -> None:
        self.assertEqual(make_settings().cors_origins, DEFAULT_CORS_ORIGINS)
        self.assertEqual(DEFAULT_CORS_ORIGINS, ("http://localhost:3000", "http://localhost:5173", "http://127.0.0.1:5173"))

    def test_wildcard_and_malformed_origins_are_rejected(self) -> None:  # HTTP-02
        for bad in ("*", "https://*.example.com", "localhost:3000"):
            with self.subTest(origin=bad), self.assertRaises(ValidationError):
                make_settings(cors_origins=bad)

    def test_origins_parse_from_a_comma_separated_env_value(self) -> None:
        with mock.patch.dict(os.environ, {"INTELLISTUDY_CORS_ORIGINS": "http://localhost:3000, https://app.example.org"}):
            settings = Settings(_env_file=None, profile="test")
        self.assertEqual(settings.cors_origins, ("http://localhost:3000", "https://app.example.org"))

    def test_docs_are_off_in_prod_even_if_requested(self) -> None:  # HTTP-05
        self.assertTrue(make_settings().api_docs_enabled)
        prod = Settings(_env_file=None, profile="prod", jwt_secret=JWT_SECRET, llm_provider="none", docs_enabled=True)
        self.assertFalse(prod.api_docs_enabled)

    def test_upload_limit_default_is_100_mb(self) -> None:
        self.assertEqual(make_settings().max_upload_bytes, 100 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
