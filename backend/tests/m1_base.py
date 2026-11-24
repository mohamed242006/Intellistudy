"""Shared fixture for the M1 security merge gate tests (docs/SECURITY_MERGE_GATE.md).

Fresh migrated SQLite database per test, a fake clock driving every time decision, and three users with separate
clients (own cookie jar and client IP): A and B (STUDENT) with one course each, C (ADMIN). Clients talk https so the
``Secure`` refresh cookie is stored and sent back, as in a browser.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import unittest
import warnings
from typing import Any

from sqlalchemy import update
from sqlalchemy.orm import Session

from backend.app.core.clock import FakeClock
from backend.app.core.ratelimit import InMemoryRateLimiter, Limit
from backend.app.db.migrate import upgrade
from backend.app.db.models import Role, User
from backend.app.main import create_app
from backend.tests.helpers import make_settings

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    from fastapi.testclient import TestClient

PASSWORD = "lectures4ever"
CSRF = {"X-Requested-With": "IntelliStudy"}
COOKIE = "__Secure-is_refresh"


class NoLimiter:
    """Rate limiting off, for tests that are not about rate limits."""

    def hit(self, limit: Limit, key: str) -> float:
        return 0.0

    def reset(self) -> None:
        return None


def _quiet_json_handler() -> None:
    """create_app installs the JSON log handler; tests read events with assertLogs instead."""
    root = logging.getLogger()
    root.handlers = [h for h in root.handlers if not getattr(h, "_intellistudy", False)]


def without_request_id(body: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in body.items() if k != "request_id"}


class M1Case(unittest.TestCase):
    real_rate_limits = False
    with_users = True

    def settings_overrides(self) -> dict[str, Any]:
        return {}

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="intellistudy-m1-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.settings = make_settings(self.tmp, **self.settings_overrides())
        upgrade(self.settings.database_url)
        self.clock = FakeClock()
        limiter = InMemoryRateLimiter(clock=self.clock.monotonic) if self.real_rate_limits else NoLimiter()
        self.app = create_app(self.settings, rate_limiter=limiter, clock=self.clock)
        _quiet_json_handler()
        self._clients: list[TestClient] = []
        if self.with_users:
            self.a = self.client("10.0.0.1")
            self.b = self.client("10.0.0.2")
            self.c = self.client("10.0.0.3")
            self.a_id = self.register(self.a, "a@example.org", "Alice")["id"]
            self.b_id = self.register(self.b, "b@example.org", "Bob")["id"]
            self.c_id = self.register(self.c, "c@example.org", "Carol")["id"]
            with self.db() as session:
                session.execute(update(User).where(User.id == self.c_id).values(role=Role.ADMIN.value))
                session.commit()
            self.a_token = self.login(self.a, "a@example.org")
            self.b_token = self.login(self.b, "b@example.org")
            self.c_token = self.login(self.c, "c@example.org")
            self.a_course = self.create_course(self.a_token, "Aspect-Oriented Programming", "CSE447")
            self.b_course = self.create_course(self.b_token, "Queueing Theory", "CSE423")

    def tearDown(self) -> None:
        for client in self._clients:
            client.close()

    # ------------------------------------------------------------------------------------------ helpers
    def client(self, ip: str = "10.0.0.9") -> TestClient:
        client = TestClient(self.app, base_url="https://testserver", client=(ip, 50000), raise_server_exceptions=False)
        self._clients.append(client)
        return client

    def db(self) -> Session:
        return self.app.state.session_factory()

    def register(self, client: TestClient, email: str, name: str = "User", password: str = PASSWORD) -> dict[str, Any]:
        response = client.post("/api/v1/auth/register", json={"email": email, "name": name, "password": password})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def login(self, client: TestClient, email: str, password: str = PASSWORD) -> str:
        response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
        self.assertEqual(response.status_code, 200, response.text)
        return str(response.json()["access_token"])

    @staticmethod
    def bearer(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def create_course(self, token: str, name: str, code: str | None = None) -> str:
        body: dict[str, Any] = {"name": name}
        if code:
            body["code"] = code
        response = self.client().post("/api/v1/courses", json=body, headers=self.bearer(token))
        self.assertEqual(response.status_code, 201, response.text)
        return str(response.json()["id"])

    def not_found_body(self, token: str) -> dict[str, Any]:
        """The 404 body for a never-issued id: the reference for "same 404" (gate rule 4)."""
        response = self.client().get("/api/v1/courses/00000000-0000-4000-8000-000000000000", headers=self.bearer(token))
        self.assertEqual(response.status_code, 404)
        return without_request_id(response.json())

    def assert_same_404(self, response: Any, token: str) -> None:
        self.assertEqual(response.status_code, 404, response.text)
        self.assertEqual(response.headers["content-type"], "application/problem+json")
        self.assertEqual(without_request_id(response.json()), self.not_found_body(token))

    def generic_401_body(self) -> dict[str, Any]:
        response = self.client().get("/api/v1/auth/me")
        self.assertEqual(response.status_code, 401)
        return without_request_id(response.json())

    def assert_generic_401(self, response: Any) -> None:
        self.assertEqual(response.status_code, 401, response.text)
        self.assertEqual(response.headers.get("www-authenticate"), "Bearer")
        self.assertEqual(without_request_id(response.json()), self.generic_401_body())

    def cookie_of(self, client: TestClient) -> str | None:
        return client.cookies.get(COOKIE, domain="testserver", path="/api/v1/auth")
