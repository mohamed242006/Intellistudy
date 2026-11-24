"""M1 gate section 6: access-token (JWT) validation (G1-JWT-01..16)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import uuid
from typing import Any
from unittest import mock

import jwt
from pydantic import ValidationError
from sqlalchemy import delete, update

from backend.app.core.config import ConfigurationError, Settings
from backend.app.db.models import User
from backend.tests.helpers import JWT_SECRET, make_settings
from backend.tests.m1_base import PASSWORD, M1Case

ME = "/api/v1/auth/me"


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def handmade(header: dict[str, Any], payload: dict[str, Any], key: str | None = JWT_SECRET) -> str:
    """Build a JWS by hand (for algorithms the library would refuse to produce)."""
    signing_input = f"{b64(json.dumps(header).encode())}.{b64(json.dumps(payload).encode())}"
    signature = b"" if key is None else hmac.new(key.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{b64(signature)}"


class JwtValidationTests(M1Case):
    def claims(self, **overrides: Any) -> dict[str, Any]:
        now = self.clock.now().timestamp()
        base = {"sub": self.a_id, "iss": "intellistudy-api", "aud": "intellistudy-web", "iat": now, "exp": now + 900,
                "jti": str(uuid.uuid4()), "typ": "access"}
        base.update(overrides)
        return {k: v for k, v in base.items() if v is not None}

    def sign(self, claims: dict[str, Any], *, key: str = JWT_SECRET, alg: str = "HS256") -> str:
        return jwt.encode(claims, key, algorithm=alg)

    def get_me(self, token: str) -> Any:
        return self.client().get(ME, headers=self.bearer(token))

    def test_g1_jwt_01_valid_token_is_accepted(self) -> None:
        response = self.get_me(self.a_token)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], self.a_id)

    def test_g1_jwt_02_alg_none_is_rejected(self) -> None:
        self.assert_generic_401(self.get_me(handmade({"alg": "none", "typ": "JWT"}, self.claims(), key=None)))
        self.assert_generic_401(self.get_me(handmade({"alg": "none", "typ": "JWT"}, self.claims())))

    def test_g1_jwt_03_hs512_and_wrong_key_are_rejected(self) -> None:
        self.assert_generic_401(self.get_me(self.sign(self.claims(), alg="HS512")))
        self.assert_generic_401(self.get_me(self.sign(self.claims(), key=secrets.token_urlsafe(32))))

    def test_g1_jwt_04_algorithm_confusion_is_rejected(self) -> None:
        for alg in ("RS256", "ES256", "PS256", "EdDSA"):
            with self.subTest(alg=alg):
                self.assert_generic_401(self.get_me(handmade({"alg": alg, "typ": "JWT"}, self.claims())))

    def test_g1_jwt_05_wrong_iss_aud_or_typ_is_rejected(self) -> None:
        for overrides in ({"iss": "someone-else"}, {"aud": "another-app"}, {"typ": "refresh"}, {"typ": None}):
            with self.subTest(overrides=overrides):
                self.assert_generic_401(self.get_me(self.sign(self.claims(**overrides))))

    def test_g1_jwt_06_missing_required_claims_are_rejected(self) -> None:
        for claim in ("sub", "exp", "iat", "jti"):
            with self.subTest(missing=claim):
                self.assert_generic_401(self.get_me(self.sign(self.claims(**{claim: None}))))

    def test_g1_jwt_07_expiry_leeway_is_30_seconds(self) -> None:
        now = self.clock.now().timestamp()
        self.assert_generic_401(self.get_me(self.sign(self.claims(iat=now - 931, exp=now - 31))))
        self.assertEqual(self.get_me(self.sign(self.claims(iat=now - 929, exp=now - 29))).status_code, 200)

    def test_g1_jwt_08_lifetime_is_15_minutes_and_capped_at_30(self) -> None:
        claims = jwt.decode(self.a_token, options={"verify_signature": False})
        self.assertAlmostEqual(claims["exp"] - claims["iat"], 15 * 60, places=3)
        with self.assertRaises(ValidationError):
            make_settings(access_token_minutes=31)

    def test_g1_jwt_09_unknown_or_deleted_user_is_rejected(self) -> None:
        self.assert_generic_401(self.get_me(self.sign(self.claims(sub=str(uuid.uuid4())))))
        self.assert_generic_401(self.get_me(self.sign(self.claims(sub="not-a-uuid"))))
        with self.db() as session:
            session.execute(delete(User).where(User.id == self.a_id))
            session.commit()
        self.assert_generic_401(self.get_me(self.a_token))

    def test_g1_jwt_10_disabled_or_locked_user_is_rejected(self) -> None:
        with self.db() as session:
            session.execute(update(User).where(User.id == self.a_id).values(is_active=False))
            session.execute(update(User).where(User.id == self.b_id).values(
                locked_until=self.clock.now().replace(year=2027)))
            session.commit()
        self.assert_generic_401(self.get_me(self.a_token))
        self.assert_generic_401(self.get_me(self.b_token))

    def test_g1_jwt_11_role_claim_in_token_is_ignored(self) -> None:
        forged_role = self.sign(self.claims(role="ADMIN"))
        me = self.get_me(forged_role).json()
        self.assertEqual(me["role"], "STUDENT")
        with self.assertLogs("intellistudy.security", level="WARNING"):
            response = self.client().get(f"/api/v1/courses/{self.b_course}", headers=self.bearer(forged_role))
        self.assert_same_404(response, self.a_token)

    def test_g1_jwt_12_token_only_in_one_bearer_header(self) -> None:
        token = self.a_token
        client = self.client()
        cases = {
            "query": lambda: client.get(f"{ME}?access_token={token}"),
            "cookie": lambda: client.get(ME, headers={"Cookie": f"access_token={token}"}),
            "form": lambda: client.request("GET", ME, data={"access_token": token}),
            "basic": lambda: client.get(ME, headers={"Authorization": "Basic " + b64(b"a@example.org:" + PASSWORD.encode())}),
            "bearer-empty": lambda: client.get(ME, headers={"Authorization": "Bearer "}),
            "bearer-two-parts": lambda: client.get(ME, headers={"Authorization": f"Bearer {token} extra"}),
            "two-headers": lambda: client.get(ME, headers=[("Authorization", f"Bearer {token}"),
                                                           ("Authorization", f"Bearer {token}")]),
        }
        for name, call in cases.items():
            with self.subTest(case=name):
                self.assert_generic_401(call())

    def test_g1_jwt_13_tokens_issued_before_revocation_are_rejected(self) -> None:
        self.clock.advance(1)
        response = self.a.post("/api/v1/auth/change-password", headers=self.bearer(self.a_token),
                               json={"current_password": PASSWORD, "new_password": "betterlectures5"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assert_generic_401(self.get_me(self.a_token))
        self.assertEqual(self.get_me(response.json()["access_token"]).status_code, 200)  # the fresh session works

        self.clock.advance(1)
        self.assertEqual(self.b.post("/api/v1/auth/logout-all", headers=self.bearer(self.b_token)).status_code, 204)
        self.assert_generic_401(self.get_me(self.b_token))

    def test_g1_jwt_14_every_failure_has_the_same_body_and_header(self) -> None:
        tokens = [handmade({"alg": "none"}, self.claims(), key=None), self.sign(self.claims(), alg="HS512"),
                  self.sign(self.claims(iss="x")), self.sign(self.claims(exp=self.clock.now().timestamp() - 100)),
                  self.sign(self.claims(sub=str(uuid.uuid4()))), "garbage", "a.b.c"]
        bodies = set()
        for token in tokens:
            response = self.get_me(token)
            self.assertEqual(response.headers.get("www-authenticate"), "Bearer")
            bodies.add(json.dumps({k: v for k, v in response.json().items() if k != "request_id"}, sort_keys=True))
        bodies.add(json.dumps({k: v for k, v in self.client().get(ME).json().items() if k != "request_id"}, sort_keys=True))
        self.assertEqual(len(bodies), 1, bodies)

    def test_g1_jwt_15_tokens_never_reach_the_logs(self) -> None:
        bad = self.sign(self.claims(iss="x"))
        with self.assertLogs(level="DEBUG") as logs:
            logging.getLogger("probe").debug("start")
            self.get_me(self.a_token)
            self.get_me(bad)
            self.client().get(f"{ME}?access_token={self.a_token}")
        joined = "\n".join(logs.output)
        for token in (self.a_token, bad):
            self.assertNotIn(token, joined)
            self.assertNotIn(token.split(".")[2], joined)  # not even the signature

    def test_g1_jwt_16_weak_or_placeholder_secret_refuses_to_start(self) -> None:
        clean = {k: v for k, v in os.environ.items() if not k.startswith("INTELLISTUDY_")}
        with mock.patch.dict(os.environ, clean, clear=True):
            for profile in ("demo", "prod"):
                for bad in ("short", "replace-with-output-of-secrets.token_urlsafe-32"):
                    with self.subTest(profile=profile, secret=bad[:8]), self.assertRaises(ConfigurationError):
                        Settings(_env_file=None, profile=profile, llm_provider="none", jwt_secret=bad)


if __name__ == "__main__":
    import unittest

    unittest.main()
