"""FastAPI dependencies. Everything comes from ``app.state``, set once by ``create_app``."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session

from backend.app.core.config import Settings
from backend.app.core.ratelimit import RateLimiter
from backend.app.db.session import session_scope
from backend.app.services.ai_container import AIContainer


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
