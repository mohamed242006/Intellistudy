"""IntelliStudy API application factory.

Run locally (demo profile; settings come from the environment or a git-ignored ``.env``):

    uvicorn --factory backend.app.main:create_app --host 127.0.0.1 --port 8000

There is deliberately no module-level ``app``: importing this module must not read the environment or fail on a
missing secret, so tests can build apps with explicit settings.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.v1 import router as v1_router
from backend.app.core.clock import Clock, SystemClock
from backend.app.core.config import Settings, get_settings
from backend.app.core.errors import UnhandledErrorMiddleware, install_error_handlers
from backend.app.core.logging import configure_logging
from backend.app.core.middleware import (
    BodySizeLimitMiddleware,
    RequestIdMiddleware,
    SecurityHeadersMiddleware,
)
from backend.app.core.passwords import PasswordService
from backend.app.core.ratelimit import InMemoryRateLimiter, RateLimiter
from backend.app.core.tokens import TokenService
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.services.ai_container import AIContainer
from backend.app.services.auth import AuthService


def create_app(
    settings: Settings | None = None, *, rate_limiter: RateLimiter | None = None, clock: Clock | None = None
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.secret_values())

    clock = clock or SystemClock()
    limiter = rate_limiter or InMemoryRateLimiter(clock=clock.monotonic)
    engine = create_db_engine(settings.database_url)
    ai = AIContainer(settings)
    passwords = PasswordService(settings)
    auth = AuthService(settings, clock, passwords, TokenService(settings, clock), limiter)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        ai.close()
        engine.dispose()

    docs = settings.api_docs_enabled
    app = FastAPI(
        title="IntelliStudy API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)
    app.state.ai = ai
    app.state.clock = clock
    app.state.rate_limiter = limiter
    app.state.auth = auth

    install_error_handlers(app)
    app.include_router(v1_router)

    # Starlette runs the last-added middleware first:
    #   request id -> security headers -> body limit -> CORS -> unhandled-error -> app
    # so a 500 produced by UnhandledErrorMiddleware still gets CORS, security headers and the request id.
    app.add_middleware(UnhandledErrorMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Requested-With", "X-Request-ID", "Idempotency-Key"],
        expose_headers=["X-Request-ID", "Retry-After"],
        max_age=600,
    )
    app.add_middleware(
        BodySizeLimitMiddleware,
        max_bytes=settings.max_json_body_bytes,
        exempt_prefixes=_upload_paths(),
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestIdMiddleware)
    return app


def _upload_paths() -> tuple[str, ...]:
    """No upload route exists in M0, so nothing is exempt yet; M2 narrows this to the exact upload path."""
    return ()
