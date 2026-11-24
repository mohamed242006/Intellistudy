"""Registration, login, sessions and revocation (contract sections 6 and 7).

Response shapes are decided by the API layer; this service decides *whether* something is allowed and keeps every
security-relevant state change in one transaction.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import CursorResult, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from backend.app.core.clock import Clock
from backend.app.core.config import Settings
from backend.app.core.errors import ApiError
from backend.app.core.logging import security_event
from backend.app.core.passwords import PasswordService, check_policy
from backend.app.core.ratelimit import LIMITS, RateLimiter, enforce
from backend.app.core.tokens import InvalidToken, IssuedToken, TokenService, timestamp
from backend.app.db.base import new_uuid
from backend.app.db.models import RefreshToken, Role, User
from backend.app.services.ownership import is_canonical_id

_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]+$")

LOGIN_FAILED = "Invalid email or password."


def unauthorized() -> ApiError:
    """The one 401 for every access-token failure (JWT-09)."""
    return ApiError(401, "Authentication required.", code="unauthorized", headers={"WWW-Authenticate": "Bearer"})


def login_failed() -> ApiError:
    """The one response for unknown email, wrong password, locked or disabled account (JWT-12, JWT-13)."""
    return ApiError(401, LOGIN_FAILED, code="invalid_credentials")


def session_rejected() -> ApiError:
    """Refresh-token failures (missing, unknown, expired, revoked, reused)."""
    return ApiError(401, "Session expired. Sign in again.", code="session_invalid")


def normalize_email(raw: str) -> str:
    return unicodedata.normalize("NFKC", raw).strip().lower()


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class SessionTokens:
    """What a successful login / refresh / password change hands to the API layer."""

    user: User
    access: IssuedToken
    refresh_token: str
    refresh_max_age: int


class AuthService:
    def __init__(self, settings: Settings, clock: Clock, passwords: PasswordService, tokens: TokenService,
                 limiter: RateLimiter) -> None:
        self._settings = settings
        self._clock = clock
        self._passwords = passwords
        self._tokens = tokens
        self._limiter = limiter
        self._idle = timedelta(days=settings.refresh_idle_days)
        self._absolute = timedelta(days=settings.refresh_absolute_days)
        self._lockout = timedelta(minutes=settings.lockout_minutes)

    # ------------------------------------------------------------------------------------------ register
    def register(self, session: Session, *, email: str, name: str, password: str) -> User:
        normalized = normalize_email(email)
        if len(normalized) > 254 or not _EMAIL.fullmatch(normalized):
            raise ApiError(422, "Enter a valid email address.", code="invalid_email")
        clean_name = " ".join(unicodedata.normalize("NFKC", name).split())
        if not 1 <= len(clean_name) <= 100:
            raise ApiError(422, "Enter your name (1-100 characters).", code="invalid_name")
        policy = check_policy(password, self._settings)
        if not policy.ok:
            raise ApiError(422, policy.reason, code="weak_password")
        password_hash = self._passwords.hash(password)  # before the existence check, so both paths cost the same
        if session.scalar(select(User.id).where(User.email == normalized)) is not None:
            raise self._registration_rejected()
        user = User(email=normalized, name=clean_name, password_hash=password_hash, role=Role.STUDENT.value)
        session.add(user)
        try:
            session.commit()
        except IntegrityError:  # concurrent registration of the same e-mail
            session.rollback()
            raise self._registration_rejected() from None
        security_event("user_registered", level=20, user_id=user.id)
        return user

    @staticmethod
    def _registration_rejected() -> ApiError:
        return ApiError(409, "Registration could not be completed with these details.", code="registration_rejected")

    # --------------------------------------------------------------------------------------------- login
    def login(self, session: Session, *, email: str, password: str, ip: str) -> SessionTokens:
        normalized = normalize_email(email)
        now = self._clock.now()
        user = session.scalars(select(User).where(User.email == normalized)).one_or_none()

        if user is not None and self._is_locked(user, now):
            self._passwords.verify_or_dummy(user.password_hash, password)  # same work as any other attempt
            security_event("login_failed", user_id=user.id, ip=ip, reason="locked")
            raise login_failed()

        ok = self._passwords.verify_or_dummy(user.password_hash if user else None, password)
        if user is None or not user.is_active or not ok:
            if user is not None and user.is_active and not ok:
                self._count_failure(session, user, now, ip)
            security_event("login_failed", user_id=user.id if user else None, ip=ip,
                           reason="unknown_email" if user is None else "bad_password" if not ok else "disabled")
            raise login_failed()

        user.failed_logins = 0
        user.locked_until = None
        if self._passwords.needs_rehash(user.password_hash):  # G1-PWD-02
            user.password_hash = self._passwords.hash(password)
        tokens, _ = self._new_session(session, user, now)
        session.commit()
        security_event("login_succeeded", level=20, user_id=user.id, ip=ip)
        return tokens

    def _is_locked(self, user: User, now: datetime) -> bool:
        return user.locked_until is not None and user.locked_until > now

    def _count_failure(self, session: Session, user: User, now: datetime, ip: str) -> None:
        user.failed_logins += 1
        if user.failed_logins >= self._settings.lockout_threshold:
            user.failed_logins = 0
            user.locked_until = now + self._lockout
            security_event("account_locked", user_id=user.id, ip=ip, minutes=self._settings.lockout_minutes)
        session.commit()

    # ------------------------------------------------------------------------------------ access tokens
    def authenticate(self, session: Session, token: str) -> User:
        """The user behind an access token, or the generic 401 (JWT-03, JWT-05, JWT-09)."""
        try:
            claims = self._tokens.verify(token)
        except InvalidToken:
            raise unauthorized() from None
        if not is_canonical_id(claims.sub):
            raise unauthorized()
        user = session.scalars(select(User).where(User.id == claims.sub)).one_or_none()
        now = self._clock.now()
        if user is None or not user.is_active or self._is_locked(user, now):
            raise unauthorized()
        if user.tokens_valid_after is not None and claims.iat < timestamp(user.tokens_valid_after):
            raise unauthorized()
        return user

    # ----------------------------------------------------------------------------------- refresh tokens
    def _new_session(self, session: Session, user: User, now: datetime, *, family_id: str | None = None,
                     family_expires_at: datetime | None = None) -> tuple[SessionTokens, RefreshToken]:
        plain = secrets.token_urlsafe(32)  # 256 bits (RT-01)
        family_end = family_expires_at or now + self._absolute
        row = RefreshToken(
            id=new_uuid(), user_id=user.id, family_id=family_id or new_uuid(), token_hash=hash_refresh_token(plain),
            created_at=now, expires_at=min(now + self._idle, family_end), family_expires_at=family_end,
        )
        session.add(row)
        max_age = max(int((row.expires_at - now).total_seconds()), 0)
        tokens = SessionTokens(user=user, access=self._tokens.issue(user.id), refresh_token=plain,
                               refresh_max_age=max_age)
        return tokens, row

    def refresh(self, session: Session, token: str | None) -> SessionTokens:
        """Rotate ``token`` (RT-04). Reuse of a rotated or revoked token revokes the whole family (RT-05)."""
        if not token:
            raise session_rejected()
        row = session.scalars(select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(token))
                              ).one_or_none()
        if row is None:
            raise session_rejected()
        now = self._clock.now()
        if row.rotated_at is not None or row.revoked_at is not None:
            self._revoke_family(session, row.family_id, now, reason="reuse_detected")
            security_event("refresh_reuse", user_id=row.user_id, family_id=row.family_id)
            raise session_rejected()
        if now >= row.expires_at or now >= row.family_expires_at:
            raise session_rejected()
        user = session.scalars(select(User).where(User.id == row.user_id)).one()
        if not user.is_active or self._is_locked(user, now):  # RT-08
            raise session_rejected()
        enforce(self._limiter, LIMITS["refresh:user"], user.id, actor=user.id)

        try:  # atomic claim: only one concurrent caller can rotate this row (RT-04 / G1-RT-06)
            result: CursorResult[Any] = session.execute(  # type: ignore[assignment]
                update(RefreshToken)
                .where(RefreshToken.id == row.id, RefreshToken.rotated_at.is_(None), RefreshToken.revoked_at.is_(None))
                .values(rotated_at=now, last_used_at=now)
                .execution_options(synchronize_session=False)
            )
            claimed = result.rowcount
        except OperationalError:
            session.rollback()
            claimed = 0
        if claimed != 1:
            session.rollback()
            self._revoke_family(session, row.family_id, now, reason="reuse_detected")
            security_event("refresh_reuse", user_id=row.user_id, family_id=row.family_id, race=True)
            raise session_rejected()

        tokens, new_row = self._new_session(session, user, now, family_id=row.family_id,
                                            family_expires_at=row.family_expires_at)
        session.execute(
            update(RefreshToken).where(RefreshToken.id == row.id).values(replaced_by_id=new_row.id)
            .execution_options(synchronize_session=False)
        )
        session.commit()
        return tokens

    def _revoke_family(self, session: Session, family_id: str, now: datetime, *, reason: str) -> None:
        session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now, revoke_reason=reason)
            .execution_options(synchronize_session=False)
        )
        session.commit()

    def logout(self, session: Session, token: str | None) -> None:
        """Revoke the family of ``token`` (RT-06). Unknown or missing tokens are a no-op (idempotent)."""
        if not token:
            return
        row = session.scalars(select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(token))
                              ).one_or_none()
        if row is not None:
            self._revoke_family(session, row.family_id, self._clock.now(), reason="logout")
            security_event("logout", level=20, user_id=row.user_id)

    def logout_all(self, session: Session, user: User) -> None:
        """Revoke every session of ``user`` and invalidate existing access tokens (RT-06, JWT-05)."""
        now = self._clock.now()
        self._revoke_all(session, user, now, reason="logout_all")
        session.commit()
        security_event("logout_all", user_id=user.id)

    def _revoke_all(self, session: Session, user: User, now: datetime, *, reason: str) -> None:
        session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now, revoke_reason=reason)
            .execution_options(synchronize_session=False)
        )
        user.tokens_valid_after = now

    # ------------------------------------------------------------------------------------ password change
    def change_password(self, session: Session, user: User, *, current: str, new: str, ip: str) -> SessionTokens:
        """Verify ``current``, set ``new``, revoke every session, return a fresh one (RT-06, G1-RT-12)."""
        now = self._clock.now()
        if not self._passwords.verify(user.password_hash, current):
            self._count_failure(session, user, now, ip)  # counts toward lockout (G1-PWD-06)
            security_event("password_change_failed", user_id=user.id, ip=ip)
            raise ApiError(400, "The current password is not correct.", code="invalid_current_password")
        policy = check_policy(new, self._settings)
        if not policy.ok:
            raise ApiError(422, policy.reason, code="weak_password")
        user.password_hash = self._passwords.hash(new)
        user.failed_logins = 0
        self._revoke_all(session, user, now, reason="password_changed")
        tokens, _ = self._new_session(session, user, now)
        session.commit()
        security_event("password_changed", user_id=user.id, ip=ip)
        return tokens
