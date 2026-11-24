"""Access tokens (contract section 6: JWT-01..09).

* HS256 only; the verifier passes ``algorithms=["HS256"]`` so ``none``, HS512 and asymmetric algorithms (key
  confusion) are rejected by the library before any claim is read (JWT-01).
* Required claims ``sub iss aud iat exp jti typ``; ``typ`` must be ``access`` (JWT-03).
* ``exp`` / ``iat`` are checked against the application clock (not the library's wall clock) with the configured
  leeway (at most 30 s), so tests can drive time exactly.
* ``iat`` is a NumericDate with microsecond precision (RFC 7519 allows non-integer values), so revocation by
  ``tokens_valid_after`` (JWT-05) is exact: a token issued in the same second as a password change but before it is
  rejected, and the fresh token issued after it is accepted.
* Every failure raises the same :class:`InvalidToken`; callers map it to one generic 401 (JWT-09).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import jwt

from backend.app.core.clock import Clock
from backend.app.core.config import Settings

ALGORITHM = "HS256"
TOKEN_TYPE = "access"
REQUIRED_CLAIMS = ("sub", "iss", "aud", "iat", "exp", "jti", "typ")


class InvalidToken(Exception):
    """Any access-token failure. Deliberately carries no detail that could reach a client."""


@dataclass(frozen=True, slots=True)
class AccessClaims:
    sub: str
    iat: float
    exp: float
    jti: str


@dataclass(frozen=True, slots=True)
class IssuedToken:
    token: str
    expires_in: int


def _ts(moment: datetime) -> float:
    return round(moment.timestamp(), 6)


class TokenService:
    def __init__(self, settings: Settings, clock: Clock) -> None:
        if settings.jwt_secret is None:
            raise ValueError("JWT secret is not configured")
        self._key = settings.jwt_secret.get_secret_value()
        self._issuer = settings.jwt_issuer
        self._audience = settings.jwt_audience
        self._lifetime = settings.access_token_minutes * 60
        self._leeway = settings.jwt_leeway_seconds
        self._clock = clock

    def issue(self, user_id: str) -> IssuedToken:
        now = _ts(self._clock.now())
        claims: dict[str, Any] = {
            "sub": user_id,
            "iss": self._issuer,
            "aud": self._audience,
            "iat": now,
            "exp": now + self._lifetime,
            "jti": str(uuid.uuid4()),
            "typ": TOKEN_TYPE,
        }
        return IssuedToken(jwt.encode(claims, self._key, algorithm=ALGORITHM), self._lifetime)

    def verify(self, token: str) -> AccessClaims:
        try:
            claims = jwt.decode(
                token,
                self._key,
                algorithms=[ALGORITHM],
                audience=self._audience,
                issuer=self._issuer,
                options={
                    "require": list(REQUIRED_CLAIMS),
                    # time checks below use the application clock
                    "verify_exp": False,
                    "verify_iat": False,
                    "verify_nbf": False,
                },
            )
        except jwt.PyJWTError as exc:
            raise InvalidToken from exc
        if claims.get("typ") != TOKEN_TYPE:
            raise InvalidToken
        sub, jti, iat, exp = claims.get("sub"), claims.get("jti"), claims.get("iat"), claims.get("exp")
        if not isinstance(sub, str) or not isinstance(jti, str) or not sub or not jti:
            raise InvalidToken
        if not isinstance(iat, int | float) or not isinstance(exp, int | float) or isinstance(iat, bool):
            raise InvalidToken
        now = _ts(self._clock.now())
        if exp < now - self._leeway:  # expired beyond the leeway
            raise InvalidToken
        if iat > now + self._leeway:  # issued in the future
            raise InvalidToken
        return AccessClaims(sub=sub, iat=float(iat), exp=float(exp), jti=jti)


def timestamp(moment: datetime) -> float:
    """Same rounding as token ``iat``, for comparisons with ``tokens_valid_after``."""
    return _ts(moment)
