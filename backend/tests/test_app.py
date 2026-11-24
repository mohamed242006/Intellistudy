"""HTTP hardening and health: contract SEC-08, HTTP-02..06, OWN-04 (matrix S-05..S-10)."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
import warnings
from unittest import mock

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.tests.helpers import DEEPSEEK_KEY, JWT_SECRET, make_settings

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    from fastapi.testclient import TestClient

CLEAN_ENV = {k: v for k, v in os.environ.items() if not k.startswith("INTELLISTUDY_")}
ALLOWED = "http://localhost:5173"


class _Echo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: int


def _test_routes() -> APIRouter:
    router = APIRouter(prefix="/api/v1/_test")

    @router.post("/echo")
    def echo(body: _Echo) -> dict[str, int]:
        return {"value": body.value}

    @router.get("/boom")
    def boom() -> None:
        raise RuntimeError("secret path /etc/intellistudy and sk-should-not-leak-123456")

    return router


@mock.patch.dict(os.environ, CLEAN_ENV, clear=True)
class AppTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="intellistudy-app-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.settings = self.make_settings()
        app = create_app(self.settings)
        app.include_router(_test_routes())
        self.app = app
        self.client = TestClient(app, raise_server_exceptions=False)
        self.addCleanup(self.client.close)

    def make_settings(self) -> Settings:
        return make_settings(self.tmp)


class HealthTests(AppTestCase):
    def test_health_reports_booleans_and_names_only(self) -> None:
        response = self.client.get("/api/v1/health")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["database"], "ok")
        self.assertEqual(body["llm"], {"configured": False, "provider": "none"})
        self.assertTrue(all(isinstance(v, bool) for v in body["models"].values()))

    def test_health_does_not_load_models(self) -> None:
        self.client.get("/api/v1/health")
        self.assertFalse(any(self.app.state.ai.status().values()))


class ProdHealthTests(AppTestCase):
    def make_settings(self) -> Settings:
        return Settings(_env_file=None, profile="prod", jwt_secret=JWT_SECRET, llm_provider="deepseek",
                        deepseek_api_key=DEEPSEEK_KEY, database_url=f"sqlite:///{self.tmp}/p.sqlite3",
                        data_dir=f"{self.tmp}/data")

    def test_prod_health_leaks_no_secret_path_or_url(self) -> None:  # S-05 / SEC-08
        response = self.client.get("/api/v1/health")
        text = response.text
        self.assertEqual(response.json()["llm"], {"configured": True, "provider": "deepseek"})
        for leak in (DEEPSEEK_KEY, JWT_SECRET, self.tmp, "api.deepseek.com", "sqlite"):
            self.assertNotIn(leak, text)

    def test_docs_are_disabled_in_prod(self) -> None:  # S-09 / HTTP-05
        for path in ("/docs", "/redoc", "/openapi.json"):
            self.assertEqual(self.client.get(path).status_code, 404, path)


class DocsTests(AppTestCase):
    def test_docs_are_available_in_demo_and_test_profiles(self) -> None:
        self.assertEqual(self.client.get("/openapi.json").status_code, 200)
        docs = self.client.get("/docs")
        self.assertEqual(docs.status_code, 200)
        self.assertIn("cdn.jsdelivr.net", docs.headers["content-security-policy"])  # docs CSP only on docs pages


class SecurityHeaderTests(AppTestCase):
    def test_security_headers_on_api_responses(self) -> None:  # S-07 / HTTP-03
        headers = self.client.get("/api/v1/health").headers
        self.assertEqual(headers["x-content-type-options"], "nosniff")
        self.assertEqual(headers["referrer-policy"], "no-referrer")
        self.assertEqual(headers["x-frame-options"], "DENY")
        self.assertEqual(headers["cache-control"], "no-store")
        self.assertIn("frame-ancestors 'none'", headers["content-security-policy"])

    def test_security_headers_also_on_errors(self) -> None:
        headers = self.client.get("/api/v1/does-not-exist").headers
        self.assertEqual(headers["x-content-type-options"], "nosniff")
        self.assertEqual(headers["cache-control"], "no-store")


class CorsTests(AppTestCase):
    def preflight(self, origin: str):
        return self.client.options("/api/v1/health", headers={
            "Origin": origin, "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization"})

    def test_allowed_origins_pass_preflight(self) -> None:
        for origin in ("http://localhost:3000", "http://localhost:5173", "http://127.0.0.1:5173"):
            response = self.preflight(origin)
            self.assertEqual(response.status_code, 200, origin)
            self.assertEqual(response.headers["access-control-allow-origin"], origin)
            self.assertEqual(response.headers["access-control-allow-credentials"], "true")

    def test_foreign_origin_is_rejected(self) -> None:  # S-06 / HTTP-02
        for origin in ("https://evil.example", "http://localhost:8080", "null"):
            response = self.preflight(origin)
            self.assertNotEqual(response.headers.get("access-control-allow-origin"), origin)
            self.assertNotIn("access-control-allow-origin", response.headers)

    def test_simple_request_from_foreign_origin_gets_no_cors_grant(self) -> None:
        response = self.client.get("/api/v1/health", headers={"Origin": "https://evil.example"})
        self.assertNotIn("access-control-allow-origin", response.headers)


class ErrorTests(AppTestCase):
    def test_unhandled_exception_is_a_bare_500_problem(self) -> None:  # S-08 / HTTP-04
        with self.assertLogs(level="ERROR"):
            response = self.client.get("/api/v1/_test/boom")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.headers["content-type"], "application/problem+json")
        body = response.json()
        self.assertEqual(body["title"], "Internal Server Error")
        for leak in ("RuntimeError", "/etc/intellistudy", "sk-should-not-leak", "Traceback"):
            self.assertNotIn(leak, response.text)
        self.assertEqual(body["request_id"], response.headers["x-request-id"])
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")  # headers survive a 500

    def test_a_500_still_carries_cors_for_allowed_origins(self) -> None:
        with self.assertLogs(level="ERROR"):
            response = self.client.get("/api/v1/_test/boom", headers={"Origin": ALLOWED})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.headers["access-control-allow-origin"], ALLOWED)

    def test_unknown_route_is_the_standard_not_found_problem(self) -> None:  # OWN-04 shape
        response = self.client.get("/api/v1/nothing-here")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Resource not found.")
        self.assertEqual(response.json()["type"], "about:blank#not_found")

    def test_validation_errors_do_not_echo_submitted_values(self) -> None:
        response = self.client.post("/api/v1/_test/echo", json={"value": "sk-should-not-echo-999", "owner_id": "x"})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn("sk-should-not-echo", response.text)
        types = {e["type"] for e in response.json()["errors"]}
        self.assertIn("extra_forbidden", types)  # OWN-08: ownership fields are rejected, not ignored


class BodyLimitTests(AppTestCase):
    def make_settings(self) -> Settings:
        return make_settings(self.tmp, max_json_body_bytes=1024)

    def test_declared_oversized_body_is_413(self) -> None:  # S-10 / HTTP-06
        response = self.client.post("/api/v1/_test/echo", content=b'{"value": 1, "pad": "' + b"x" * 2000 + b'"}',
                                    headers={"Content-Type": "application/json"})
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.headers["content-type"], "application/problem+json")

    def test_chunked_oversized_body_without_content_length_is_413(self) -> None:
        def chunks():
            yield b'{"value": 1, "pad": "'
            for _ in range(10):
                yield b"x" * 200
            yield b'"}'

        response = self.client.post("/api/v1/_test/echo", content=chunks(), headers={"Content-Type": "application/json"})
        self.assertEqual(response.status_code, 413)

    def test_small_body_passes(self) -> None:
        response = self.client.post("/api/v1/_test/echo", json={"value": 7})
        self.assertEqual(response.json(), {"value": 7})


class RequestIdTests(AppTestCase):
    def test_a_well_formed_request_id_is_echoed(self) -> None:
        response = self.client.get("/api/v1/health", headers={"X-Request-ID": "abc12345-req"})
        self.assertEqual(response.headers["x-request-id"], "abc12345-req")

    def test_a_malformed_request_id_is_replaced(self) -> None:
        response = self.client.get("/api/v1/health", headers={"X-Request-ID": "bad id\r\nX-Injected: 1"})
        self.assertRegex(response.headers["x-request-id"], r"^[0-9a-f]{32}$")
        self.assertNotIn("x-injected", response.headers)


if __name__ == "__main__":
    unittest.main()
