"""The LLM usage ledger: the single source of truth for the per-user daily token budget (contract UPL-16).

Finding F-M3-05: M3 summed the tokens of stored messages, so deleting a conversation refunded its usage. Usage is now
recorded per provider call in ``llm_usage``, a table linked only to the user, and committed as soon as the call
returns -- before anything else in the request can fail or be rolled back. Deleting conversations, messages,
summaries, quizzes, documents or courses never changes it. Chat, summaries and quizzes share one budget.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, time, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ai.answering.llm import LLMError
from ai.answering.models import LLMResponse
from ai.answering.models import Message as LLMMessage
from backend.app.core.clock import Clock
from backend.app.core.config import Settings
from backend.app.core.errors import ApiError
from backend.app.core.logging import security_event
from backend.app.db.models import LlmUsage, UsageFeature


class BudgetExhausted(LLMError):
    """Raised by :class:`MeteredLLM` (``check_each_call``) when the budget ran out between calls of one generation."""

    def __init__(self) -> None:
        super().__init__("daily token budget exhausted", retryable=False)


class UsageLedger:
    def __init__(self, settings: Settings, clock: Clock) -> None:
        self._settings = settings
        self._clock = clock

    @property
    def daily_budget(self) -> int:
        return int(self._settings.llm_daily_token_budget)

    def day_start(self) -> datetime:
        now = self._clock.now()
        return datetime.combine(now.date(), time.min, tzinfo=now.tzinfo)

    def seconds_to_reset(self) -> int:
        return max(int((self.day_start() + timedelta(days=1) - self._clock.now()).total_seconds()), 1)

    def used_today(self, session: Session, user_id: str) -> int:
        used = session.scalar(
            select(func.coalesce(func.sum(LlmUsage.prompt_tokens + LlmUsage.completion_tokens), 0))
            .where(LlmUsage.owner_id == user_id, LlmUsage.created_at >= self.day_start()))
        return int(used or 0)

    def remaining(self, session: Session, user_id: str) -> int:
        return max(self.daily_budget - self.used_today(session, user_id), 0)

    def exhausted_error(self) -> ApiError:
        return ApiError(429, "Your daily AI budget is used up. Try again tomorrow.", code="token_budget",
                        headers={"Retry-After": str(self.seconds_to_reset())})

    def check(self, session: Session, user_id: str, *, estimated: int = 0) -> None:
        """Raise 429 ``token_budget`` when the budget is spent, or would be by an ``estimated`` cost (G4-BUD-02)."""
        if self.used_today(session, user_id) + max(estimated, 0) >= self.daily_budget:
            security_event("token_budget_exhausted", user_id=user_id)
            raise self.exhausted_error()

    def record(self, session: Session, user_id: str, feature: UsageFeature, reply: LLMResponse, model: str) -> None:
        """One ledger row per provider call, committed immediately (no content is stored)."""
        session.add(LlmUsage(owner_id=user_id, feature=feature.value, model=(reply.model or model)[:100],
                             prompt_tokens=max(int(reply.prompt_tokens or 0), 0),
                             completion_tokens=max(int(reply.completion_tokens or 0), 0),
                             created_at=self._clock.now()))
        session.commit()


class MeteredLLM:
    """Wraps a provider: every successful call is written to the ledger before its reply is used.

    With ``check_each_call`` the budget is re-checked before every call, so a multi-call generation (map-reduce
    summaries, quiz top-ups) stops as soon as the budget is spent (G4-BUD-03)."""

    def __init__(self, inner: Any, ledger: UsageLedger, session: Session, user_id: str, feature: UsageFeature,
                 *, check_each_call: bool = False) -> None:
        self._inner = inner
        self._ledger = ledger
        self._session = session
        self._user_id = user_id
        self._feature = feature
        self._check_each_call = check_each_call
        self.model_name = str(getattr(inner, "model_name", "unknown"))
        self.calls = 0

    def generate(self, messages: Sequence[LLMMessage], *, temperature: float = 0.0, max_tokens: int = 700
                 ) -> LLMResponse:
        if self._check_each_call and self._ledger.remaining(self._session, self._user_id) <= 0:
            security_event("token_budget_exhausted", user_id=self._user_id)
            raise BudgetExhausted()
        reply: LLMResponse = self._inner.generate(messages, temperature=temperature, max_tokens=max_tokens)
        self.calls += 1
        self._ledger.record(self._session, self._user_id, self._feature, reply, self.model_name)
        return reply
