"""Rate limiting (contract UPL-16, section 9a). Scaffold in M0; routes attach limits from M1 on.

``RateLimiter`` is the interface. ``InMemoryRateLimiter`` is a sliding-window limiter for the single-process demo;
any multi-process or multi-instance deployment must swap in a shared-store implementation (e.g. Redis) before going
live (contract 9a). Exceeding a limit raises ``ApiError(429)`` with ``Retry-After`` and writes a security event.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from fastapi import Request

from backend.app.core.errors import ApiError
from backend.app.core.logging import security_event


@dataclass(frozen=True, slots=True)
class Limit:
    """``max_events`` per ``window_seconds`` for one ``scope`` (e.g. ``login:ip``)."""

    scope: str
    max_events: int
    window_seconds: float


#: Contract 9a defaults. Per-user limits are attached once authentication exists (M1+).
LIMITS: dict[str, Limit] = {
    "login:ip": Limit("login:ip", 5, 60),
    "login:account": Limit("login:account", 5, 60),
    "register:ip": Limit("register:ip", 3, 3600),
    "refresh:user": Limit("refresh:user", 30, 3600),
    "upload:user": Limit("upload:user", 20, 3600),
    "chat:user": Limit("chat:user", 20, 60),
    "summary:user": Limit("summary:user", 10, 3600),
    "quiz:user": Limit("quiz:user", 5, 3600),
    "attempt:start": Limit("attempt:start", 30, 3600),  # start and retry-missed (M5 D5-9)
    "attempt:answer": Limit("attempt:answer", 600, 3600),
    "attempt:submit": Limit("attempt:submit", 30, 3600),
}


class RateLimiter(Protocol):
    def hit(self, limit: Limit, key: str) -> float:
        """Record one event for ``key``; return 0 if allowed, else the seconds until the next event is allowed."""
        ...

    def reset(self) -> None: ...


class InMemoryRateLimiter:
    """Thread-safe sliding window per (scope, key). State is lost on restart (acceptable for the demo)."""

    def __init__(self, clock: Callable[[], float] = time.monotonic, max_keys: int = 100_000) -> None:
        self._clock = clock
        self._events: dict[tuple[str, str], deque[float]] = {}
        self._lock = threading.Lock()
        self._max_keys = max_keys

    def hit(self, limit: Limit, key: str) -> float:
        now = self._clock()
        with self._lock:
            window = self._events.setdefault((limit.scope, key), deque())
            while window and now - window[0] >= limit.window_seconds:
                window.popleft()
            if len(window) >= limit.max_events:
                return max(limit.window_seconds - (now - window[0]), 0.001)
            window.append(now)
            if len(self._events) > self._max_keys:  # bound memory: drop empty / oldest windows
                self._evict(now)
            return 0.0

    def reset(self) -> None:
        with self._lock:
            self._events.clear()

    def _evict(self, now: float) -> None:
        stale = [k for k, w in self._events.items() if not w or now - w[-1] > 3600]
        for k in stale:
            del self._events[k]


def client_ip(request: Request) -> str:
    """The peer address. Behind a reverse proxy this must be replaced by trusted-proxy handling (cloud deployment)."""
    return request.client.host if request.client else "unknown"


def enforce(limiter: RateLimiter, limit: Limit, key: str, *, actor: str = "") -> None:
    """Raise 429 with ``Retry-After`` when ``key`` exceeded ``limit``."""
    wait = limiter.hit(limit, key)
    if wait > 0:
        security_event("rate_limited", scope=limit.scope, actor=actor or key)
        raise ApiError(429, "Too many requests. Try again later.", code="rate_limited",
                       headers={"Retry-After": str(math.ceil(wait))})
