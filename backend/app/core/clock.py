"""One clock for every time-based security decision (token expiry, lockout, refresh lifetimes, rate limits).

Production uses :class:`SystemClock`. Tests inject :class:`FakeClock` so that lockout windows, 7-day idle and 30-day
absolute refresh lifetimes, and JWT leeway edges can be tested exactly, without sleeping.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Current time, timezone-aware UTC."""
        ...

    def monotonic(self) -> float:
        """Seconds on a monotonic scale (rate limiting)."""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        return time.monotonic()


class FakeClock:
    """Manually advanced clock. ``now`` and ``monotonic`` move together."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 11, 24, 12, 0, tzinfo=UTC)
        self._mono = 1_000_000.0

    def now(self) -> datetime:
        return self._now

    def monotonic(self) -> float:
        return self._mono

    def advance(self, seconds: float = 0, **kwargs: float) -> None:
        delta = timedelta(seconds=seconds, **kwargs)
        self._now += delta
        self._mono += delta.total_seconds()
