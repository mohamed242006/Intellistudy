"""Pure-ASGI middleware: request ids, security headers (HTTP-03) and request-body limits (HTTP-06).

Pure ASGI (not ``BaseHTTPMiddleware``) so streaming uploads are never buffered and the body limit also applies to
chunked requests that send no ``Content-Length``.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Iterable

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from backend.app.core.logging import request_id_var

_REQUEST_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")

SECURITY_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"x-frame-options", b"DENY"),
    (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'"),
    (b"cross-origin-resource-policy", b"same-origin"),
)
# Swagger UI loads its own assets; the docs pages get a CSP that allows them (docs are off in prod, HTTP-05).
DOCS_CSP = (
    b"default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    b"style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com; "
    b"frame-ancestors 'none'"
)
DOCS_PATHS = ("/docs", "/redoc")


class RequestIdMiddleware:
    """Accept a well-formed ``X-Request-ID`` or create one; expose it in logs, problem bodies and the response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = dict(scope["headers"]).get(b"x-request-id", b"").decode("latin-1")
        request_id = incoming if _REQUEST_ID.match(incoming) else uuid.uuid4().hex
        token = request_id_var.set(request_id)

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", [])
                message["headers"] = [*message["headers"], (b"x-request-id", request_id.encode("latin-1"))]
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            request_id_var.reset(token)


class SecurityHeadersMiddleware:
    """Add the HTTP-03 headers to every response; ``Cache-Control: no-store`` on every API response."""

    def __init__(self, app: ASGIApp, *, api_prefix: str = "/api/") -> None:
        self.app = app
        self.api_prefix = api_prefix

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope.get("path", "")
        is_docs = path.startswith(DOCS_PATHS)

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [h for h in message.get("headers", []) if h[0].lower() not in {k for k, _ in SECURITY_HEADERS}]
                for name, value in SECURITY_HEADERS:
                    use_docs_csp = name == b"content-security-policy" and is_docs
                    headers.append((name, DOCS_CSP if use_docs_csp else value))
                if path.startswith(self.api_prefix):
                    headers = [h for h in headers if h[0].lower() != b"cache-control"]
                    headers.append((b"cache-control", b"no-store"))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)


class BodySizeLimitMiddleware:
    """Reject request bodies over ``max_bytes`` with 413 (HTTP-06), counting bytes as they arrive.

    ``exempt`` lists (method, full-path regex) pairs for streaming uploads, which enforce their own per-file limit
    (UPL-02). Patterns are anchored and exact: a prefix would exempt unrelated routes.
    """

    def __init__(self, app: ASGIApp, *, max_bytes: int, exempt: Iterable[tuple[str, str]] = ()) -> None:
        self.app = app
        self.max_bytes = max_bytes
        self.exempt = tuple((method, re.compile(pattern)) for method, pattern in exempt)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        exempt = scope["type"] == "http" and any(
            scope.get("method") == method and pattern.fullmatch(scope.get("path", "")) for method, pattern in self.exempt)
        if scope["type"] != "http" or exempt:
            await self.app(scope, receive, send)
            return
        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.max_bytes:
            await _reject_too_large(send)
            return

        received = 0
        too_large = False
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received, too_large
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    too_large = True
                    return {"type": "http.disconnect"}
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if too_large:
                return  # the 413 below replaces whatever the app tries to send
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        await self.app(scope, limited_receive, tracking_send)
        if too_large and not response_started:
            await _reject_too_large(send)


async def _reject_too_large(send: Send) -> None:
    body = json.dumps({
        "type": "about:blank#payload_too_large", "title": "Content Too Large", "status": 413,
        "detail": "The request body is too large.", "request_id": request_id_var.get(),
    }).encode()
    await send({"type": "http.response.start", "status": 413,
                "headers": [(b"content-type", b"application/problem+json"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})
