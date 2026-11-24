"""M1 gate section 7: refresh-token rotation and revocation (G1-RT-01..18)."""

from __future__ import annotations

import hashlib
import re
import threading
from typing import Any

from sqlalchemy import select, update

from backend.app.db.models import RefreshToken, User
from backend.tests.m1_base import COOKIE, CSRF, PASSWORD, M1Case

REFRESH = "/api/v1/auth/refresh"
LOGOUT = "/api/v1/auth/logout"


def sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class RefreshCase(M1Case):
    def fresh_login(self, email: str = "a@example.org", ip: str = "10.1.0.1") -> tuple[Any, str, str]:
        """A new client, its access token and its refresh-token value."""
        client = self.client(ip)
        response = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
        self.assertEqual(response.status_code, 200)
        return client, response.json()["access_token"], response.cookies[COOKIE]

    def refresh_with(self, token: str | None, **headers: str) -> Any:
        """Refresh presenting exactly ``token`` (no cookie jar involved)."""
        cookie = {"Cookie": f"{COOKIE}={token}"} if token else {}
        return self.client("10.9.9.9").post(REFRESH, headers={**CSRF, **cookie, **headers})

    def row(self, token: str) -> RefreshToken:
        with self.db() as session:
            return session.scalars(select(RefreshToken).where(RefreshToken.token_hash == sha(token))).one()

    def family_rows(self, family_id: str) -> list[RefreshToken]:
        with self.db() as session:
            return list(session.scalars(select(RefreshToken).where(RefreshToken.family_id == family_id)))

    def assert_cookie_cleared(self, response: Any) -> None:
        header = response.headers.get("set-cookie", "")
        self.assertIn(f"{COOKIE}=", header)
        self.assertRegex(header.lower(), r"max-age=0")


class RefreshTokenTests(RefreshCase):
    def test_g1_rt_01_login_sets_only_the_scoped_secure_cookie(self) -> None:
        response = self.client("10.1.1.1").post("/api/v1/auth/login", json={"email": "a@example.org", "password": PASSWORD})
        body = response.json()
        self.assertEqual(set(body), {"access_token", "token_type", "expires_in"})
        cookie = response.cookies[COOKIE]
        self.assertNotIn(cookie, response.text)
        header = response.headers["set-cookie"]
        attributes = {a.strip().split("=")[0].lower(): (a.split("=", 1)[1] if "=" in a else "") for a in header.split(";")[1:]}
        self.assertTrue(header.startswith(f"{COOKIE}="))
        self.assertIn("httponly", attributes)
        self.assertIn("secure", attributes)
        self.assertEqual(attributes["samesite"].lower(), "strict")
        self.assertEqual(attributes["path"], "/api/v1/auth")
        self.assertEqual(attributes["max-age"], "604800")

    def test_g1_rt_02_token_has_256_bits_and_is_unique(self) -> None:
        _, _, first = self.fresh_login(ip="10.1.2.1")
        _, _, second = self.fresh_login(ip="10.1.2.2")
        for token in (first, second):
            self.assertGreaterEqual(len(token), 43)
            self.assertRegex(token, r"^[A-Za-z0-9_-]+$")
        self.assertNotEqual(first, second)

    def test_g1_rt_03_only_the_sha256_is_stored(self) -> None:
        _, _, token = self.fresh_login()
        row = self.row(token)
        self.assertEqual(row.token_hash, sha(token))
        with self.db() as session:
            for stored in session.scalars(select(RefreshToken)):
                values = [str(getattr(stored, c.key)) for c in RefreshToken.__table__.columns]
                self.assertNotIn(token, " ".join(values))

    def test_g1_rt_04_refresh_rotates_within_the_family(self) -> None:
        _, _, t1 = self.fresh_login()
        response = self.refresh_with(t1)
        self.assertEqual(response.status_code, 200, response.text)
        t2 = response.cookies[COOKIE]
        self.assertNotEqual(t1, t2)
        self.assertEqual(self.client().get("/api/v1/auth/me", headers=self.bearer(response.json()["access_token"])
                                           ).status_code, 200)
        old, new = self.row(t1), self.row(t2)
        self.assertIsNotNone(old.rotated_at)
        self.assertEqual(old.replaced_by_id, new.id)
        self.assertEqual(old.family_id, new.family_id)
        self.assertIsNone(new.rotated_at)

    def test_g1_rt_05_reuse_revokes_the_whole_family(self) -> None:
        _, _, t1 = self.fresh_login()
        t2 = self.refresh_with(t1).cookies[COOKIE]
        with self.assertLogs("intellistudy.security", level="WARNING") as logs:
            reused = self.refresh_with(t1)
        self.assertEqual(reused.status_code, 401)
        self.assert_cookie_cleared(reused)
        family = self.family_rows(self.row(t1).family_id)
        self.assertTrue(all(r.revoked_at is not None for r in family))
        self.assertIn("reuse_detected", {r.revoke_reason for r in family})
        self.assertEqual(self.refresh_with(t2).status_code, 401)  # the newest token of the family is dead too
        self.assertIn("refresh_reuse", [getattr(r, "security_event", {}).get("event") for r in logs.records])

    def test_g1_rt_06_concurrent_refresh_exactly_one_wins(self) -> None:
        _, _, t1 = self.fresh_login()
        barrier = threading.Barrier(2)
        results: list[Any] = []
        clients = [self.client("10.6.0.1"), self.client("10.6.0.2")]

        def attempt(client: Any) -> None:
            barrier.wait()
            results.append(client.post(REFRESH, headers={**CSRF, "Cookie": f"{COOKIE}={t1}"}))

        with self.assertLogs("intellistudy.security", level="WARNING"):
            threads = [threading.Thread(target=attempt, args=(c,)) for c in clients]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=30)
        statuses = sorted(r.status_code for r in results)
        self.assertEqual(statuses, [200, 401])
        winner = next(r for r in results if r.status_code == 200).cookies[COOKIE]
        self.assertEqual(self.refresh_with(winner).status_code, 401)  # the loser's reuse revoked the family
        self.assertTrue(all(r.revoked_at is not None for r in self.family_rows(self.row(t1).family_id)))

    def test_g1_rt_07_refresh_after_logout_fails(self) -> None:
        client, _, token = self.fresh_login()
        self.assertEqual(client.post(LOGOUT, headers=CSRF).status_code, 204)
        with self.assertLogs("intellistudy.security", level="WARNING"):
            response = self.refresh_with(token)
        self.assertEqual(response.status_code, 401)
        self.assert_cookie_cleared(response)

    def test_g1_rt_08_idle_expiry_after_7_days(self) -> None:
        _, _, token = self.fresh_login()
        self.clock.advance(days=7, seconds=1)
        self.assertEqual(self.refresh_with(token).status_code, 401)

    def test_g1_rt_09_absolute_expiry_after_30_days(self) -> None:
        _, _, token = self.fresh_login()
        for _ in range(5):  # rotate on days 6, 12, 18, 24, 30 (minus a second)
            self.clock.advance(days=6)
            if self.clock.now() >= self.row(token).family_expires_at:
                break
            response = self.refresh_with(token)
            self.assertEqual(response.status_code, 200, response.text)
            token = response.cookies[COOKIE]
        self.clock.advance(seconds=1)
        self.assertLess(self.row(token).family_expires_at, self.clock.now())
        self.assertEqual(self.refresh_with(token).status_code, 401)

    def test_g1_rt_10_logout_revokes_only_this_family(self) -> None:
        phone, _, phone_token = self.fresh_login(ip="10.10.0.1")
        _, _, laptop_token = self.fresh_login(ip="10.10.0.2")
        response = phone.post(LOGOUT, headers=CSRF)
        self.assertEqual(response.status_code, 204)
        self.assert_cookie_cleared(response)
        self.assertTrue(all(r.revoked_at for r in self.family_rows(self.row(phone_token).family_id)))
        with self.assertLogs("intellistudy.security", level="WARNING"):
            self.assertEqual(self.refresh_with(phone_token).status_code, 401)
        self.assertEqual(self.refresh_with(laptop_token).status_code, 200)

    def test_g1_rt_11_logout_all_revokes_every_family_and_access_token(self) -> None:
        _, access_1, token_1 = self.fresh_login(ip="10.11.0.1")
        _, _, token_2 = self.fresh_login(ip="10.11.0.2")
        self.clock.advance(1)
        self.assertEqual(self.client().post("/api/v1/auth/logout-all", headers=self.bearer(access_1)).status_code, 204)
        with self.db() as session:
            self.assertEqual(session.scalars(select(RefreshToken).where(
                RefreshToken.user_id == self.a_id, RefreshToken.revoked_at.is_(None))).all(), [])
        with self.assertLogs("intellistudy.security", level="WARNING"):
            self.assertEqual(self.refresh_with(token_1).status_code, 401)
            self.assertEqual(self.refresh_with(token_2).status_code, 401)
        self.assert_generic_401(self.client().get("/api/v1/auth/me", headers=self.bearer(access_1)))

    def test_g1_rt_12_change_password_revokes_all_and_returns_a_fresh_session(self) -> None:
        client, access, token = self.fresh_login()
        self.clock.advance(1)
        response = client.post("/api/v1/auth/change-password", headers=self.bearer(access),
                               json={"current_password": PASSWORD, "new_password": "betterlectures5"})
        self.assertEqual(response.status_code, 200, response.text)
        with self.assertLogs("intellistudy.security", level="WARNING"):
            self.assertEqual(self.refresh_with(token).status_code, 401)
        self.assert_generic_401(self.client().get("/api/v1/auth/me", headers=self.bearer(access)))
        fresh_cookie = response.cookies[COOKIE]
        self.assertEqual(self.client().get("/api/v1/auth/me", headers=self.bearer(response.json()["access_token"])
                                           ).status_code, 200)
        self.assertEqual(self.refresh_with(fresh_cookie).status_code, 200)

    def test_g1_rt_13_refresh_without_csrf_header_is_forbidden(self) -> None:
        _, _, token = self.fresh_login()
        client = self.client("10.13.0.1")
        for headers in ({}, {"X-Requested-With": "XMLHttpRequest"}):
            with self.subTest(headers=headers), self.assertLogs("intellistudy.security", level="WARNING"):
                response = client.post(REFRESH, headers={"Cookie": f"{COOKIE}={token}", **headers})
                self.assertEqual(response.status_code, 403)
        self.assertIsNone(self.row(token).rotated_at)

    def test_g1_rt_14_foreign_origin_is_forbidden(self) -> None:
        _, _, token = self.fresh_login()
        for path in (REFRESH, LOGOUT):
            with self.subTest(path=path), self.assertLogs("intellistudy.security", level="WARNING"):
                response = self.client("10.14.0.1").post(path, headers={
                    **CSRF, "Origin": "https://evil.example", "Cookie": f"{COOKIE}={token}"})
                self.assertEqual(response.status_code, 403)
        row = self.row(token)
        self.assertIsNone(row.rotated_at)
        self.assertIsNone(row.revoked_at)

    def test_g1_rt_15_missing_random_or_misplaced_cookie_is_rejected(self) -> None:
        self.assertEqual(self.refresh_with(None).status_code, 401)
        self.assertEqual(self.refresh_with("x" * 43).status_code, 401)
        _, _, token = self.fresh_login()
        client = self.client("10.15.0.1")
        client.cookies.set(COOKIE, token, domain="testserver", path="/api/v1/other")
        self.assertEqual(client.post(REFRESH, headers=CSRF).status_code, 401)  # wrong path: never sent

    def test_g1_rt_16_locked_or_disabled_account_cannot_refresh(self) -> None:
        _, _, token_a = self.fresh_login("a@example.org", ip="10.16.0.1")
        _, _, token_b = self.fresh_login("b@example.org", ip="10.16.0.2")
        with self.db() as session:
            session.execute(update(User).where(User.id == self.a_id).values(
                locked_until=self.clock.now().replace(year=2027)))
            session.execute(update(User).where(User.id == self.b_id).values(is_active=False))
            session.commit()
        self.assertEqual(self.refresh_with(token_a).status_code, 401)
        self.assertEqual(self.refresh_with(token_b).status_code, 401)

    def test_g1_rt_17_refresh_tokens_never_in_bodies_or_logs(self) -> None:
        with self.assertLogs(level="DEBUG") as logs:
            import logging

            logging.getLogger("probe").debug("start")
            client, _, t1 = self.fresh_login()
            r2 = self.refresh_with(t1)
            t2 = r2.cookies[COOKIE]
            r3 = self.refresh_with(t1)  # reuse
            r4 = client.post(LOGOUT, headers=CSRF)
        joined = "\n".join(logs.output)
        for token in (t1, t2):
            self.assertNotIn(token, joined)
            for response in (r2, r3, r4):
                self.assertNotIn(token, response.text)


class RefreshRateLimitTests(RefreshCase):
    real_rate_limits = True

    def test_g1_rt_18_31st_refresh_within_an_hour_is_429(self) -> None:
        _, _, token = self.fresh_login(ip="10.18.0.1")
        for i in range(30):
            response = self.refresh_with(token)
            self.assertEqual(response.status_code, 200, f"refresh {i + 1}: {response.text}")
            token = response.cookies[COOKIE]
        with self.assertLogs("intellistudy.security", level="WARNING"):
            response = self.refresh_with(token)
        self.assertEqual(response.status_code, 429)
        self.assertTrue(re.fullmatch(r"\d+", response.headers["retry-after"]))
        self.assertIsNone(self.row(token).rotated_at)  # the limited call did not rotate


if __name__ == "__main__":
    import unittest

    unittest.main()
