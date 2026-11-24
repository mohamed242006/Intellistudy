"""Logging with secret redaction (contract SEC-06, SEC-09) and the security event log.

Every handler installed by :func:`configure_logging` passes records through :class:`RedactingFilter`, which masks the
configured secret values and anything that looks like a credential (Bearer tokens, ``sk-`` keys, JWTs). Security events
go to the ``intellistudy.security`` logger; they never carry passwords, tokens, secrets or document text.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable
from contextvars import ContextVar
from typing import Any

REDACTED = "[REDACTED]"
SECURITY_LOGGER = "intellistudy.security"

#: Request id of the request being handled (set by the request-id middleware).
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

_CREDENTIAL_PATTERNS = (
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}"),  # a JWT
    re.compile(r"(?i)(api[_-]?key|secret|password|token)(\"?\s*[:=]\s*\"?)[^\s\",&]{6,}"),
)


def redact(text: str, secrets: Iterable[str] = ()) -> str:
    """``text`` with every known secret value and every credential-shaped string replaced by ``[REDACTED]``."""
    for secret in sorted((s for s in secrets if s), key=len, reverse=True):
        text = text.replace(secret, REDACTED)
    for pattern in _CREDENTIAL_PATTERNS:
        if pattern.groups >= 2:
            text = pattern.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", text)
        else:
            text = pattern.sub(REDACTED, text)
    return text


class RedactingFilter(logging.Filter):
    """Masks secrets in the final message of every record; never drops a record."""

    def __init__(self, secrets: Iterable[str] = ()) -> None:
        super().__init__()
        self._secrets = tuple(s for s in secrets if s)

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        clean = redact(message, self._secrets)
        if clean != message or record.args:
            record.msg, record.args = clean, None
        if record.exc_info and not record.exc_text:
            record.exc_text = redact(logging.Formatter().formatException(record.exc_info), self._secrets)
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = redact(record.exc_text, self._secrets)
        record.request_id = request_id_var.get()
        return True


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "message": record.getMessage(),
        }
        event = getattr(record, "security_event", None)
        if event is not None:
            payload["security_event"] = event
        if record.exc_text:
            payload["exception"] = record.exc_text
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(secrets: Iterable[str] = (), level: int = logging.INFO) -> None:
    """Install one JSON handler with redaction on the root logger (idempotent)."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_intellistudy", False):
            root.removeHandler(handler)
    handler = logging.StreamHandler()
    handler._intellistudy = True  # type: ignore[attr-defined]
    handler.addFilter(RedactingFilter(secrets))
    handler.setFormatter(_JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level)
    for noisy in ("httpx", "httpcore"):  # per-request INFO lines (URLs) add noise, not information
        logging.getLogger(noisy).setLevel(logging.WARNING)


#: Keys never accepted in security events, whatever the caller passes (SEC-09).
_FORBIDDEN_EVENT_KEYS = frozenset({"password", "token", "access_token", "refresh_token", "secret", "api_key", "text"})


def security_event(event: str, *, level: int = logging.WARNING, **fields: Any) -> None:
    """Write one structured security event (login failure, ownership 404, rate limit, upload rejection, ...)."""
    safe = {k: v for k, v in fields.items() if k.lower() not in _FORBIDDEN_EVENT_KEYS}
    logging.getLogger(SECURITY_LOGGER).log(level, event, extra={"security_event": {"event": event, **safe}})
