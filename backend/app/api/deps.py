"""FastAPI dependencies. Everything comes from ``app.state``, set once by ``create_app``."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from backend.app.core.clock import Clock
from backend.app.core.config import Settings
from backend.app.core.errors import ApiError
from backend.app.core.logging import security_event
from backend.app.core.ratelimit import RateLimiter, client_ip
from backend.app.db.models import User
from backend.app.db.session import session_scope
from backend.app.services.ai_container import AIContainer
from backend.app.services.auth import AuthService, unauthorized

#: Value of the header that cookie-authenticated endpoints require (contract RT-07).
CSRF_HEADER = "X-Requested-With"
CSRF_VALUE = "IntelliStudy"


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_session(request: Request) -> Iterator[Session]:
    yield from session_scope(request.app.state.session_factory)


def get_ai(request: Request) -> AIContainer:
    container: AIContainer = request.app.state.ai
    return container


def get_rate_limiter(request: Request) -> RateLimiter:
    limiter: RateLimiter = request.app.state.rate_limiter
    return limiter


def get_clock(request: Request) -> Clock:
    clock: Clock = request.app.state.clock
    return clock


def get_auth(request: Request) -> AuthService:
    auth: AuthService = request.app.state.auth
    return auth


def get_current_user(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    auth: Annotated[AuthService, Depends(get_auth)],
) -> User:
    """The authenticated user. Only ``Authorization: Bearer <token>`` is accepted, exactly once (JWT-06)."""
    values = request.headers.getlist("authorization")
    if len(values) != 1:
        raise unauthorized()
    scheme, _, token = values[0].strip().partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token or " " in token:
        raise unauthorized()
    return auth.authenticate(session, token)


def require_csrf_guard(request: Request, settings: Annotated[Settings, Depends(get_settings)]) -> None:
    """Cookie-authenticated endpoints (refresh, logout) need the custom header and, if sent, an allowed Origin (RT-07).

    A custom header cannot be set cross-site without a CORS preflight, which the allowlist refuses.
    """
    origin = request.headers.get("origin")
    if request.headers.get(CSRF_HEADER) != CSRF_VALUE or (origin is not None and origin not in settings.cors_origins):
        security_event("csrf_rejected", ip=client_ip(request), path=request.url.path, origin=origin or "")
        raise ApiError(403, "Forbidden.", code="csrf_rejected")


CurrentUser = Annotated[User, Depends(get_current_user)]
DbSession = Annotated[Session, Depends(get_session)]
