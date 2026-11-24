"""M1 gate section 8: login lockout, rate limits and password rules (G1-LOCK-01..09, G1-PWD-01..06)."""

from __future__ import annotations

import logging
import re
import statistics
import time
from typing import Any

from sqlalchemy import select

from backend.app.db.models import User
from backend.app.main import create_app
from backend.tests.m1_base import (
    COOKIE,
    CSRF,
    PASSWORD,
    M1Case,
    NoLimiter,
    _quiet_json_handler,
    without_request_id,
)

LOGIN = "/api/v1/auth/login"
WRONG = "not-the-password-1"


class LockoutCase(M1Case):
    def attempt(self, email: str, password: str, ip: str = "10.20.0.1") -> Any:
        return self.client(ip).post(LOGIN, json={"email": email, "password": password})

    def user(self, user_id: str) -> User:
        with self.db() as session:
            return session.scalars(select(User).where(User.id == user_id)).one()


class LockoutTests(LockoutCase):
    def test_g1_lock_01_sixth_attempt_rejected_even_with_the_right_password(self) -> None:
        with self.assertLogs("intellistudy.security", level="WARNING"):
            wrong = [self.attempt("a@example.org", WRONG) for _ in range(5)]
            locked = self.attempt("a@example.org", PASSWORD)
        self.assertTrue(all(r.status_code == 401 for r in wrong))
        self.assertEqual(locked.status_code, 401)
        self.assertEqual(without_request_id(locked.json()), without_request_id(wrong[0].json()))
        self.assertNotIn("lock", locked.text.lower())

    def test_g1_lock_02_lock_lasts_15_minutes(self) -> None:
        with self.assertLogs("intellistudy.security", level="WARNING"):
            for _ in range(5):
                self.attempt("a@example.org", WRONG)
            self.clock.advance(minutes=14, seconds=59)
            self.assertEqual(self.attempt("a@example.org", PASSWORD).status_code, 401)
        self.clock.advance(seconds=1)
        self.assertEqual(self.attempt("a@example.org", PASSWORD).status_code, 200)

    def test_g1_lock_03_success_resets_the_counter(self) -> None:
        with self.assertLogs("intellistudy.security", level="WARNING"):
            for _ in range(4):
                self.attempt("a@example.org", WRONG)
            self.assertEqual(self.attempt("a@example.org", PASSWORD).status_code, 200)
            for _ in range(4):
                self.attempt("a@example.org", WRONG)
        self.assertIsNone(self.user(self.a_id).locked_until)
        self.assertEqual(self.attempt("a@example.org", PASSWORD).status_code, 200)

    def test_g1_lock_04_locked_account_loses_its_sessions(self) -> None:
        refresh_cookie = self.a.cookies.get(COOKIE)
        with self.assertLogs("intellistudy.security", level="WARNING"):
            for _ in range(5):
                self.attempt("a@example.org", WRONG)
        self.assert_generic_401(self.client().get("/api/v1/auth/me", headers=self.bearer(self.a_token)))
        response = self.client("10.20.4.1").post("/api/v1/auth/refresh",
                                                 headers={**CSRF, "Cookie": f"{COOKIE}={refresh_cookie}"})
        self.assertEqual(response.status_code, 401)

    def test_g1_lock_05_failures_and_lock_are_logged_without_passwords(self) -> None:
        with self.assertLogs("intellistudy.security", level="WARNING") as logs:
            for _ in range(5):
                self.attempt("a@example.org", WRONG)
        events = [getattr(r, "security_event", {}) for r in logs.records]
        self.assertEqual(sum(e.get("event") == "login_failed" for e in events), 5)
        self.assertEqual(sum(e.get("event") == "account_locked" for e in events), 1)
        self.assertNotIn(WRONG, str(events) + "\n".join(logs.output))
        self.assertNotIn(PASSWORD, str(events) + "\n".join(logs.output))

    def test_g1_lock_06_unknown_email_is_indistinguishable(self) -> None:
        logging.disable(logging.WARNING)
        try:
            def run(email: str) -> tuple[list[float], set[str]]:
                times, bodies = [], set()
                for i in range(50):
                    started = time.perf_counter()
                    response = self.attempt(email, WRONG, ip=f"10.26.{i // 250}.{i % 250}")
                    times.append((time.perf_counter() - started) * 1000)
                    self.assertEqual(response.status_code, 401)
                    bodies.add(str(without_request_id(response.json())))
                    self.clock.advance(minutes=16)  # stay clear of the lock so every attempt does the same work
                return times, bodies

            known_times, known_bodies = run("b@example.org")
            unknown_times, unknown_bodies = run("nobody@example.org")
        finally:
            logging.disable(logging.NOTSET)
        self.assertEqual(known_bodies, unknown_bodies)
        self.assertEqual(len(known_bodies), 1)
        self.assertLess(abs(statistics.mean(known_times) - statistics.mean(unknown_times)), 20.0)


class LoginRateLimitTests(LockoutCase):
    real_rate_limits = True

    def test_g1_lock_07_per_ip_limit(self) -> None:
        self.clock.advance(61)
        with self.assertLogs("intellistudy.security", level="WARNING") as logs:
            responses = [self.attempt(f"user{i}@example.org", WRONG, ip="10.27.0.1") for i in range(6)]
        self.assertEqual([r.status_code for r in responses[:5]], [401] * 5)
        self.assertEqual(responses[5].status_code, 429)
        self.assertRegex(responses[5].headers["retry-after"], r"^\d+$")
        self.assertIn("rate_limited", [getattr(r, "security_event", {}).get("event") for r in logs.records])

    def test_g1_lock_08_per_account_limit(self) -> None:
        self.clock.advance(61)
        with self.assertLogs("intellistudy.security", level="WARNING"):
            responses = [self.attempt("c@example.org", WRONG, ip=f"10.28.0.{i}") for i in range(6)]
        self.assertEqual(responses[5].status_code, 429)

    def test_g1_lock_09_registration_limit(self) -> None:
        client = self.client("10.29.0.1")
        statuses = []
        with self.assertLogs("intellistudy.security", level="INFO"):
            for i in range(4):
                statuses.append(client.post("/api/v1/auth/register", json={
                    "email": f"new{i}@example.org", "name": "New", "password": PASSWORD}).status_code)
        self.assertEqual(statuses, [201, 201, 201, 429])


class PasswordTests(LockoutCase):
    def test_g1_pwd_01_argon2id_with_contract_parameters(self) -> None:
        stored = self.user(self.a_id).password_hash
        match = re.fullmatch(r"\$argon2id\$v=19\$m=(\d+),t=(\d+),p=(\d+)\$[^$]+\$[^$]+", stored)
        assert match is not None, stored[:30]
        memory, time_cost, parallelism = map(int, match.groups())
        self.assertGreaterEqual(memory, 19456)
        self.assertGreaterEqual(time_cost, 2)
        self.assertEqual(parallelism, 1)
        self.assertNotIn(PASSWORD, stored)

    def test_g1_pwd_02_hash_is_upgraded_on_login(self) -> None:
        stronger = self.settings.model_copy(update={"argon2_memory_kib": 24576, "argon2_time_cost": 3})
        app = create_app(stronger, rate_limiter=NoLimiter(), clock=self.clock)
        _quiet_json_handler()
        from fastapi.testclient import TestClient

        with TestClient(app, base_url="https://testserver") as client:
            self.assertEqual(client.post(LOGIN, json={"email": "a@example.org", "password": PASSWORD}).status_code, 200)
        self.assertIn("m=24576,t=3,p=1", self.user(self.a_id).password_hash)

    def test_g1_pwd_03_password_policy(self) -> None:
        cases = {"nine-char": "abcdefgh1", "no-digit": "abcdefghijk", "no-letter": "12345678901",
                 "common": "password123", "too-long": "a1" * 64 + "b"}
        for name, password in cases.items():
            with self.subTest(case=name):
                response = self.client("10.33.0.1").post("/api/v1/auth/register", json={
                    "email": f"{name}@example.org", "name": "X", "password": password})
                self.assertEqual(response.status_code, 422, response.text)
                self.assertNotIn(password, response.text)

    def test_g1_pwd_04_emails_are_unique_case_insensitively(self) -> None:
        for variant in ("A@Example.org", "  a@EXAMPLE.ORG "):
            with self.subTest(email=variant):
                response = self.client("10.34.0.1").post("/api/v1/auth/register", json={
                    "email": variant, "name": "Dup", "password": PASSWORD})
                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.json()["detail"], "Registration could not be completed with these details.")
                self.assertNotIn("a@example.org", response.text.lower())
        with self.db() as session:
            self.assertEqual(len(session.scalars(select(User).where(User.email == "a@example.org")).all()), 1)

    def test_g1_pwd_05_passwords_hashes_and_tokens_never_logged(self) -> None:
        new_password = "betterlectures5"
        with self.assertLogs(level="DEBUG") as logs:
            logging.getLogger("probe").debug("start")
            client = self.client("10.35.0.1")
            client.post("/api/v1/auth/register", json={"email": "d@example.org", "name": "D", "password": PASSWORD})
            token = client.post(LOGIN, json={"email": "d@example.org", "password": PASSWORD}).json()["access_token"]
            client.post(LOGIN, json={"email": "d@example.org", "password": WRONG})
            self.clock.advance(1)
            client.post("/api/v1/auth/change-password", headers=self.bearer(token),
                        json={"current_password": PASSWORD, "new_password": new_password})
        joined = "\n".join(logs.output)
        stored_hash = self.user(self.a_id).password_hash
        for secret in (PASSWORD, new_password, WRONG, token, "$argon2id$", stored_hash):
            self.assertNotIn(secret, joined)

    def test_g1_pwd_06_wrong_current_password_counts_toward_lockout(self) -> None:
        refresh_cookie = self.a.cookies.get(COOKIE)
        with self.assertLogs("intellistudy.security", level="WARNING"):
            first = self.a.post("/api/v1/auth/change-password", headers=self.bearer(self.a_token),
                                json={"current_password": WRONG, "new_password": "betterlectures5"})
        self.assertEqual(first.status_code, 400)
        self.assertEqual(self.user(self.a_id).failed_logins, 1)
        # sessions unchanged after one wrong attempt
        self.assertEqual(self.client().get("/api/v1/auth/me", headers=self.bearer(self.a_token)).status_code, 200)
        self.assertEqual(self.client("10.36.0.1").post("/api/v1/auth/refresh", headers={
            **CSRF, "Cookie": f"{COOKIE}={refresh_cookie}"}).status_code, 200)
        self.assertEqual(self.attempt("a@example.org", PASSWORD).status_code, 200)  # still able to log in
        with self.assertLogs("intellistudy.security", level="WARNING") as logs:
            token = self.attempt("a@example.org", PASSWORD).json()["access_token"]
            for _ in range(5):
                self.client().post("/api/v1/auth/change-password", headers=self.bearer(token),
                                   json={"current_password": WRONG, "new_password": "betterlectures5"})
        self.assertIn("account_locked", [getattr(r, "security_event", {}).get("event") for r in logs.records])
        self.assertEqual(self.attempt("a@example.org", PASSWORD).status_code, 401)


if __name__ == "__main__":
    import unittest

    unittest.main()
