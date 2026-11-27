"""RFC 7807 problem documents for every error (contract HTTP-04, JWT-09, OWN-04).

Clients never see stack traces, SQL, file paths, library messages or provider error bodies. Unexpected exceptions are
logged (with redaction) under the request id that the response also carries, so an operator can correlate them.
"""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.app.core.logging import request_id_var

logger = logging.getLogger(__name__)

PROBLEM_JSON = "application/problem+json"


class ApiError(Exception):
    """An error with a fixed, client-safe message. Raise it from services; never put user content in ``detail``."""

    def __init__(self, status: int, detail: str = "", *, code: str = "", headers: dict[str, str] | None = None,
                 extra: dict[str, Any] | None = None) -> None:
        super().__init__(detail or HTTPStatus(status).phrase)
        self.status = status
        self.detail = detail
        self.code = code
        self.headers = headers or {}
        self.extra = extra or {}  # client-safe structured detail (e.g. per-file reason codes)


def not_found() -> ApiError:
    """The single 404 used for missing *and* foreign resources (OWN-04): same status, same body."""
    return ApiError(404, "Resource not found.", code="not_found")


def problem(status: int, detail: str = "", *, code: str = "", extra: dict[str, Any] | None = None,
            headers: dict[str, str] | None = None) -> JSONResponse:
    body: dict[str, Any] = {
        "type": f"about:blank#{code}" if code else "about:blank",
        "title": HTTPStatus(status).phrase,
        "status": status,
        "request_id": request_id_var.get(),
    }
    if detail:
        body["detail"] = detail
    if extra:
        body.update(extra)
    return JSONResponse(body, status_code=status, media_type=PROBLEM_JSON, headers=headers)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return problem(exc.status, exc.detail, code=exc.code, headers=exc.headers, extra=exc.extra)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, str) and exc.status_code < 500 else ""
        if exc.status_code == 404:
            return problem(404, "Resource not found.", code="not_found")  # unknown routes look like OWN-04 404s
        return problem(exc.status_code, detail, headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # field locations and error types only; the submitted values are never echoed back
        errors = [{"loc": [str(p) for p in e.get("loc", ())], "type": e.get("type", "")} for e in exc.errors()]
        return problem(422, "The request is not valid.", code="validation_error", extra={"errors": errors})

    # Unhandled exceptions are turned into 500 problems by UnhandledErrorMiddleware, which sits inside the CORS,
    # security-header and request-id middleware. A handler registered here for ``Exception`` would run in Starlette's
    # outermost ServerErrorMiddleware instead, and those responses would miss every header (found by the M0 tests).


class UnhandledErrorMiddleware:
    """Innermost middleware: any exception escaping the app becomes a logged, bare 500 problem (HTTP-04)."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def tracking_send(message: Any) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception as exc:
            logger.exception("unhandled error: %s", type(exc).__name__)
            if started:  # the response is already on the wire; nothing safe left to send
                raise
            app = scope.get("app")
            if _is_schema_error(exc) and getattr(getattr(app, "state", None), "schema_outdated", False):
                # The database is behind the code (a migration was not applied): say so instead of a bare 500.
                response = problem(503, DATABASE_OUTDATED, code="database_outdated")
            else:
                response = problem(500, code="internal_error")
            await response(scope, receive, send)


DATABASE_OUTDATED = "The server's database needs an update. An administrator must apply the database migrations."
_SCHEMA_MARKERS = ("no such column", "no such table", "does not exist", "undefinedcolumn", "undefinedtable")


def _is_schema_error(exc: BaseException) -> bool:
    """A database error caused by a missing table or column (never shown to the client, only classified)."""
    from sqlalchemy.exc import OperationalError, ProgrammingError

    return isinstance(exc, OperationalError | ProgrammingError) and any(
        marker in str(exc).lower() for marker in _SCHEMA_MARKERS)
